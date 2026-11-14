"""Read TypeORM entity declarations without executing TypeScript."""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tree_sitter import Node

from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.contract import Finding
from chunkhound.domain_model.structure.readers import _ts
from chunkhound.domain_model.structure.schema import (
    Column,
    Constraint,
    Schema,
    Span,
    Table,
)

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext


_UNKNOWN = object()


@dataclass
class Entity:
    path: str
    node: Node
    name: str
    table: str
    span: Span
    properties: dict[str, str]


@dataclass
class Relation:
    entity: Entity
    columns: tuple[str, ...]
    target: Node | None
    referenced_columns: tuple[object, ...]
    composite: bool
    span: Span


def snake_case(name: str) -> str:
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


class TypeORMReader:
    name = "typeorm"
    patterns: tuple[str, ...] = ("**/*.ts", "**/*.tsx")

    def read(self, ctx: "ReadContext") -> None:
        roots = {}
        for path in ctx.paths:
            source = ctx.read(path)
            if source is not None:
                roots[path] = _ts.parse("\n".join(source.lines), path)
        paths = set(roots)
        schemas: dict[str, Schema] = {}
        entities: dict[tuple[str, str], Entity] = {}

        def span(path: str, node: Node) -> Span:
            if (
                node.type == "class_declaration"
                and node.parent is not None
                and node.parent.type == "export_statement"
            ):
                node = node.parent
            return Span(
                path=path,
                start_line=node.start_point.row + 1,
                end_line=node.end_point.row + 1,
                reader=self.name,
            )

        def unresolved(
            location: Span,
            reason: str = "non_literal_argument",
            detail: str | None = None,
        ) -> None:
            repo = ctx.repository_of(location.path)
            finding = Finding(
                kind="unresolved",
                subject=None,
                reason=reason,
                detail=detail,
                citations=(
                    Citation(
                        repository=repo.key,
                        path=location.path,
                        start_line=location.start_line,
                        end_line=location.end_line,
                        commit=repo.commit,
                    ),
                ),
            )
            if finding not in ctx.findings:
                ctx.findings.append(finding)

        def options(
            arguments: tuple[Node, ...], used: set[str], location: Span
        ) -> dict[str, object]:
            result: dict[str, object] = {}
            for arg in arguments:
                try:
                    entries = _ts.object_entries(arg)
                except _ts.NonLiteral:
                    unresolved(location)
                    result.update(dict.fromkeys(used, _UNKNOWN))
                    continue
                for key, value in entries.items():
                    if key not in used:
                        continue
                    if key == "enum":
                        result[key] = value
                        continue
                    try:
                        result[key] = _ts.literal(value)
                    except _ts.NonLiteral:
                        unresolved(location)
                        result[key] = _UNKNOWN
            return result

        # Establish table identities first. A duplicate declaration has no members.
        for path, root in roots.items():
            for node in _ts.declarations(root, "class_declaration"):
                decorator = next(
                    (d for d in _ts.decorators(node) if d.name == "Entity"), None
                )
                name_node = node.child_by_field_name("name")
                if decorator is None or name_node is None:
                    continue
                name = _ts.text(name_node)
                location = span(path, node)
                args = decorator.arguments
                table_name: object = snake_case(name)
                if args and args[0].type == "string":
                    table_name = _ts.literal(args[0])
                    args = args[1:]
                opts = options(args, {"name"}, location)
                table_name = opts.get("name", table_name)
                if not isinstance(table_name, str):
                    unresolved(location)
                    continue
                repo = ctx.repository_of(path).key
                if repo not in schemas:
                    schemas[repo] = Schema(reader=self.name, repository=repo)
                    ctx.schemas.append(schemas[repo])
                schema = schemas[repo]
                duplicate = table_name in schema.tables
                schema.create_table(
                    Table(
                        name=table_name,
                        columns=(),
                        constraints=(),
                        defined_at=location,
                        model_class=name,
                    )
                )
                if not duplicate:
                    entities[path, name] = Entity(
                        path, node, name, table_name, location, {}
                    )

        def resolve(path: str, symbol: str) -> tuple[str, str]:
            target_path, target_symbol = _ts.relative_import(
                roots[path], symbol, path, paths
            ) or (path, symbol)
            if target_symbol == "default":
                for declaration in _ts.declarations(
                    roots[target_path], "class_declaration"
                ):
                    parent = declaration.parent
                    name_node = declaration.child_by_field_name("name")
                    if (
                        parent is not None
                        and name_node is not None
                        and any(c.type == "default" for c in parent.children)
                    ):
                        return target_path, _ts.text(name_node)
            return target_path, target_symbol

        def enum(path: str, node: Node) -> tuple[str, ...]:
            if node.type == "array":
                values = _ts.literal(node)
                if not isinstance(values, list) or not all(
                    isinstance(v, (str, int, float)) and not isinstance(v, bool)
                    for v in values
                ):
                    raise _ts.NonLiteral
                return tuple(str(v) for v in values)
            if node.type != "identifier":
                raise _ts.NonLiteral
            target_path, symbol = resolve(path, _ts.text(node))
            for declaration in _ts.declarations(roots[target_path], "enum_declaration"):
                name = declaration.child_by_field_name("name")
                if name is not None and _ts.text(name) == symbol:
                    return _ts.enum_values(declaration)
            raise _ts.NonLiteral

        column_decorators = {
            "Column",
            "PrimaryColumn",
            "PrimaryGeneratedColumn",
            "CreateDateColumn",
            "UpdateDateColumn",
            "DeleteDateColumn",
            "VersionColumn",
        }
        relations: list[Relation] = []
        # Insert both scalar and join columns in property order; resolve FKs later.
        for entity in entities.values():
            schema = schemas[ctx.repository_of(entity.path).key]
            body = entity.node.child_by_field_name("body")
            if body is None:
                continue
            primary: list[str] = []
            primary_spans: list[Span] = []
            explicit_columns: set[str] = set()

            def store_column(incoming: Column, *, explicit: bool) -> bool:
                existing = next(
                    (
                        c
                        for c in schema.tables[entity.table].columns
                        if c.name == incoming.name
                    ),
                    None,
                )
                if explicit and incoming.name in explicit_columns:
                    schema.add_column(entity.table, incoming)
                    return False
                if explicit:
                    explicit_columns.add(incoming.name)
                if existing is None:
                    schema.add_column(entity.table, incoming)
                else:
                    # change_column retains the first position and both citations.
                    if not explicit:
                        incoming = existing.model_copy(
                            update={"origin": incoming.origin}
                        )
                    schema.change_column(entity.table, incoming.name, incoming)
                return True

            for member in body.named_children:
                name_node = member.child_by_field_name("name")
                if member.type != "public_field_definition" or name_node is None:
                    continue
                location = span(entity.path, member)
                prop = _ts.text(name_node)
                decs = _ts.decorators(member)
                column = next((d for d in decs if d.name in column_decorators), None)
                relation_decorator = next(
                    (d for d in decs if d.name in {"ManyToOne", "OneToOne"}), None
                )
                join = next((d for d in decs if d.name == "JoinColumn"), None)
                if column is None and (
                    relation_decorator is None
                    or (relation_decorator.name == "OneToOne" and join is None)
                ):
                    continue
                if name_node.type == "computed_property_name":
                    try:
                        if len(name_node.named_children) != 1:
                            raise _ts.NonLiteral
                        key = _ts.literal(name_node.named_children[0])
                        if not isinstance(key, str):
                            raise _ts.NonLiteral
                        prop = key
                    except _ts.NonLiteral:
                        unresolved(location)
                        continue
                annotation = next(
                    (c for c in member.named_children if c.type == "type_annotation"),
                    None,
                )
                datatype: str | None = (
                    _ts.text(annotation).removeprefix(":").strip()
                    if annotation
                    else None
                )
                allowed: tuple[str, ...] = ()
                if column is not None:
                    args = column.arguments
                    literal_type = None
                    if args and args[0].type == "string":
                        if column.name != "PrimaryGeneratedColumn":
                            literal_type = _ts.literal(args[0])
                        args = args[1:]
                    opts = options(
                        args,
                        {"type", "length", "name", "nullable", "unique", "enum"},
                        location,
                    )
                    explicit_type = opts.get("type", literal_type)
                    if isinstance(explicit_type, str):
                        datatype = explicit_type
                    column_name = opts.get("name", prop)
                    mandatory = (
                        None
                        if opts.get("nullable") is _UNKNOWN
                        else opts.get("nullable") is not True
                    )
                    enum_node = opts.get("enum")
                    if enum_node is not None:
                        try:
                            if not isinstance(enum_node, Node):
                                raise _ts.NonLiteral
                            allowed = enum(entity.path, enum_node)
                        except _ts.NonLiteral:
                            unresolved(location)
                else:
                    assert relation_decorator is not None
                    relation_args = tuple(
                        a
                        for a in relation_decorator.arguments[1:]
                        if a.type != "arrow_function"
                    )
                    opts = options(relation_args, {"nullable"}, location)
                    composite = bool(
                        join and join.arguments and join.arguments[0].type == "array"
                    )
                    entries = (
                        tuple(join.arguments[0].named_children)
                        if composite and join
                        else ()
                    )
                    if composite:
                        entries = tuple(e for e in entries if e.type != "comment")
                        if not entries or any(e.type != "object" for e in entries):
                            schema.mark_uncertain(entity.table, location)
                            continue
                        join_options = [
                            options(
                                (entry,), {"name", "referencedColumnName"}, location
                            )
                            for entry in entries
                        ]
                    else:
                        join_options = [
                            options(
                                join.arguments,
                                {"name", "referencedColumnName"},
                                location,
                            )
                            if join
                            else {}
                        ]
                    names = tuple(
                        o.get("name", None if composite else prop + "Id")
                        for o in join_options
                    )
                    if any(n is _UNKNOWN for n in names):
                        continue  # options already reported the non-literal name.
                    if not all(isinstance(n, str) for n in names) or len(
                        set(names)
                    ) != len(names):
                        schema.mark_uncertain(entity.table, location)
                        continue
                    join_names = tuple(n for n in names if isinstance(n, str))
                    mandatory = (
                        None
                        if opts.get("nullable") is _UNKNOWN
                        else opts.get("nullable") is False
                    )
                    for join_name in join_names:
                        store_column(
                            Column(
                                name=join_name,
                                datatype=None,
                                mandatory=mandatory,
                                origin=(location,),
                                defined_at=location,
                            ),
                            explicit=False,
                        )
                    if len(join_names) == 1:
                        entity.properties[prop] = join_names[0]
                    relations.append(
                        Relation(
                            entity,
                            join_names,
                            relation_decorator.arguments[0]
                            if relation_decorator.arguments
                            else None,
                            tuple(o.get("referencedColumnName") for o in join_options),
                            composite,
                            location,
                        )
                    )
                    continue
                if not isinstance(column_name, str):
                    unresolved(location)
                    continue
                if not store_column(
                    Column(
                        name=column_name,
                        datatype=datatype,
                        mandatory=mandatory,
                        origin=(location,),
                        defined_at=location,
                    ),
                    explicit=True,
                ):
                    continue
                entity.properties[prop] = column_name
                if column is not None and column.name in {
                    "PrimaryColumn",
                    "PrimaryGeneratedColumn",
                }:
                    primary.append(column_name)
                    primary_spans.append(location)
                if opts.get("unique") is True:
                    schema.add_constraint(
                        entity.table,
                        Constraint(
                            kind="unique", columns=(column_name,), spans=(location,)
                        ),
                    )
                if allowed:
                    schema.add_constraint(
                        entity.table,
                        Constraint(
                            kind="value",
                            columns=(column_name,),
                            allowed_values=allowed,
                            spans=(location,),
                        ),
                    )
            if primary:
                schema.add_constraint(
                    entity.table,
                    Constraint(
                        kind="primary",
                        columns=tuple(primary),
                        spans=tuple(primary_spans),
                    ),
                )

        for relation in relations:
            entity = relation.entity
            schema = schemas[ctx.repository_of(entity.path).key]
            expression = relation.target
            if expression is not None and expression.type == "arrow_function":
                expression = expression.child_by_field_name("body")
            target = None
            if expression is not None and expression.type == "string":
                symbol = _ts.literal(expression)
                matches = [
                    e
                    for e in entities.values()
                    if e.name == symbol
                    and ctx.repository_of(e.path).key == schema.repository
                ]
                if len(matches) == 1:
                    target = matches[0]
            elif expression is not None and expression.type == "identifier":
                symbol = _ts.text(expression)
                target = entities.get(resolve(entity.path, symbol))
            else:
                unresolved(relation.span)
                continue
            if (
                target is None
                or ctx.repository_of(target.path).key != schema.repository
            ):
                unresolved(relation.span, "model_table_unknown", str(symbol))
                continue
            refs = relation.referenced_columns
            if any(ref is _UNKNOWN for ref in refs):
                continue
            target_table = schema.tables[target.table]
            target_primary = next(
                (c.columns for c in target_table.constraints if c.kind == "primary"), ()
            )
            referenced: list[str] = []
            for index, ref in enumerate(refs):
                if ref is None and index < len(target_primary):
                    referenced.append(target_primary[index])
                elif isinstance(ref, str) and ref in target.properties:
                    referenced.append(target.properties[ref])
                else:
                    break
            valid = len(referenced) == len(relation.columns) and len(
                set(referenced)
            ) == len(referenced)
            if any(ref is None for ref in refs) and len(target_primary) != len(
                relation.columns
            ):
                valid = False
            if not valid:
                if relation.composite:
                    schema.mark_uncertain(entity.table, relation.span)
                else:
                    unresolved(relation.span, "model_table_unknown", target.name)
                continue
            schema.add_constraint(
                entity.table,
                Constraint(
                    kind="foreign",
                    columns=relation.columns,
                    ref_table=target.table,
                    ref_columns=tuple(referenced),
                    spans=(relation.span,),
                ),
            )

        for entity in entities.values():
            schema = schemas[ctx.repository_of(entity.path).key]
            for decorator in _ts.decorators(entity.node):
                if decorator.name not in {"Unique", "Index"}:
                    continue
                location = span(entity.path, decorator.node)
                constraint_args = list(decorator.arguments)
                constraint_name = None
                if constraint_args and constraint_args[0].type == "string":
                    value = _ts.literal(constraint_args.pop(0))
                    if isinstance(value, str):
                        constraint_name = value
                if decorator.name == "Index":
                    index_opts = options(
                        tuple(constraint_args[1:]), {"unique"}, location
                    )
                    if index_opts.get("unique") is not True:
                        continue
                # Unique options (e.g. deferrable) have no extracted semantics.
                try:
                    if not constraint_args:
                        raise _ts.NonLiteral
                    fields = _ts.literal(constraint_args[0])
                    if (
                        not isinstance(fields, list)
                        or not fields
                        or not all(
                            isinstance(f, str) and f in entity.properties
                            for f in fields
                        )
                    ):
                        raise _ts.NonLiteral
                    columns = tuple(entity.properties[f] for f in fields)
                except _ts.NonLiteral:
                    unresolved(location)
                    continue
                schema.add_constraint(
                    entity.table,
                    Constraint(
                        kind="unique",
                        name=constraint_name,
                        columns=columns,
                        spans=(location,),
                    ),
                )
