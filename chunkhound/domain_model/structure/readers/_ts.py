"""Small, framework-neutral helpers for TypeScript syntax trees."""

import ast
import posixpath
from dataclasses import dataclass
from typing import Literal

from tree_sitter import Node
from tree_sitter_language_pack import get_parser


class NonLiteralError(ValueError):
    """An expression requires runtime evaluation."""


NonLiteral = NonLiteralError


def text(node: Node) -> str:
    return node.text.decode("utf-8") if node.text else ""


def parse(source: str, path: str) -> Node:
    language: Literal["tsx", "typescript"] = (
        "tsx" if path.endswith(".tsx") else "typescript"
    )
    return get_parser(language).parse(source.encode("utf-8")).root_node


def declarations(root: Node, kind: str) -> list[Node]:
    result = []
    for child in root.named_children:
        if child.type == kind:
            result.append(child)
        elif child.type == "export_statement":
            result.extend(c for c in child.named_children if c.type == kind)
    return result


@dataclass(frozen=True)
class Decorator:
    name: str
    arguments: tuple[Node, ...]
    node: Node


def decorators(node: Node) -> list[Decorator]:
    """Include decorators attached to the export wrapper of a declaration."""
    children = list(node.named_children)
    if node.parent is not None and node.parent.type == "export_statement":
        children = list(node.parent.named_children) + children
    result = []
    for child in children:
        if child.type != "decorator" or not child.named_children:
            continue
        expression = child.named_children[0]
        if expression.type == "call_expression":
            function = expression.child_by_field_name("function")
            args = expression.child_by_field_name("arguments")
            if function is not None:
                result.append(
                    Decorator(
                        text(function),
                        tuple(args.named_children) if args else (),
                        child,
                    )
                )
        else:
            result.append(Decorator(text(expression), (), child))
    return result


def object_entries(node: Node) -> dict[str, Node]:
    if node.type != "object":
        raise NonLiteral
    result = {}
    for pair in node.named_children:
        if pair.type == "comment":
            continue
        if pair.type == "shorthand_property_identifier":
            result[text(pair)] = pair
            continue
        key = pair.child_by_field_name("key")
        value = pair.child_by_field_name("value")
        if pair.type != "pair" or key is None or value is None:
            raise NonLiteral
        if key.type in {"property_identifier", "identifier"}:
            name = text(key)
        elif key.type == "string":
            key_value = literal(key)
            if not isinstance(key_value, str):
                raise NonLiteral
            name = key_value
        else:
            raise NonLiteral
        if not isinstance(name, str):
            raise NonLiteral
        result[name] = value
    return result


def string_literal(source: str) -> str:
    """Decode JavaScript escapes, including identity escapes, without evaluation."""
    if len(source) < 2 or source[0] not in {"'", '"'} or source[-1] != source[0]:
        raise NonLiteral
    source = source[1:-1]
    result = []
    index = 0
    escapes = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "b": "\b",
        "f": "\f",
        "v": "\v",
        "0": "\0",
    }
    while index < len(source):
        char = source[index]
        index += 1
        if char != "\\":
            result.append(char)
            continue
        if index == len(source):
            raise NonLiteral
        char = source[index]
        index += 1
        if char in {"\n", "\r"}:
            if char == "\r" and source[index : index + 1] == "\n":
                index += 1
            continue
        if char in {"u", "x"}:
            if char == "u" and source[index : index + 1] == "{":
                end = source.find("}", index + 1)
                digits = source[index + 1 : end] if end >= 0 else ""
                index = end + 1
            else:
                length = 4 if char == "u" else 2
                digits = source[index : index + length]
                index += length
                if len(digits) != length:
                    raise NonLiteral
            if not digits or any(c not in "0123456789abcdefABCDEF" for c in digits):
                raise NonLiteral
            try:
                result.append(chr(int(digits, 16)))
            except ValueError:
                raise NonLiteral from None
        else:
            result.append(escapes.get(char, char))
    # Join UTF-16 surrogate pairs while preserving legal lone JS surrogates.
    return (
        "".join(result)
        .encode("utf-16-le", errors="surrogatepass")
        .decode("utf-16-le", errors="surrogatepass")
    )


def literal(node: Node) -> object:
    """Read only literal values; never evaluate identifiers or calls."""
    if node.type == "string":
        return string_literal(text(node))
    if node.type in {"number", "unary_expression"}:
        try:
            value = ast.literal_eval(text(node))
        except (ValueError, SyntaxError):
            raise NonLiteral from None
        if isinstance(value, (int, float)):
            return value
    if node.type in {"true", "false"}:
        return node.type == "true"
    if node.type == "null":
        return None
    if node.type == "array":
        return [literal(c) for c in node.named_children if c.type != "comment"]
    if node.type == "object":
        return {key: literal(value) for key, value in object_entries(node).items()}
    raise NonLiteral


def relative_import(
    root: Node, symbol: str, path: str, paths: set[str]
) -> tuple[str, str] | None:
    """Resolve a named/default relative import within the selected project files."""
    for statement in root.named_children:
        if statement.type != "import_statement":
            continue
        source = statement.child_by_field_name("source")
        if source is None:
            continue
        module = literal(source)
        if not isinstance(module, str) or not module.startswith("."):
            continue
        imported = None
        for clause in statement.named_children:
            if clause.type != "import_clause":
                continue
            for child in clause.named_children:
                if child.type == "identifier" and text(child) == symbol:
                    imported = "default"
                if child.type == "named_imports":
                    for spec in child.named_children:
                        name = spec.child_by_field_name("name")
                        alias = spec.child_by_field_name("alias")
                        if name is not None and text(alias or name) == symbol:
                            imported = text(name)
        if imported is None:
            continue
        base = posixpath.normpath(posixpath.join(posixpath.dirname(path), module))
        # TypeScript commonly uses .js specifiers for emitted ESM files.
        if base.endswith(".js"):
            base = base[:-3]
        for candidate in (
            base,
            base + ".ts",
            base + ".tsx",
            base + "/index.ts",
            base + "/index.tsx",
        ):
            if candidate in paths:
                return candidate, imported
    return None


def enum_values(node: Node) -> tuple[str, ...]:
    body = node.child_by_field_name("body")
    if body is None:
        raise NonLiteral
    values = []
    next_number: int | None = 0
    for member in body.named_children:
        if member.type == "comment":
            continue
        value_node = member.child_by_field_name("value")
        if value_node is not None:
            value = literal(value_node)
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise NonLiteral
            next_number = value + 1 if isinstance(value, int) else None
        elif member.type == "property_identifier" and next_number is not None:
            value = next_number
            next_number += 1
        else:
            raise NonLiteral
        values.append(str(value))
    return tuple(values)
