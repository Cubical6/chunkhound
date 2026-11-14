"""Magento service and controller entry points from own modules only."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from tree_sitter import Node

from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.anchors import anchor_id, hint, operation_hint
from chunkhound.domain_model.structure.contract import Anchor, Finding, Handler, Hint
from chunkhound.domain_model.structure.files import select_files
from chunkhound.domain_model.structure.readers import _php
from chunkhound.domain_model.structure.readers._magento import (
    Module,
    ModuleResolver,
    find_modules,
    is_vendor,
    module_name,
    read_xml,
)
from chunkhound.domain_model.structure.readers._psr4 import PHPType
from chunkhound.domain_model.structure.readers._xml import Element
from chunkhound.domain_model.structure.schema import Span

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext


class MagentoAnchorsReader:
    name = "magento_anchors"
    patterns: tuple[str, ...] = ("**/module.xml",)

    def read(self, ctx: ReadContext) -> None:
        modules = find_modules(ctx, self.name)
        if modules:
            _Anchors(ctx, modules).read()


class _Anchors:
    def __init__(self, ctx: ReadContext, modules: tuple[Module, ...]) -> None:
        self.ctx = ctx
        self.modules = tuple(sorted(modules, key=lambda module: module.path))
        self.own = tuple(module for module in self.modules if not module.third_party)
        self.route_files: dict[tuple[str, str], tuple[Element, ...]] = {}
        self.front_names: dict[tuple[str, str, str], str] = {}
        self.resolver = ModuleResolver(ctx, modules, "magento_anchors")
        self.controller_paths = {
            module.path: tuple(
                f"{module.path}/Controller/{path}"
                for path in select_files(
                    ctx.project_root / module.path / "Controller", ("**/*.php",)
                )
            )
            for module in self.own
            if (ctx.project_root / module.path / "Controller").is_dir()
        }
        self.names = {
            (ctx.repository_of(module.path + "/registration.php").key, name): module
            for module in self.own
            if (name := module_name(ctx, module, "magento_anchors"))
        }

    def xml(self, module: Module, suffix: str) -> tuple[Element, ...]:
        path = f"{module.path}/etc/{suffix}"
        if not (self.ctx.project_root / path).is_file():
            return ()
        return read_xml(self.ctx, path, "magento_anchors")

    def citation(self, span: Span) -> Citation:
        repo = self.ctx.repository_of(span.path)
        return Citation(
            repository=repo.key,
            path=span.path,
            start_line=span.start_line,
            end_line=span.end_line,
            commit=repo.commit,
        )

    def qualify(self, item: PHPType, name: str) -> str:
        if not name.startswith("\\"):
            first, separator, rest = name.partition("\\")
            for alias, target in item.imports.items():
                if alias.casefold() == first.casefold():
                    return target + (separator + rest if separator else "")
        return item.qualify(name)

    def method(
        self, item: PHPType, name: str, seen: frozenset[str] = frozenset()
    ) -> tuple[PHPType, Node] | None:
        identity = item.qualified_name.casefold()
        if identity in seen:
            return None
        seen = seen | {identity}
        body = item.node.child_by_field_name("body")
        if body:
            for node in body.named_children:
                if (
                    node.type == "method_declaration"
                    and _php.text(node.child_by_field_name("name")).casefold()
                    == name.casefold()
                ):
                    return item, node
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
                    trait = self.resolver.resolve(
                        self.qualify(item, _php.text(reference)), item.path
                    )
                    found = self.method(trait, name, seen) if trait else None
                    if found:
                        return found
        for qualified in self.references(item, {"base_clause"}):
            parent = self.resolver.resolve(qualified, item.path)
            found = self.method(parent, name, seen) if parent else None
            if found:
                return found
        return None

    def references(self, item: PHPType, clauses: set[str]) -> list[str]:
        return [
            self.qualify(item, _php.text(reference))
            for clause in item.node.named_children
            if clause.type in clauses
            for reference in clause.named_children
        ]

    def methods(self, item: PHPType, seen: frozenset[str] = frozenset()) -> set[str]:
        identity = item.qualified_name.casefold()
        if identity in seen:
            return set()
        seen = seen | {identity}
        result = set()
        for name in self.references(item, {"class_interface_clause", "base_clause"}):
            match = re.fullmatch(
                r"Magento\\Framework\\App\\Action\\Http(Get|Post|Put|Delete|Patch|Head)ActionInterface",
                name,
                re.IGNORECASE,
            )
            if match:
                result.add(match[1].upper())
            parent = self.resolver.resolve(name, item.path)
            if parent and not is_vendor(parent.path):
                result.update(self.methods(parent, seen))
        return result

    def parameter_types(self, method: Node) -> list[tuple[Node, str]]:
        previous = method.prev_named_sibling
        doc = _php.text(previous) if previous and previous.type == "comment" else ""
        documented = {
            name: annotation
            for annotation, name in re.findall(
                r"@param\s+(\S+)\s+(?:\.\.\.)?\$(\w+)", doc
            )
        }
        parameters = method.child_by_field_name("parameters")
        result = []
        for parameter in parameters.named_children if parameters else ():
            annotation = parameter.child_by_field_name("type")
            name = _php.text(parameter.child_by_field_name("name")).lstrip("$")
            types = _php.text(annotation) if annotation else documented.get(name, "")
            result.append((parameter, types))
        return result

    def input_hints(
        self,
        item: PHPType,
        method: Node,
        fallback: tuple[PHPType, Node] | None = None,
    ) -> list[Hint]:
        result = []
        inherited = self.parameter_types(fallback[1]) if fallback else []
        pseudo_types = {
            "string",
            "int",
            "float",
            "bool",
            "array",
            "mixed",
            "null",
            "self",
            "static",
            "callable",
            "iterable",
            "object",
            "void",
            "false",
            "true",
        }
        for position, (parameter, types) in enumerate(self.parameter_types(method)):
            origin = item
            if not types and fallback and position < len(inherited):
                origin = fallback[0]
                parameter, types = inherited[position]
            for token in re.findall(r"[\\A-Za-z_][\\A-Za-z_0-9]*", types):
                if token.casefold().lstrip("\\") in pseudo_types:
                    continue
                qualified = self.qualify(origin, token)
                if "\\Api\\Data\\" not in "\\" + qualified:
                    continue
                result.append(
                    hint(
                        "input_type",
                        self.citation(
                            _php.span(parameter, origin.path, "magento_anchors")
                        ),
                        name=qualified,
                    )
                )
        return result

    def emit(
        self,
        registration: Element,
        source: str,
        method: str,
        path: str,
        symbol: str,
        target: str,
        controller: PHPType | None = None,
    ) -> None:
        citation = self.citation(registration.span)
        aid = anchor_id(citation.repository, "http", method, path)
        cls, _, action = target.partition("@")
        item = controller or self.resolver.resolve(cls, registration.span.path)
        resolved = self.method(item, action) if item else None
        handler_citation = (
            self.citation(_php.span(resolved[1], resolved[0].path, source))
            if resolved
            else None
        )
        hints = list(operation_hint(method, citation))
        if resolved:
            interface, _, interface_action = symbol.partition("@")
            declaration = (
                self.resolver.resolve(interface, registration.span.path)
                if symbol != target
                else None
            )
            fallback = (
                self.method(declaration, interface_action) if declaration else None
            )
            hints.extend(self.input_hints(*resolved, fallback=fallback))
        else:
            self.ctx.findings.append(
                Finding(
                    kind="unresolved",
                    subject=aid,
                    reason="handler_not_found",
                    detail=target,
                    citations=(citation,),
                )
            )
        self.ctx.anchors.append(
            Anchor(
                id=aid,
                repository=citation.repository,
                kind="http",
                method=method,
                path=path,
                handler=Handler(symbol=symbol, citation=handler_citation),
                source=source,
                citations=(citation,),
                hints=tuple(hints),
            )
        )

    def read(self) -> None:
        preferences = {}
        for suffix in ("di.xml", "webapi_rest/di.xml"):
            for module in self.own:
                for root in self.xml(module, suffix):
                    for preference in root.children:
                        attrs = preference.attributes
                        if (
                            preference.name == "preference"
                            and attrs.get("for")
                            and attrs.get("type")
                        ):
                            repo = self.ctx.repository_of(preference.span.path).key
                            preferences[(repo, attrs["for"].lstrip("\\"))] = attrs[
                                "type"
                            ]
        for module in self.modules:
            for area in ("frontend", "adminhtml"):
                routes = tuple(
                    route
                    for root in self.xml(module, f"{area}/routes.xml")
                    for router in root.children
                    for route in router.children
                    if route.name == "route"
                )
                self.route_files[(module.path, area)] = routes
                for route in routes:
                    route_id = route.attributes.get("id")
                    front = route.attributes.get("frontName")
                    if route_id and front:
                        repo = self.ctx.repository_of(route.span.path).key
                        self.front_names[(repo, area, route_id)] = front
        for module in self.own:
            for root in self.xml(module, "webapi.xml"):
                for route in root.children:
                    attrs = route.attributes
                    if (
                        route.name != "route"
                        or not attrs.get("url")
                        or not attrs.get("method")
                    ):
                        continue
                    for service in route.children:
                        cls = service.attributes.get("class")
                        action = service.attributes.get("method")
                        if service.name != "service" or not cls or not action:
                            continue
                        repo = self.ctx.repository_of(route.span.path).key
                        target = preferences.get((repo, cls.lstrip("\\")), cls)
                        self.emit(
                            route,
                            "magento_webapi",
                            attrs["method"].upper(),
                            attrs["url"],
                            f"{cls}@{action}",
                            f"{target}@{action}",
                        )
            for area in ("frontend", "adminhtml"):
                self.controllers(module, area)

    def controllers(self, module: Module, area: str) -> None:
        for route in self.route_files.get((module.path, area), ()):
            repo = self.ctx.repository_of(route.span.path).key
            route_id = route.attributes.get("id", "")
            front = route.attributes.get("frontName") or self.front_names.get(
                (repo, area, route_id)
            )
            if not front:
                self.ctx.findings.append(
                    Finding(
                        kind="external_reference",
                        subject=None,
                        reason="vendor_not_followed",
                        detail=f"route {route_id}",
                        citations=(self.citation(route.span),),
                    )
                )
                continue
            for reference in route.children:
                target = self.names.get((repo, reference.attributes.get("name", "")))
                if reference.name != "module" or target is None:
                    continue
                base = f"{target.path}/Controller/"
                if area == "adminhtml":
                    base += "Adminhtml/"
                for path in self.controller_paths.get(target.path, ()):
                    if not path.startswith(base) or not path.endswith(".php"):
                        continue
                    relative = PurePosixPath(path[len(base) :])
                    if area == "frontend" and relative.parts[0] == "Adminhtml":
                        continue
                    for item in self.resolver.load(path):
                        if (
                            item.node.type != "class_declaration"
                            or item.name != relative.stem
                            or any(
                                child.type == "abstract_modifier"
                                for child in item.node.named_children
                            )
                        ):
                            continue
                        directory = "_".join(relative.parent.parts).lower()
                        url = "/" + "/".join(
                            segment
                            for segment in (front, directory, item.name.lower())
                            if segment
                        )
                        symbol = f"{item.qualified_name}@execute"
                        for method in sorted(self.methods(item) or {"ANY"}):
                            self.emit(
                                route,
                                f"magento_routes_{area}",
                                method,
                                url,
                                symbol,
                                symbol,
                                controller=item,
                            )
