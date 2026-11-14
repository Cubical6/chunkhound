"""Small, literal-only PHP tree helpers shared by Laravel readers."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from tree_sitter import Node

from chunkhound.domain_model.structure.schema import Span


def text(node: Node | None) -> str:
    return node.text.decode("utf-8") if node is not None and node.text else ""


def walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.named_children:
        yield from walk(child)


def literal_text(node: Node | None) -> str | None:
    if node is None or node.type not in {"string", "encapsed_string"}:
        return None
    raw = text(node)
    if len(raw) < 2 or raw[0] not in {"'", '"'} or raw[-1] != raw[0]:
        return None
    if any(
        c.type not in {"string_content", "escape_sequence"} for c in node.named_children
    ):
        return None
    value = raw[1:-1]
    if raw[0] == "'":
        return re.sub(r"\\([\\'])", r"\1", value)
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "e": "\x1b",
        "f": "\f",
        "\\": "\\",
        '"': '"',
        "$": "$",
    }
    # Do not pretend unsupported numeric/unicode escapes are literal source text.
    if re.search(r"\\(?:[0-7]|x|u)", value):
        return None
    return re.sub(r"\\(.)", lambda m: escapes.get(m[1], m[0]), value)


def literal_list(node: Node | None) -> tuple[str, ...] | None:
    if node is None or node.type != "array_creation_expression":
        return None
    values: list[str] = []
    for element in node.named_children:
        if element.type == "comment":
            continue
        if (
            element.type != "array_element_initializer"
            or len(element.named_children) != 1
        ):
            return None
        value = literal_text(element.named_children[0])
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def arguments(node: Node) -> tuple[Node, ...]:
    args = node.child_by_field_name("arguments")
    if args is None:
        return ()
    return tuple(
        child.named_children[-1] if child.named_children else child
        for child in args.named_children
        if child.type == "argument"
    )


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple[Node, ...]
    node: Node


def method_chain(node: Node) -> tuple[Node, tuple[Call, ...]]:
    calls: list[Call] = []
    while node.type == "member_call_expression":
        calls.append(
            Call(text(node.child_by_field_name("name")), arguments(node), node)
        )
        receiver = node.child_by_field_name("object")
        if receiver is None:
            break
        node = receiver
    return node, tuple(reversed(calls))


def static_call(node: Node) -> tuple[str, Call] | None:
    if node.type != "scoped_call_expression":
        return None
    return text(node.child_by_field_name("scope")).lstrip("\\"), Call(
        text(node.child_by_field_name("name")), arguments(node), node
    )


def span(node: Node, path: str, reader: str) -> Span:
    return Span(
        path=path,
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + (1 if node.end_point.column else 0),
        reader=reader,
    )


def regular_plural(name: str) -> str:
    """The deliberately limited regular-English convention in spec §8.2."""
    if re.search(r"[^aeiou]y$", name):
        return name[:-1] + "ies"
    return name + ("es" if re.search(r"(?:s|x|z|ch|sh)$", name) else "s")
