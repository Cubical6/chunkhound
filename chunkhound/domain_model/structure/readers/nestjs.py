"""NestJS decorator registrations and class-validator input hints."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

from tree_sitter import Node

from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.anchors import anchor_id, hint, operation_hint
from chunkhound.domain_model.structure.contract import Anchor, Finding, Handler, Hint
from chunkhound.domain_model.structure.readers import _ts

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext

HTTP = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Patch": "PATCH",
    "Delete": "DELETE",
    "Options": "OPTIONS",
    "Head": "HEAD",
    "All": "ANY",
}
GRAPHQL = {"Query": "query", "Mutation": "mutation", "Subscription": "subscription"}


@dataclass
class Source:
    path: str
    root: Node
    imports: dict[str, tuple[str, str]]

    def imported(self, decorator: _ts.Decorator, package: str) -> str | None:
        module, name = self.imports.get(decorator.name, ("", ""))
        if module == package:
            return name
        namespace, separator, member = decorator.name.partition(".")
        if separator and self.imports.get(namespace) == (package, "*"):
            return member
        return None


def imports(root: Node) -> dict[str, tuple[str, str]]:
    result = {}
    for statement in root.named_children:
        if statement.type != "import_statement":
            continue
        module = statement.child_by_field_name("source")
        if module is None:
            continue
        for clause in statement.named_children:
            if clause.type != "import_clause":
                continue
            for group in clause.named_children:
                if group.type == "namespace_import":
                    for identifier in group.named_children:
                        if identifier.type == "identifier":
                            result[_ts.text(identifier)] = (
                                str(_ts.literal(module)),
                                "*",
                            )
                if group.type == "named_imports":
                    for spec in group.named_children:
                        name = spec.child_by_field_name("name")
                        alias = spec.child_by_field_name("alias")
                        if name is not None:
                            result[_ts.text(alias or name)] = (
                                str(_ts.literal(module)),
                                _ts.text(name),
                            )
    return result


def named_arguments(node: Node) -> tuple[Node, ...]:
    return tuple(child for child in node.named_children if child.type != "comment")


def read_decorators(node: Node) -> list[_ts.Decorator]:
    return [
        _ts.Decorator(
            d.name, tuple(a for a in d.arguments if a.type != "comment"), d.node
        )
        for d in _ts.decorators(node)
    ]


def declarations(root: Node, kind: str) -> list[Node]:
    result = _ts.declarations(root, kind)
    if kind == "class_declaration":
        result.extend(_ts.declarations(root, "abstract_class_declaration"))
    elif kind == "variable_declarator":
        for declaration_kind in ("lexical_declaration", "variable_declaration"):
            for declaration in _ts.declarations(root, declaration_kind):
                result.extend(
                    child
                    for child in declaration.named_children
                    if child.type == "variable_declarator"
                )
    return sorted(result, key=lambda node: node.start_byte)


def annotation(node: Node) -> str | None:
    value = node.child_by_field_name("type")

    def unwrap(value: Node) -> str | None:
        if value.type == "type_identifier":
            return _ts.text(value)
        children = named_arguments(value)
        if value.type in {"type_annotation", "array_type", "parenthesized_type"}:
            return unwrap(children[0]) if len(children) == 1 else None
        if value.type == "union_type":
            non_null = [c for c in children if _ts.text(c) not in {"null", "undefined"}]
            names = [unwrap(c) for c in non_null]
            if (
                names
                and all(name is not None for name in names)
                and len(set(names)) == 1
            ):
                return names[0]
        return None

    return unwrap(value) if value is not None else None


def literal_value(node: Node) -> object:
    if node.type == "template_string":
        if any(child.type == "template_substitution" for child in node.named_children):
            raise _ts.NonLiteral
        return _ts.string_literal('"' + _ts.text(node)[1:-1] + '"')
    if node.type == "array":
        return [literal_value(child) for child in named_arguments(node)]
    return _ts.literal(node)


def option(node: Node, wanted: str) -> Node | None:
    """Read only the needed key; unrelated options need not be literal."""
    result = None
    spread = False
    for entry in node.named_children:
        if entry.type == "spread_element":
            spread = True
            continue
        key = entry.child_by_field_name("key") or entry.child_by_field_name("name")
        if entry.type == "shorthand_property_identifier":
            key = entry
        if key is None:
            continue
        if key.type == "string":
            name = _ts.literal(key)
        else:
            name = _ts.text(key)
        if name == wanted:
            result = entry.child_by_field_name("value")
            if result is None:
                raise _ts.NonLiteral
    if result is None and spread:
        raise _ts.NonLiteral
    return result


def method_name(node: Node) -> str:
    name = node.child_by_field_name("name")
    if name is None or name.type == "computed_property_name":
        raise _ts.NonLiteral
    return str(_ts.literal(name)) if name.type == "string" else _ts.text(name)


def parent_class(node: Node) -> Node | None:
    for child in node.named_children:
        if child.type == "class_heritage":
            for clause in child.named_children:
                if clause.type == "extends_clause" and clause.named_children:
                    return clause.named_children[0]
    return None


def paths(decorator: _ts.Decorator, *, controller: bool = False) -> list[str]:
    if not decorator.arguments:
        return [""]
    value = decorator.arguments[0]
    if controller and value.type == "object":
        path = option(value, "path")
        if path is None:
            return [""]
        value = path
    literal = literal_value(value)
    if isinstance(literal, str):
        return [literal]
    if isinstance(literal, list) and all(isinstance(part, str) for part in literal):
        return literal
    raise _ts.NonLiteral


def graphql_name(decorator: _ts.Decorator, fallback: str) -> str:
    if not decorator.arguments:
        return fallback
    first, *rest = decorator.arguments
    if first.type in {"string", "template_string"}:
        return str(literal_value(first))
    if first.type == "arrow_function":
        if not rest:
            return fallback
        first = rest[0]
    if first.type != "object":
        raise _ts.NonLiteral
    name = option(first, "name")
    if name is None:
        return fallback
    value = literal_value(name)
    if not isinstance(value, str):
        raise _ts.NonLiteral
    return value


class NestJSReader:
    name = "nestjs"
    patterns: tuple[str, ...] = ("**/*.ts",)

    def read(self, ctx: ReadContext) -> None:
        sources = {}
        for path in ctx.paths:
            if path.endswith(".d.ts") or {"vendor", "node_modules"} & set(
                PurePosixPath(path).parts
            ):
                continue
            version = ctx.read(path)
            if version is not None:
                root = _ts.parse("\n".join(version.lines), path)
                sources[path] = Source(path, root, imports(root))
        reader = Registrations(ctx, sources)
        for source in sources.values():
            for cls in declarations(source.root, "class_declaration"):
                for decorator in read_decorators(cls):
                    if source.imported(decorator, "@nestjs/common") == "Controller":
                        reader.controller(source, cls, decorator)
                    elif source.imported(decorator, "@nestjs/graphql") == "Resolver":
                        reader.resolver(source, cls)


class Registrations:
    def __init__(self, ctx: ReadContext, sources: dict[str, Source]) -> None:
        self.ctx = ctx
        self.sources = sources
        self.models = {
            (schema.repository, table.model_class)
            for schema in ctx.schemas
            if schema.reader == "typeorm"
            for table in schema.tables.values()
            if table.model_class
        }

    def citation(self, source: Source, node: Node) -> Citation:
        repo = self.ctx.repository_of(source.path)
        return Citation(
            repository=repo.key,
            path=source.path,
            commit=repo.commit,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
        )

    def dynamic(self, source: Source, decorator: _ts.Decorator) -> None:
        self.ctx.findings.append(
            Finding(
                kind="unresolved",
                subject=None,
                reason="dynamic_registration",
                detail=None,
                citations=(self.citation(source, decorator.node),),
            )
        )

    def methods(self, cls: Node) -> list[tuple[Node, list[_ts.Decorator]]]:
        body = cls.child_by_field_name("body")
        result = []
        pending = []
        if body is not None:
            for member in body.named_children:
                if member.type == "decorator":
                    pending.append(member)
                    continue
                if member.type == "method_definition":
                    # Method decorators are siblings in the TypeScript grammar.
                    decorators = read_decorators(member)
                    for node in pending:
                        expression = node.named_children[0]
                        function = expression.child_by_field_name("function")
                        args = expression.child_by_field_name("arguments")
                        decorators.append(
                            _ts.Decorator(
                                _ts.text(function or expression),
                                named_arguments(args) if args else (),
                                node,
                            )
                        )
                    result.append((member, decorators))
                if member.type != "comment":
                    pending = []
        return result

    def controller(self, source: Source, cls: Node, decorator: _ts.Decorator) -> None:
        try:
            prefixes = paths(decorator, controller=True)
        except _ts.NonLiteral:
            self.dynamic(source, decorator)
            return
        for method, decorators in self.methods(cls):
            for registration in decorators:
                verb = HTTP.get(source.imported(registration, "@nestjs/common") or "")
                if verb is None:
                    continue
                try:
                    method_name(method)
                    suffixes = paths(registration)
                except _ts.NonLiteral:
                    self.dynamic(source, registration)
                    continue
                for prefix in prefixes:
                    for suffix in suffixes:
                        path = "/" + "/".join(
                            part.strip("/")
                            for part in (prefix, suffix)
                            if part.strip("/")
                        )
                        self.add(source, cls, method, registration, "http", verb, path)

    def resolver(self, source: Source, cls: Node) -> None:
        for method, decorators in self.methods(cls):
            name = method.child_by_field_name("name")
            if name is None:
                continue
            for registration in decorators:
                root = source.imported(registration, "@nestjs/graphql") or ""
                if root not in GRAPHQL:
                    continue
                try:
                    field = graphql_name(registration, method_name(method))
                except _ts.NonLiteral:
                    self.dynamic(source, registration)
                    continue
                self.add(
                    source,
                    cls,
                    method,
                    registration,
                    "graphql",
                    GRAPHQL[root],
                    f"{root}.{field}",
                )

    def module(self, source: Source, module: Node) -> Source | None:
        name = _ts.literal(module)
        if not isinstance(name, str) or not name.startswith("."):
            return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(source.path), name))
        if base.endswith(".js"):
            base = base[:-3]
        for candidate in (base, base + ".ts", base + "/index.ts"):
            target = self.sources.get(candidate)
            if target and (
                self.ctx.repository_of(target.path).key
                == self.ctx.repository_of(source.path).key
            ):
                return target
        return None

    def resolve(
        self,
        source: Source,
        symbol: str,
        kind: str,
        seen: set[tuple[str, str, str]] | None = None,
    ) -> tuple[Source, Node] | None:
        if seen is None:
            seen = set()
        key = (source.path, symbol, kind)
        if key in seen:
            return None
        seen.add(key)
        for node in declarations(source.root, kind):
            name = node.child_by_field_name("name")
            if name is not None and _ts.text(name) == symbol:
                return source, node
            if (
                symbol == "default"
                and node.parent is not None
                and any(c.type == "default" for c in node.parent.children)
            ):
                return source, node
        imported = _ts.relative_import(
            source.root, symbol, source.path, set(self.sources)
        )
        if imported:
            path, imported_name = imported
            target = self.sources[path]
            if (
                self.ctx.repository_of(path).key
                == self.ctx.repository_of(source.path).key
            ):
                found = self.resolve(target, imported_name, kind, seen)
                if found:
                    return found
        for statement in source.root.named_children:
            if statement.type != "export_statement":
                continue
            module = statement.child_by_field_name("source")
            export_target = (
                self.module(source, module) if module is not None else source
            )
            if export_target is None:
                continue
            for clause in statement.named_children:
                if clause.type != "export_clause":
                    continue
                for spec in clause.named_children:
                    name = spec.child_by_field_name("name")
                    alias = spec.child_by_field_name("alias")
                    if name is not None and _ts.text(alias or name) == symbol:
                        found = self.resolve(export_target, _ts.text(name), kind, seen)
                        if found:
                            return found
            if (
                module is not None
                and symbol != "default"
                and any(child.type == "*" for child in statement.children)
            ):
                found = self.resolve(export_target, symbol, kind, seen)
                if found:
                    return found
        return None

    def dto(self, source: Source, symbol: str) -> tuple[Source, Node] | None:
        found = self.resolve(source, symbol, "class_declaration")
        if found:
            parent = parent_class(found[1])
            if parent is not None and parent.type == "call_expression":
                return None
        return found

    def properties(
        self, source: Source, cls: Node, seen: set[tuple[str, int]]
    ) -> list[tuple[Source, Node]]:
        key = (source.path, cls.start_byte)
        if key in seen:
            return []
        seen.add(key)
        body = cls.child_by_field_name("body")
        result = (
            [
                (source, p)
                for p in body.named_children
                if p.type == "public_field_definition"
            ]
            if body
            else []
        )
        parent = parent_class(cls)
        if parent is not None and parent.type == "identifier":
            found = self.dto(source, _ts.text(parent))
            if found:
                result.extend(self.properties(*found, seen))
        return result

    def enum_hint(self, source: Source, decorator: _ts.Decorator) -> Hint | None:
        if not decorator.arguments:
            return None
        symbol = _ts.text(decorator.arguments[0])
        found = self.resolve(source, symbol, "enum_declaration")
        try:
            if found:
                values = _ts.enum_values(found[1])
            else:
                # Literal objects (including `as const`) are common enum substitutes.
                found = self.resolve(source, symbol, "variable_declarator")
                if found is None:
                    return None
                value = found[1].child_by_field_name("value")
                if value is None:
                    return None
                if value.type == "as_expression":
                    value = value.named_children[0]
                obj = _ts.literal(value)
                if not isinstance(obj, dict) or not all(
                    isinstance(v, (str, int, float)) and not isinstance(v, bool)
                    for v in obj.values()
                ):
                    return None
                values = tuple(str(v) for v in obj.values())
                if not values:
                    return None
        except _ts.NonLiteral:
            return None
        name = found[1].child_by_field_name("name")
        if name is None:
            return None
        return hint(
            "enum",
            self.citation(source, decorator.node),
            name=_ts.text(name),
            values=values,
        )

    def input_hints(self, source: Source, cls: Node) -> list[Hint]:
        name = cls.child_by_field_name("name")
        if name is None:
            return []
        result = [hint("input_type", self.citation(source, cls), name=_ts.text(name))]
        for owner, prop in self.properties(source, cls, set()):
            prop_name = prop.child_by_field_name("name")
            if prop_name is None:
                continue
            decorators = read_decorators(prop)
            nested = annotation(prop)
            for decorator in decorators:
                validator = owner.imported(decorator, "class-validator")
                if validator:
                    result.append(
                        hint(
                            "input_rule",
                            self.citation(owner, decorator.node),
                            name=_ts.text(prop_name),
                            value=_ts.text(decorator.node),
                        )
                    )
                    if validator == "IsEnum":
                        enum = self.enum_hint(owner, decorator)
                        if enum:
                            result.append(enum)
            if any(
                owner.imported(d, "class-validator") == "ValidateNested"
                for d in decorators
            ):
                for decorator in decorators:
                    if (
                        owner.imported(decorator, "class-transformer") == "Type"
                        and decorator.arguments
                    ):
                        arrow = decorator.arguments[0]
                        body = arrow.child_by_field_name("body")
                        if (
                            arrow.type == "arrow_function"
                            and body is not None
                            and body.type == "identifier"
                        ):
                            nested = _ts.text(body)
            found = self.dto(owner, nested) if nested else None
            if found:
                target, child = found
                child_name = child.child_by_field_name("name")
                if child_name is not None:
                    result.append(
                        hint(
                            "input_type",
                            self.citation(target, child),
                            name=_ts.text(child_name),
                        )
                    )
        return result

    def add(
        self,
        source: Source,
        cls: Node,
        method: Node,
        decorator: _ts.Decorator,
        kind: Literal["http", "graphql"],
        verb: str,
        path: str,
    ) -> None:
        cls_name = cls.child_by_field_name("name")
        if cls_name is None:
            return
        handler_name = method_name(method)
        citation = self.citation(source, decorator.node)
        hints = list(operation_hint(verb, citation))
        parameters = method.child_by_field_name("parameters")
        for parameter in parameters.named_children if parameters else ():
            symbol = annotation(parameter)
            if symbol is None:
                continue
            found = self.resolve(source, symbol, "class_declaration")
            if found:
                name = found[1].child_by_field_name("name")
                if (
                    name is not None
                    and (citation.repository, _ts.text(name)) in self.models
                ):
                    hints.append(
                        hint(
                            "model",
                            self.citation(source, parameter),
                            name=_ts.text(name),
                        )
                    )
            is_input = any(
                source.imported(d, "@nestjs/common") == "Body"
                or source.imported(d, "@nestjs/graphql") == "Args"
                for d in read_decorators(parameter)
            )
            dto = self.dto(source, symbol) if is_input else None
            if dto:
                hints.extend(self.input_hints(*dto))
        self.ctx.anchors.append(
            Anchor(
                id=anchor_id(citation.repository, kind, verb, path),
                repository=citation.repository,
                kind=kind,
                method=verb,
                path=path,
                handler=Handler(
                    symbol=f"{_ts.text(cls_name)}.{handler_name}",
                    citation=self.citation(source, method),
                ),
                source="nestjs",
                citations=(citation,),
                hints=tuple(hints),
            )
        )
