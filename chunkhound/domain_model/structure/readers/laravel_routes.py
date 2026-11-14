"""Literal Laravel registrations and input hints, without executing PHP."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.anchors import anchor_id, hint, operation_hint
from chunkhound.domain_model.structure.contract import Anchor, Finding, Handler, Hint
from chunkhound.domain_model.structure.readers import _php
from chunkhound.domain_model.structure.readers._psr4 import (
    PHPType,
    PSR4Resolver,
    file_scopes,
)
from chunkhound.domain_model.structure.readers.eloquent import MODEL, class_reference

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext

FORM_REQUEST = "Illuminate\\Foundation\\Http\\FormRequest"
COMMAND = "Illuminate\\Console\\Command"
CLOSURES = {"anonymous_function", "arrow_function"}
LOOPS = {"foreach_statement", "for_statement", "while_statement", "do_statement"}
HTTP = {"get", "head", "post", "put", "patch", "delete", "options", "any", "match"}


def _facade(origin: PHPType, scope: str) -> str:
    qualified = origin.qualify(scope)
    for name in ("Route", "Artisan", "Validator"):
        if qualified in {name, "Illuminate\\Support\\Facades\\" + name}:
            return name
    return ""


def _method(item: PHPType, name: str) -> Node | None:
    body = item.node.child_by_field_name("body")
    return (
        next(
            (
                n
                for n in body.named_children
                if n.type == "method_declaration"
                and _php.text(n.child_by_field_name("name")).lower() == name.lower()
            ),
            None,
        )
        if body
        else None
    )


def _path(prefix: str, path: str) -> str:
    return "/" + "/".join(p.strip("/") for p in (prefix, path) if p.strip("/"))


def _parameter(resource: str) -> str:
    # Laravel-compatible regular English singulars; no guessed irregular nouns.
    for pattern, replacement in (
        (r"(house|movie)s$", r"\1"),
        (r"([^aeiouy]|qu)ies$", r"\1y"),
        (r"(ss|x|ch|sh|zz)es$", r"\1"),
        (r"uses$", "us"),
        (r"(ss|us)$", r"\1"),
        (r"s$", ""),
    ):
        if re.search(pattern, resource, re.IGNORECASE):
            resource = re.sub(pattern, replacement, resource, flags=re.IGNORECASE)
            break
    return resource.replace("-", "_")


class LaravelRoutesReader:
    name = "laravel_routes"
    patterns: tuple[str, ...] = ("**/*.php", "**/composer.json")

    def read(self, ctx: ReadContext) -> None:
        _Routes(ctx, self.name).read()


class _Routes:
    def __init__(self, ctx: ReadContext, name: str) -> None:
        self.ctx = ctx
        self.name = name
        self.resolver = PSR4Resolver(
            ctx, tuple(p for p in ctx.paths if p.endswith("composer.json"))
        )

    def citation(self, origin: PHPType, node: Node) -> Citation:
        span = _php.span(node, origin.path, self.name)
        repo = self.ctx.repository_of(origin.path)
        return Citation(
            repository=repo.key,
            path=span.path,
            start_line=span.start_line,
            end_line=span.end_line,
            commit=repo.commit,
        )

    def unresolved(
        self,
        origin: PHPType,
        node: Node,
        reason: str,
        subject: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.ctx.findings.append(
            Finding(
                kind="unresolved",
                subject=subject,
                reason=reason,
                detail=detail,
                citations=(self.citation(origin, node),),
            )
        )

    def extends(
        self, item: PHPType, target: str, seen: frozenset[str] = frozenset()
    ) -> bool:
        if item.qualified_name in seen:
            return False
        base = next(
            (n for n in item.node.named_children if n.type == "base_clause"), None
        )
        if base is None or not base.named_children:
            return False
        name = _php.text(base.named_children[0])
        if item.qualify(name) == target:
            return True
        parent = self.resolver.resolve(name, item)
        return bool(
            parent and self.extends(parent, target, seen | {item.qualified_name})
        )

    def method(
        self, item: PHPType, name: str, seen: frozenset[str] = frozenset()
    ) -> tuple[PHPType, Node] | None:
        if item.qualified_name in seen:
            return None
        method = _method(item, name)
        if method is not None:
            return item, method
        seen = seen | {item.qualified_name}
        body = item.node.child_by_field_name("body")
        if body is not None:
            for use in body.named_children:
                if use.type != "use_declaration":
                    continue
                for reference in use.named_children:
                    if reference.type not in {
                        "name",
                        "qualified_name",
                        "relative_name",
                    }:
                        continue
                    trait = self.resolver.resolve(_php.text(reference), item)
                    found = self.method(trait, name, seen) if trait else None
                    if found:
                        return found
        base = next(
            (n for n in item.node.named_children if n.type == "base_clause"), None
        )
        parent = (
            self.resolver.resolve(_php.text(base.named_children[0]), item)
            if base and base.named_children
            else None
        )
        return (
            self.method(parent, name, seen | {item.qualified_name}) if parent else None
        )

    def read(self) -> None:
        for path in self.ctx.paths:
            if not path.endswith(".php"):
                continue
            for item in self.resolver.load(path):
                if not self.extends(item, COMMAND):
                    continue
                if any(n.type == "abstract_modifier" for n in item.node.named_children):
                    continue
                for node in _php.walk(item.node):
                    if (
                        node.type != "property_element"
                        or _php.text(node.child_by_field_name("name")) != "$signature"
                    ):
                        continue
                    signature = _php.literal_text(
                        node.child_by_field_name("default_value")
                    )
                    if signature is None:
                        self.unresolved(
                            item, node, "non_literal_argument", detail="$signature"
                        )
                    else:
                        self.command(
                            item, node, signature, item.qualified_name + "@handle"
                        )
            repo = self.ctx.repository_of(path)
            relative = PurePosixPath(path).relative_to(repo.path)
            if not relative.parts or relative.parts[0] != "routes":
                continue
            source = self.ctx.read(path)
            if source is None:
                continue
            root = get_parser("php").parse("\n".join(source.lines).encode()).root_node
            for scope in file_scopes(path, root):
                self.scan(scope, scope.node)

    def rules(self, origin: PHPType, node: Node) -> list[Hint]:
        if node.type != "array_creation_expression":
            self.unresolved(
                origin, node, "non_literal_argument", detail="validation rules"
            )
            return []
        result = []
        for element in node.named_children:
            if element.type == "comment":
                continue
            parts = element.named_children
            if element.type != "array_element_initializer" or len(parts) != 2:
                self.unresolved(
                    origin, element, "non_literal_argument", detail="validation rules"
                )
                continue
            name = _php.literal_text(parts[0])
            value = _php.literal_text(parts[1])
            if parts[1].type == "array_creation_expression":
                value = _php.text(parts[1])
            if name is None or value is None:
                self.unresolved(
                    origin, element, "non_literal_argument", detail="validation rules"
                )
                continue
            result.append(
                hint(
                    "input_rule", self.citation(origin, element), name=name, value=value
                )
            )
        return result

    def hints(self, origin: PHPType, handler: Node) -> list[Hint]:
        result = []
        parameters = handler.child_by_field_name("parameters")
        if parameters:
            for parameter in parameters.named_children:
                annotation = parameter.child_by_field_name("type")
                for name in _php.text(annotation).lstrip("?").split("|"):
                    name = name.strip()
                    if not name:
                        continue
                    qualified = origin.qualify(name)
                    item = self.resolver.resolve(name, origin)
                    citation = self.citation(origin, parameter)
                    known = any(
                        s.repository == citation.repository
                        and (
                            any(t.model_class == qualified for t in s.tables.values())
                            or any(c.model_class == qualified for c in s.claims)
                        )
                        for s in self.ctx.schemas
                    )
                    if known or (item is not None and self.extends(item, MODEL)):
                        result.append(hint("model", citation, name=qualified))
                    if item is not None and self.extends(item, FORM_REQUEST):
                        result.append(
                            hint("input_type", citation, name=item.qualified_name)
                        )
                        rules = self.method(item, "rules")
                        if rules:
                            owner, method = rules
                            returns = [
                                n
                                for n in _php.walk(method)
                                if n.type == "return_statement"
                            ]
                            if len(returns) == 1 and returns[0].named_children:
                                result.extend(
                                    self.rules(owner, returns[0].named_children[0])
                                )
                            else:
                                self.unresolved(
                                    owner,
                                    method,
                                    "non_literal_argument",
                                    detail="rules",
                                )
        body = handler.child_by_field_name("body")
        if body:
            for node in _php.walk(body):
                args = _php.arguments(node)
                if (
                    node.type == "member_call_expression"
                    and _php.text(node.child_by_field_name("name")) == "validate"
                    and _php.text(node.child_by_field_name("object")) == "$request"
                    and args
                ):
                    result.extend(self.rules(origin, args[0]))
                static = _php.static_call(node)
                if (
                    static
                    and _facade(origin, static[0]) == "Validator"
                    and static[1].name == "make"
                    and len(args) > 1
                ):
                    result.extend(self.rules(origin, args[1]))
        return result

    def handler(
        self, origin: PHPType, node: Node, controller: str | None
    ) -> str | Node | None:
        if node.type in CLOSURES:
            return node
        name = class_reference(node)
        if name:
            return origin.qualify(name) + "@__invoke"
        value = _php.literal_text(node)
        if value is not None:
            if "@" in value:
                cls, method = value.split("@", 1)
                return (
                    (
                        origin.qualify(cls)
                        if cls.split("\\")[0] in origin.imports
                        else cls.lstrip("\\")
                    )
                    + "@"
                    + method
                )
            if (
                controller
                and self.resolver.resolve("\\" + value.lstrip("\\"), origin) is None
            ):
                return controller + "@" + value
            return value.lstrip("\\") + "@__invoke"
        if node.type == "array_creation_expression":
            elements = [n for n in node.named_children if n.type != "comment"]
            for element in elements:
                parts = element.named_children
                if len(parts) == 2 and _php.literal_text(parts[0]) == "uses":
                    return self.handler(origin, parts[1], controller)
            if len(elements) == 2 and all(len(n.named_children) == 1 for n in elements):
                cls_node, method_node = (n.named_children[0] for n in elements)
                reference = class_reference(cls_node)
                class_name = (
                    origin.qualify(reference)
                    if reference
                    else _php.literal_text(cls_node)
                )
                method_name = _php.literal_text(method_node)
                if class_name and method_name:
                    return class_name.lstrip("\\") + "@" + method_name
        return None

    def emit(
        self,
        origin: PHPType,
        node: Node,
        kind: Literal["http", "command"],
        method: str | None,
        path: str,
        target: str | Node,
    ) -> None:
        citation = self.citation(origin, node)
        aid = anchor_id(citation.repository, kind, method, path)
        hints = list(operation_hint(method, citation)) if kind == "http" else []
        if isinstance(target, Node):
            handler = Handler(symbol="closure", citation=self.citation(origin, target))
            hints.extend(self.hints(origin, target))
        else:
            cls, _, action = target.partition("@")
            item = self.resolver.resolve("\\" + cls, origin)
            resolved = self.method(item, action) if item else None
            handler = Handler(
                symbol=target, citation=self.citation(*resolved) if resolved else None
            )
            if resolved:
                hints.extend(self.hints(*resolved))
            else:
                self.unresolved(origin, node, "handler_not_found", aid, target)
        self.ctx.anchors.append(
            Anchor(
                id=aid,
                repository=citation.repository,
                kind=kind,
                method=method,
                path=path,
                handler=handler,
                source=self.name,
                citations=(citation,),
                hints=tuple(hints),
            )
        )

    def command(
        self, origin: PHPType, node: Node, signature: str, target: str | Node
    ) -> None:
        name = re.split(r"[\s{]", signature.lstrip(), maxsplit=1)[0]
        if name:
            self.emit(origin, node, "command", None, name, target)
        else:
            self.unresolved(
                origin, node, "non_literal_argument", detail="command signature"
            )

    def scan(
        self,
        origin: PHPType,
        node: Node,
        prefix: str = "",
        controller: str | None = None,
        dynamic: bool = False,
    ) -> None:
        dynamic = dynamic or node.type in LOOPS
        callback_loop = (
            node.type == "member_call_expression"
            and _php.text(node.child_by_field_name("name")) in {"each", "map"}
        ) or (
            node.type == "function_call_expression"
            and _php.text(node.child_by_field_name("function")).lstrip("\\")
            in {"array_map", "array_walk"}
        )
        if callback_loop:
            arguments = node.child_by_field_name("arguments")
            for child in node.named_children:
                if child != arguments:
                    self.scan(origin, child, prefix, controller, dynamic)
            for argument in _php.arguments(node):
                callback_node = argument
                while (
                    callback_node.type == "parenthesized_expression"
                    and len(callback_node.named_children) == 1
                ):
                    callback_node = callback_node.named_children[0]
                # Receiver and non-callback arguments are evaluated just once.
                self.scan(
                    origin,
                    argument,
                    prefix,
                    controller,
                    dynamic or callback_node.type in CLOSURES,
                )
            return
        base, chain = _php.method_chain(node)
        static = _php.static_call(base)
        if static and _facade(origin, static[0]) in {"Route", "Artisan"}:
            facade, first = static
            calls = (first, *chain)
            if _facade(origin, facade) == "Artisan":
                if first.name == "command" and len(first.args) > 1:
                    signature = _php.literal_text(first.args[0])
                    if (
                        signature is not None
                        and first.args[1].type in CLOSURES
                        and not dynamic
                    ):
                        self.command(origin, node, signature, first.args[1])
                    else:
                        self.unresolved(origin, node, "dynamic_registration")
                return
            for call in calls:
                if call.name == "prefix":
                    value = _php.literal_text(call.args[0]) if call.args else None
                    dynamic = dynamic or value is None
                    prefix = _path(prefix, value or "")
                elif call.name == "controller":
                    value = class_reference(call.args[0]) if call.args else None
                    literal = _php.literal_text(call.args[0]) if call.args else None
                    controller = origin.qualify(value) if value else literal
                    dynamic = dynamic or controller is None
                elif call.name == "group":
                    if len(call.args) > 1:
                        attributes = call.args[0]
                        if attributes.type != "array_creation_expression":
                            dynamic = True
                        else:
                            for element in attributes.named_children:
                                if element.type == "comment":
                                    continue
                                parts = element.named_children
                                key = (
                                    _php.literal_text(parts[0])
                                    if len(parts) == 2
                                    else None
                                )
                                if key == "prefix":
                                    value = _php.literal_text(parts[1])
                                    dynamic = dynamic or value is None
                                    prefix = _path(prefix, value or "")
                                elif key == "controller":
                                    reference = class_reference(parts[1])
                                    controller = (
                                        origin.qualify(reference)
                                        if reference
                                        else _php.literal_text(parts[1])
                                    )
                                    dynamic = dynamic or controller is None
                                elif key is None:
                                    dynamic = True
                    callback = call.args[-1] if call.args else None
                    if callback is not None and callback.type in CLOSURES:
                        body = callback.child_by_field_name("body")
                        if body is not None:
                            self.scan(origin, body, prefix, controller, dynamic)
                    else:
                        self.unresolved(origin, node, "dynamic_registration")
                    return
                elif call.name in {"resources", "apiResources"}:
                    registrations = call.args[0] if call.args else None
                    if (
                        registrations is None
                        or registrations.type != "array_creation_expression"
                    ):
                        self.unresolved(origin, node, "dynamic_registration")
                        return
                    for element in registrations.named_children:
                        if element.type == "comment":
                            continue
                        parts = element.named_children
                        if len(parts) != 2:
                            self.unresolved(origin, element, "dynamic_registration")
                            continue
                        single = _php.Call(
                            call.name[:-1], (*parts, *call.args[1:]), element
                        )
                        self.route(
                            origin, element, single, calls, prefix, controller, dynamic
                        )
                    return
                elif call.name in HTTP | {"resource", "apiResource"}:
                    self.route(origin, node, call, calls, prefix, controller, dynamic)
                    return
                elif call.name in {"view", "redirect", "permanentRedirect"}:
                    return
            return
        for child in node.named_children:
            self.scan(origin, child, prefix, controller, dynamic)

    def route(
        self,
        origin: PHPType,
        node: Node,
        call: _php.Call,
        calls: tuple[_php.Call, ...],
        prefix: str,
        controller: str | None,
        dynamic: bool,
    ) -> None:
        args = call.args
        if call.name == "match":
            methods = _php.literal_list(args[0]) if args else None
            literal_method = _php.literal_text(args[0]) if args else None
            if literal_method is not None:
                methods = (literal_method,)
            args = args[1:]
            if methods is None:
                self.unresolved(origin, node, "dynamic_registration")
                return
        else:
            methods = (call.name,)
        path = _php.literal_text(args[0]) if args else None
        target = self.handler(origin, args[1], controller) if len(args) > 1 else None
        if call.name in {"resource", "apiResource"} and len(args) > 1:
            reference = class_reference(args[1])
            target = (
                origin.qualify(reference) if reference else _php.literal_text(args[1])
            )
        if dynamic or path is None or target is None:
            self.unresolved(origin, node, "dynamic_registration")
            return
        if call.name in {"resource", "apiResource"}:
            # Resource controllers are class references, not invokable handlers.
            if not isinstance(target, str):
                self.unresolved(origin, node, "dynamic_registration")
                return
            cls = target.partition("@")[0]
            options = list(calls)
            parameters: dict[str, str] = {}
            shallow = False
            filters: list[tuple[str, tuple[str, ...]]] = []
            if len(args) > 2:
                config = args[2]
                if config.type != "array_creation_expression":
                    self.unresolved(
                        origin,
                        config,
                        "non_literal_argument",
                        detail="resource options",
                    )
                    return
                for element in config.named_children:
                    if element.type == "comment":
                        continue
                    parts = element.named_children
                    key = _php.literal_text(parts[0]) if len(parts) == 2 else None
                    if key is None:
                        self.unresolved(
                            origin,
                            element,
                            "non_literal_argument",
                            detail="resource options",
                        )
                        return
                    if key in {"only", "except", "parameters", "shallow"}:
                        options.append(_php.Call(key, (parts[1],), element))
            for option in options:
                if option.name == "parameters":
                    mapping = option.args[0] if len(option.args) == 1 else None
                    if mapping is None or mapping.type != "array_creation_expression":
                        self.unresolved(
                            origin, node, "non_literal_argument", detail="parameters"
                        )
                        return
                    for element in mapping.named_children:
                        if element.type == "comment":
                            continue
                        parts = element.named_children
                        key = _php.literal_text(parts[0]) if len(parts) == 2 else None
                        value = _php.literal_text(parts[1]) if len(parts) == 2 else None
                        if key is None or value is None:
                            self.unresolved(
                                origin,
                                node,
                                "non_literal_argument",
                                detail="parameters",
                            )
                            return
                        parameters[key] = value.replace("-", "_")
                    continue
                if option.name == "shallow":
                    value = (
                        _php.text(option.args[0]).lower()
                        if len(option.args) == 1
                        else "true"
                        if not option.args
                        else ""
                    )
                    if value not in {"true", "false"}:
                        self.unresolved(
                            origin, node, "non_literal_argument", detail="shallow"
                        )
                        return
                    shallow = value == "true"
                    continue
                if option.name not in {"only", "except"}:
                    continue
                names = (
                    _php.literal_list(option.args[0]) if len(option.args) == 1 else None
                )
                if names is None:
                    literals = tuple(_php.literal_text(n) for n in option.args)
                    if not literals or any(n is None for n in literals):
                        self.unresolved(
                            origin, node, "non_literal_argument", detail=option.name
                        )
                        return
                    names = tuple(n for n in literals if n is not None)
                filters.append((option.name, names))
            # Dots in a group prefix are literal, not resource nesting separators.
            components = path.strip("/").split(".")
            wildcards = [
                parameters.get(
                    part,
                    parameters.get(
                        part.split("/")[-1], _parameter(part.split("/")[-1])
                    ),
                )
                for part in components
            ]
            ancestors = "/".join(
                part + "/{" + wildcard + "}"
                for part, wildcard in zip(components[:-1], wildcards[:-1])
            )
            resource = _path(prefix, _path(ancestors, components[-1]))
            member_base = _path(prefix, components[-1]) if shallow else resource
            member = _path(member_base, "{" + wildcards[-1] + "}")
            actions = [
                ("index", "GET", resource),
                ("store", "POST", resource),
                ("show", "GET", member),
                ("update", "PUT", member),
                ("update", "PATCH", member),
                ("destroy", "DELETE", member),
            ]
            if call.name == "resource":
                actions.extend(
                    [
                        ("create", "GET", _path(resource, "create")),
                        ("edit", "GET", _path(member, "edit")),
                    ]
                )
            for option_name, names in filters:
                actions = [
                    a for a in actions if (a[0] in names) == (option_name == "only")
                ]
            for action, method, route_path in actions:
                self.emit(origin, node, "http", method, route_path, cls + "@" + action)
        else:
            for method in methods:
                self.emit(
                    origin, node, "http", method.upper(), _path(prefix, path), target
                )
