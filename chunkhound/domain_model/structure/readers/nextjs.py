"""Next.js filesystem entry points and handler-used Zod input contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

from tree_sitter import Node

from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.anchors import anchor_id, hint, operation_hint
from chunkhound.domain_model.structure.contract import Anchor, Handler, Hint
from chunkhound.domain_model.structure.readers import _ts

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext

METHODS = {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}
FUNCTIONS = {"function_declaration", "function_expression", "arrow_function"}


@dataclass
class Source:
    path: str
    root: Node


def walk(node: Node) -> list[Node]:
    result = []
    stack = [node]
    while stack:
        current = stack.pop()
        result.append(current)
        stack.extend(reversed(current.named_children))
    return result


def binding_names(pattern: Node) -> list[str]:
    """Read bound names, excluding property keys and default-value expressions."""
    result = []
    stack = [pattern]
    while stack:
        node = stack.pop()
        if node.type in {"identifier", "shorthand_property_identifier_pattern"}:
            result.append(_ts.text(node))
        elif node.type in {
            "pair_pattern",
            "assignment_pattern",
            "object_assignment_pattern",
        }:
            bound = node.child_by_field_name(
                "value" if node.type == "pair_pattern" else "left"
            )
            if bound is not None:
                stack.append(bound)
        elif node.type in {"object_pattern", "array_pattern", "rest_pattern"}:
            stack.extend(reversed(node.named_children))
    return result


def exports(root: Node) -> list[tuple[str, Node, Node]]:
    """Export name, handler expression, and registration statement."""
    result: list[tuple[str, Node, Node]] = []
    for statement in root.named_children:
        if statement.type != "export_statement":
            continue
        declaration = statement.child_by_field_name("declaration")
        value = statement.child_by_field_name("value")
        if any(c.type == "default" for c in statement.children):
            expression = declaration if declaration is not None else value
            if expression is not None and expression.type in FUNCTIONS | {"identifier"}:
                result.append(("default", expression, statement))
            continue
        if declaration is not None:
            if declaration.type == "function_declaration":
                name = declaration.child_by_field_name("name")
                if name is not None:
                    result.append((_ts.text(name), declaration, statement))
            elif declaration.type == "lexical_declaration" and any(
                c.type == "const" for c in declaration.children
            ):
                for node in declaration.named_children:
                    name = node.child_by_field_name("name")
                    value = node.child_by_field_name("value")
                    if (
                        node.type == "variable_declarator"
                        and name is not None
                        and name.type in {"object_pattern", "array_pattern"}
                    ):
                        result.extend(
                            (bound, statement, statement)
                            for bound in binding_names(name)
                        )
                    if (
                        node.type == "variable_declarator"
                        and name is not None
                        and name.type == "identifier"
                        and value is not None
                        and value.type in FUNCTIONS | {"identifier"}
                    ):
                        result.append((_ts.text(name), value, statement))
        for clause in statement.named_children:
            if clause.type == "export_clause":
                for spec in clause.named_children:
                    name = spec.child_by_field_name("name")
                    alias = spec.child_by_field_name("alias")
                    if name is not None:
                        result.append((_ts.text(alias or name), name, statement))
    return result


def local_function(root: Node, node: Node, seen: set[str] | None = None) -> Node | None:
    if node.type in FUNCTIONS:
        return node
    if node.type != "identifier":
        return None
    seen = set() if seen is None else seen
    symbol = _ts.text(node)
    if symbol in seen:
        return None
    seen.add(symbol)
    for kind in ("function_declaration", "variable_declarator"):
        for declaration in _ts.module_declarations(root, kind):
            name = declaration.child_by_field_name("name")
            if name is not None and _ts.text(name) == symbol:
                value = (
                    declaration
                    if kind == "function_declaration"
                    else declaration.child_by_field_name("value")
                )
                return local_function(root, value, seen) if value is not None else None
    return None


def route_path(path: str) -> tuple[str, str] | None:
    parts = PurePosixPath(path).parts
    if "app" in parts and parts[-1] in {"route.ts", "route.js"}:
        segments = list(parts[parts.index("app") + 1 : -1])
        if any(part.startswith("_") for part in segments):
            return None
        return "app", "/" + "/".join(
            p
            for p in segments
            if not (p.startswith("(") and p.endswith(")")) and not p.startswith("@")
        )
    if "pages" in parts and path.endswith((".ts", ".js")):
        index = parts.index("pages")
        if index + 1 < len(parts) and parts[index + 1] == "api":
            segments = list(parts[index + 1 :])
            if any(part.startswith("_") for part in segments[1:-1]):
                return None
            segments[-1] = segments[-1].rsplit(".", 1)[0]
            if segments[-1] == "index":
                segments.pop()
            return "pages", "/" + "/".join(segments)
    return None


def server_file(root: Node) -> bool:
    first = next((c for c in root.named_children if c.type != "comment"), None)
    if first is None or first.type != "expression_statement":
        return False
    expression = next((c for c in first.named_children if c.type != "comment"), None)
    return (
        expression is not None
        and expression.type == "string"
        and _ts.literal(expression) == "use server"
    )


def zod_names(root: Node) -> set[str]:
    result: set[str] = set()
    for statement in root.named_children:
        module = statement.child_by_field_name("source")
        if (
            statement.type != "import_statement"
            or module is None
            or _ts.literal(module) not in {"zod", "zod/v4", "zod/v3"}
        ):
            continue
        for node in walk(statement):
            if node.type == "import_clause":
                result.update(
                    _ts.text(c) for c in node.named_children if c.type == "identifier"
                )
            if node.type == "import_specifier":
                name = node.child_by_field_name("name")
                alias = node.child_by_field_name("alias")
                if name is not None and _ts.text(name) == "z":
                    result.add(_ts.text(alias or name))
            elif node.type == "namespace_import":
                result.update(
                    _ts.text(c) for c in node.named_children if c.type == "identifier"
                )
    return result


def schema_object(node: Node, names: set[str]) -> Node | None:
    """Unwrap chained calls, but never inspect nested argument objects."""
    while node.type == "call_expression":
        function = node.child_by_field_name("function")
        if function is None or function.type != "member_expression":
            return None
        receiver = function.child_by_field_name("object")
        member = function.child_by_field_name("property")
        if receiver is None or member is None:
            return None
        if (
            receiver.type == "identifier"
            and _ts.text(receiver) in names
            and _ts.text(member) == "object"
        ):
            arguments = node.child_by_field_name("arguments")
            args = (
                [c for c in arguments.named_children if c.type != "comment"]
                if arguments
                else []
            )
            return args[0] if len(args) == 1 and args[0].type == "object" else None
        node = receiver
    return None


class NextJSReader:
    name = "nextjs"
    patterns: tuple[str, ...] = ("**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx")

    def read(self, ctx: ReadContext) -> None:
        sources = {}
        for path in ctx.paths:
            if path.endswith(".d.ts") or {"node_modules", "vendor", ".next"} & set(
                PurePosixPath(path).parts
            ):
                continue
            version = ctx.read(path)
            if version is not None:
                sources[path] = Source(
                    path,
                    _ts.parse(
                        "\n".join(version.lines),
                        path,
                        javascript=path.endswith((".js", ".jsx")),
                    ),
                )

        def citation(source: Source, node: Node) -> Citation:
            repo = ctx.repository_of(source.path)
            return Citation(
                repository=repo.key,
                path=source.path,
                commit=repo.commit,
                start_line=node.start_point.row + 1,
                end_line=node.end_point.row + 1,
            )

        def input_hints(source: Source, function: Node) -> list[Hint]:
            body = function.child_by_field_name("body")
            result: list[Hint] = []
            used = set()
            if body is None:
                return result
            # A local binding shadows the module schema only in its own scope.
            shadowed: list[tuple[str, Node]] = []
            for node in walk(function):
                if node.type in FUNCTIONS:
                    # JavaScript parameters are bare patterns, unlike TS wrappers.
                    parameters = node.child_by_field_name("parameters")
                    if parameters is not None:
                        for pattern in parameters.named_children:
                            shadowed.extend(
                                (name, node) for name in binding_names(pattern)
                            )
                    parameter = node.child_by_field_name("parameter")
                    if parameter is not None:
                        shadowed.extend(
                            (name, node) for name in binding_names(parameter)
                        )
                if node.type not in {
                    "variable_declarator",
                    "required_parameter",
                    "optional_parameter",
                    "function_declaration",
                    "class_declaration",
                    "catch_clause",
                    "for_in_statement",
                }:
                    continue
                if (
                    node.type == "for_in_statement"
                    and node.child_by_field_name("kind") is None
                ):
                    continue
                name = (
                    node.child_by_field_name("name")
                    or node.child_by_field_name("pattern")
                    or node.child_by_field_name("parameter")
                    or node.child_by_field_name("left")
                )
                if name is None:
                    continue
                scope = (
                    node
                    if node.type in {"catch_clause", "for_in_statement"}
                    else node.parent
                )
                scopes = FUNCTIONS | {
                    "statement_block",
                    "for_statement",
                    "for_in_statement",
                    "catch_clause",
                }
                if (
                    node.type in {"required_parameter", "optional_parameter"}
                    or (
                        node.parent is not None
                        and node.parent.type == "variable_declaration"
                    )
                    or (
                        node.type == "for_in_statement"
                        and any(c.type == "var" for c in node.children)
                    )
                ):
                    scopes = FUNCTIONS
                while scope is not None and scope.type not in scopes:
                    scope = scope.parent
                if scope is not None:
                    shadowed.extend((bound, scope) for bound in binding_names(name))
            for call in walk(body):
                if call.type != "call_expression":
                    continue
                member = call.child_by_field_name("function")
                if member is None or member.type != "member_expression":
                    continue
                receiver = member.child_by_field_name("object")
                method = member.child_by_field_name("property")
                if (
                    receiver is None
                    or receiver.type != "identifier"
                    or method is None
                    or _ts.text(method)
                    not in {"parse", "safeParse", "parseAsync", "safeParseAsync"}
                    or any(
                        name == _ts.text(receiver)
                        and scope.start_byte <= call.start_byte < scope.end_byte
                        for name, scope in shadowed
                    )
                ):
                    continue
                found = _ts.resolve_symbol(
                    source,
                    _ts.text(receiver),
                    "variable_declarator",
                    sources,
                    lambda p: ctx.repository_of(p).key,
                )
                if found is None:
                    continue
                target, declaration = found
                key = (target.path, declaration.start_byte)
                value = declaration.child_by_field_name("value")
                obj = (
                    schema_object(value, zod_names(target.root))
                    if value is not None
                    else None
                )
                if obj is None or key in used:
                    continue
                used.add(key)
                name = declaration.child_by_field_name("name")
                result.append(
                    hint(
                        "input_type",
                        citation(target, declaration),
                        name=_ts.text(name) if name else None,
                    )
                )
                for pair in obj.named_children:
                    name = pair.child_by_field_name("key")
                    value = pair.child_by_field_name("value")
                    if (
                        pair.type != "pair"
                        or name is None
                        or value is None
                        or name.type
                        not in {"property_identifier", "identifier", "string", "number"}
                    ):
                        continue
                    key_name = (
                        str(_ts.literal(name))
                        if name.type in {"string", "number"}
                        else _ts.text(name)
                    )
                    result.append(
                        hint(
                            "input_rule",
                            citation(target, pair),
                            name=key_name,
                            value=_ts.text(value),
                        )
                    )
            return result

        for source in sources.values():
            repo = ctx.repository_of(source.path)
            relative_path = PurePosixPath(source.path).relative_to(repo.path).as_posix()
            route = route_path(relative_path)
            server = server_file(source.root)
            if route is None and not server:
                continue
            for name, expression, registration in exports(source.root):
                handler_source = source
                function = local_function(source.root, expression)
                if registration.child_by_field_name("source") is not None:
                    function = None
                    for declaration_kind in (
                        "function_declaration",
                        "variable_declarator",
                    ):
                        found_handler = _ts.resolve_symbol(
                            source,
                            name,
                            declaration_kind,
                            sources,
                            lambda p: ctx.repository_of(p).key,
                        )
                        if found_handler is None:
                            continue
                        target, declaration = found_handler
                        value = (
                            declaration
                            if declaration_kind == "function_declaration"
                            else declaration.child_by_field_name("value")
                        )
                        followed = (
                            local_function(target.root, value)
                            if value is not None
                            else None
                        )
                        if followed is not None:
                            handler_source, function = target, followed
                            break
                entrances: list[tuple[Literal["http", "action"], str | None, str]] = []
                if route is not None:
                    router, path = route
                    if router == "app" and name in METHODS:
                        entrances.append(("http", name, path))
                    elif router == "pages" and name == "default":
                        entrances.append(("http", "ANY", path))
                if (
                    server
                    and function is not None
                    and any(c.type == "async" for c in function.children)
                ):
                    entrances.append(("action", None, f"{relative_path}#{name}"))
                for kind, method, path in entrances:
                    repo = ctx.repository_of(source.path)
                    site = citation(source, registration)
                    ctx.anchors.append(
                        Anchor(
                            id=anchor_id(repo.key, kind, method, path),
                            repository=repo.key,
                            kind=kind,
                            method=method,
                            path=path,
                            source=self.name,
                            handler=Handler(
                                symbol=f"{relative_path}#{name}",
                                citation=citation(handler_source, function)
                                if function is not None
                                else site,
                            ),
                            citations=(site,),
                            hints=operation_hint(method, site)
                            + tuple(
                                input_hints(handler_source, function)
                                if function is not None
                                else []
                            ),
                        )
                    )
