"""Eloquent models provide lower-source claims, never storage tables."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tree_sitter import Node

from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.contract import Finding
from chunkhound.domain_model.structure.readers import _php
from chunkhound.domain_model.structure.readers._psr4 import PHPType, PSR4Resolver
from chunkhound.domain_model.structure.schema import Constraint, Schema, TableClaims

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext


MODEL = "Illuminate\\Database\\Eloquent\\Model"


def snake_case(name: str) -> str:
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def class_reference(node: Node | None) -> str | None:
    if node is None or node.type != "class_constant_access_expression":
        return None
    children = node.named_children
    if len(children) != 2 or _php.text(children[-1]).lower() != "class":
        return None
    return _php.text(children[0])


class EloquentReader:
    name = "eloquent"
    patterns: tuple[str, ...] = ("**/*.php", "**/composer.json")

    def read(self, ctx: ReadContext) -> None:
        resolver = PSR4Resolver(
            ctx, tuple(p for p in ctx.paths if p.endswith("composer.json"))
        )
        types = [
            item
            for path in ctx.paths
            if path.endswith(".php")
            for item in resolver.load(path)
        ]
        schemas: dict[str, Schema] = {}

        def unresolved(item: PHPType, node: Node, reason: str, detail: str) -> None:
            span = _php.span(node, item.path, self.name)
            repo = ctx.repository_of(item.path)
            ctx.findings.append(
                Finding(
                    kind="unresolved",
                    subject=None,
                    reason=reason,
                    detail=detail,
                    citations=(
                        Citation(
                            repository=repo.key,
                            path=span.path,
                            start_line=span.start_line,
                            end_line=span.end_line,
                            commit=repo.commit,
                        ),
                    ),
                )
            )

        def lineage(item: PHPType, seen: frozenset[str] = frozenset()) -> list[PHPType]:
            if item.qualified_name in seen or item.node.type != "class_declaration":
                return []
            base = next(
                (c for c in item.node.named_children if c.type == "base_clause"), None
            )
            if base is None or not base.named_children:
                return []
            name = _php.text(base.named_children[0])
            if item.qualify(name) == MODEL:
                return [item]
            parent = resolver.resolve(name, item)
            ancestors = lineage(parent, seen | {item.qualified_name}) if parent else []
            return [*ancestors, item] if ancestors else []

        def properties(chain: list[PHPType]) -> dict[str, tuple[PHPType, Node]]:
            result: dict[str, tuple[PHPType, Node]] = {}
            for owner in chain:
                body = owner.node.child_by_field_name("body")
                if body is None:
                    continue
                for member in body.named_children:
                    if member.type == "property_declaration":
                        for prop in member.named_children:
                            if prop.type == "property_element":
                                value = prop.child_by_field_name("default_value")
                                if value is not None:
                                    result[
                                        _php.text(prop.child_by_field_name("name"))
                                    ] = (owner, value)
                    elif (
                        member.type == "method_declaration"
                        and _php.text(member.child_by_field_name("name")) == "casts"
                    ):
                        returns = [
                            n for n in _php.walk(member) if n.type == "return_statement"
                        ]
                        value = (
                            returns[0].named_children[0]
                            if len(returns) == 1 and returns[0].named_children
                            else member
                        )
                        result["casts()"] = (owner, value)
            return result

        def table_for(item: PHPType) -> str | None:
            chain = lineage(item)
            if not chain:
                return None
            props = properties(chain)
            name = snake_case(item.name)
            repo = ctx.repository_of(item.path).key
            available = {
                name for s in ctx.schemas if s.repository == repo for name in s.tables
            }
            if "$table" in props:
                explicit = _php.literal_text(props["$table"][1])
                return explicit if explicit in available else None
            return next(
                (n for n in (name, _php.regular_plural(name)) if n in available),
                None,
            )

        for item in types:
            chain = lineage(item)
            if not chain or any(
                c.type == "abstract_modifier" for c in item.node.named_children
            ):
                continue
            props = properties(chain)
            if "$table" in props and _php.literal_text(props["$table"][1]) is None:
                owner, value = props["$table"]
                unresolved(owner, value, "non_literal_argument", "$table")
                continue
            table = table_for(item)
            if table is None:
                unresolved(item, item.node, "model_table_unknown", item.qualified_name)
                continue
            repository = ctx.repository_of(item.path).key
            if repository not in schemas:
                schemas[repository] = Schema(self.name, repository)
                ctx.schemas.append(schemas[repository])
            constraints: list[Constraint] = []
            methods: dict[str, tuple[PHPType, Node]] = {}
            for owner in chain:
                body = owner.node.child_by_field_name("body")
                if body is not None:
                    for member in body.named_children:
                        if member.type == "method_declaration":
                            method_name = _php.text(member.child_by_field_name("name"))
                            methods[method_name.lower()] = (owner, member)
            for owner, method in methods.values():
                for call in _php.walk(method):
                    if (
                        call.type != "member_call_expression"
                        or _php.text(call.child_by_field_name("name")) != "belongsTo"
                    ):
                        continue
                    if _php.text(call.child_by_field_name("object")) != "$this":
                        continue
                    args = _php.arguments(call)
                    name = class_reference(args[0]) if args else None
                    target = resolver.resolve(name, owner) if name else None
                    target_table = table_for(target) if target else None
                    if name is None:
                        unresolved(owner, call, "non_literal_argument", "belongsTo")
                        continue
                    if target is None or target_table is None:
                        unresolved(owner, call, "model_table_unknown", name)
                        continue
                    target_props = properties(lineage(target))
                    target_key = (
                        _php.literal_text(target_props["$primaryKey"][1])
                        if "$primaryKey" in target_props
                        else "id"
                    )
                    owner_key = (
                        _php.literal_text(args[2]) if len(args) > 2 else target_key
                    )
                    method_name = _php.text(method.child_by_field_name("name"))
                    default_column = (
                        snake_case(method_name) + "_" + target_key
                        if target_key
                        else None
                    )
                    column = (
                        _php.literal_text(args[1]) if len(args) > 1 else default_column
                    )
                    if column is None or owner_key is None:
                        unresolved(owner, call, "non_literal_argument", "belongsTo")
                        continue
                    constraints.append(
                        Constraint(
                            kind="foreign",
                            columns=(column,),
                            ref_table=target_table,
                            ref_columns=(owner_key,) if owner_key else (),
                            spans=(_php.span(call, owner.path, self.name),),
                        )
                    )
            for key in ("$casts", "casts()"):
                if key not in props:
                    continue
                owner, array = props[key]
                if array.type != "array_creation_expression":
                    unresolved(owner, array, "non_literal_argument", key)
                    continue
                for element in array.named_children:
                    if (
                        element.type != "array_element_initializer"
                        or len(element.named_children) != 2
                    ):
                        continue
                    column_node, value = element.named_children
                    name = class_reference(value)
                    if name is None:
                        literal_name = _php.literal_text(value)
                        if literal_name is None:
                            unresolved(owner, element, "non_literal_argument", key)
                            continue
                        # Class strings are absolute PHP names, unlike ::class.
                        enum = resolver.resolve("\\" + literal_name.lstrip("\\"), owner)
                        # Ordinary scalar casts and custom cast classes add nothing.
                        if enum is None or enum.node.type != "enum_declaration":
                            continue
                    else:
                        enum = resolver.resolve(name, owner)
                        if enum is not None and enum.node.type != "enum_declaration":
                            continue
                    if enum is None or not any(
                        c.type == "primitive_type" for c in enum.node.named_children
                    ):
                        continue
                    column = _php.literal_text(column_node)
                    if column is None:
                        unresolved(owner, element, "non_literal_argument", key)
                        continue
                    values: list[str] = []
                    for case in _php.walk(enum.node):
                        if case.type != "enum_case":
                            continue
                        case_value = case.child_by_field_name("value")
                        literal = _php.literal_text(case_value)
                        if case_value is not None and case_value.type in {
                            "integer",
                            "unary_op_expression",
                        }:
                            raw = (
                                _php.text(case_value).replace("_", "").replace(" ", "")
                            )
                            if re.fullmatch(
                                r"[+-]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|[0-9]+)",
                                raw,
                            ):
                                sign = -1 if raw.startswith("-") else 1
                                digits = raw.lstrip("+-")
                                base = 8 if re.fullmatch(r"0[0-7]+", digits) else 0
                                try:
                                    literal = str(sign * int(digits, base))
                                except ValueError:
                                    literal = None
                        if literal is None:
                            break
                        values.append(literal)
                    else:
                        if values:
                            constraints.append(
                                Constraint(
                                    kind="value",
                                    columns=(column,),
                                    allowed_values=tuple(values),
                                    spans=(_php.span(element, owner.path, self.name),),
                                )
                            )
                        continue
                    unresolved(owner, element, "non_literal_argument", key)
            schemas[repository].claims.append(
                TableClaims(
                    table=table,
                    model_class=item.qualified_name,
                    span=_php.span(item.node, item.path, self.name),
                    constraints=tuple(constraints),
                )
            )
