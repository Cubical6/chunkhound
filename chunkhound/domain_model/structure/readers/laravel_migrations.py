"""Literal Blueprint replay, preceded by Laravel's SQL schema dump."""

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.contract import Finding
from chunkhound.domain_model.structure.ordering import natural_order
from chunkhound.domain_model.structure.readers._php import (
    Call,
    literal_list,
    literal_text,
    method_chain,
    regular_plural,
    span,
    static_call,
    text,
    walk,
)
from chunkhound.domain_model.structure.readers.sql import (
    SQLReader,
    dumped_migrations,
    is_laravel_dump,
    sql_statements,
)
from chunkhound.domain_model.structure.schema import (
    Column,
    Constraint,
    Schema,
    Span,
    Table,
)

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext
    from chunkhound.domain_model.structure.readers.sql import _Statement

_COLUMN_METHODS = set(
    """
    bigInteger binary boolean char date dateTime dateTimeTz decimal double float
    foreignId foreignUuid foreignUlid geometry geometryCollection integer ipAddress
    json jsonb lineString longText macAddress mediumInteger mediumText multiLineString
    multiPoint multiPolygon point polygon smallInteger string text time timeTz
    timestamp timestampTz tinyInteger tinyText unsignedBigInteger unsignedInteger
    unsignedMediumInteger unsignedSmallInteger unsignedTinyInteger uuid ulid year
    enum set id increments bigIncrements mediumIncrements smallIncrements tinyIncrements
""".split()
)
_EXPANSIONS = {
    "timestamps",
    "timestampsTz",
    "nullableTimestamps",
    "softDeletes",
    "softDeletesTz",
    "rememberToken",
    "morphs",
    "nullableMorphs",
    "uuidMorphs",
    "nullableUuidMorphs",
    "ulidMorphs",
    "nullableUlidMorphs",
}
_IGNORED = {"default", "index", "after", "comment", "useCurrent"}
_MODIFIERS = _IGNORED | {
    "nullable",
    "unique",
    "primary",
    "unsigned",
    "change",
    "constrained",
    "references",
    "on",
    "onDelete",
    "onUpdate",
    "cascadeOnDelete",
    "cascadeOnUpdate",
    "restrictOnDelete",
    "restrictOnUpdate",
    "nullOnDelete",
    "noActionOnDelete",
    "noActionOnUpdate",
}
_OPERATIONS = {
    "primary",
    "unique",
    "foreign",
    "dropColumn",
    "renameColumn",
    "dropUnique",
    "dropForeign",
    "dropPrimary",
}
_TABLE_CALLS = {"create", "table", "rename", "drop", "dropIfExists"}
_SCHEMA_IGNORED = {
    "hasColumn",
    "hasTable",
    "hasColumns",
    "connection",
    "disableForeignKeyConstraints",
    "enableForeignKeyConstraints",
    "withoutForeignKeyConstraints",
    "defaultStringLength",
    "defaultMorphKeyType",
    "useNativeSchemaOperationsIfPossible",
    "blueprintResolver",
}
_CONDITIONS = {
    "if_statement",
    "else_clause",
    "else_if_clause",
    "foreach_statement",
    "for_statement",
    "while_statement",
    "do_statement",
    "switch_statement",
    "switch_block",
    "match_expression",
    "conditional_expression",
    "binary_expression",
    "try_statement",
    "catch_clause",
}


class _NonLiteralError(ValueError):
    pass


def _string(args: tuple[Node, ...], index: int = 0) -> str:
    value = literal_text(args[index]) if len(args) > index else None
    if value is None:
        raise _NonLiteralError
    return value


def _columns(args: tuple[Node, ...]) -> tuple[str, ...]:
    if not args:
        raise _NonLiteralError
    values = literal_list(args[0])
    return values if values is not None else (_string(args),)


def _enabled(modifiers: dict[str, Call], name: str) -> bool:
    call = modifiers.get(name)
    if call is None:
        return False
    if not call.args:
        return True
    value = text(call.args[0]).lower()
    if value not in {"true", "false"}:
        raise _NonLiteralError
    return value == "true"


def _conditional(node: Node, boundary: Node) -> bool:
    if node == boundary:
        return False
    parent = node.parent
    while parent is not None and parent != boundary:
        if parent.type in _CONDITIONS:
            return True
        parent = parent.parent
    return False


class LaravelMigrationsReader:
    name = "laravel_migrations"
    # A character class preserves the recursive glob: scope collection otherwise
    # mistakes **/database for a root-only directory anchor and prunes monorepos.
    patterns: tuple[str, ...] = (
        "**/[d]atabase/migrations/*.php",
        "**/[d]atabase/schema/*.sql",
    )

    def read(self, ctx: "ReadContext") -> None:
        schemas: dict[str, Schema] = {}
        played: dict[str, set[str]] = {}
        dumps: list[tuple[Schema, _Statement]] = []
        migrations: list[tuple[str, Schema]] = []
        for path in sorted(ctx.paths, key=natural_order):
            repository = ctx.repository_of(path).key
            if repository not in schemas:
                schemas[repository] = Schema(reader=self.name, repository=repository)
                ctx.schemas.append(schemas[repository])
                played[repository] = set()
            schema = schemas[repository]
            if is_laravel_dump(path):
                source = ctx.read(path)
                if source is not None:
                    statements = sql_statements(
                        path, "\n".join(source.lines).encode("utf-8")
                    )
                    dumps.extend((schema, statement) for statement in statements)
                    played[repository].update(dumped_migrations(statements))
            else:
                migrations.append((path, schema))
        SQLReader().replay(dumps)
        parser = get_parser("php")
        for path, schema in migrations:
            if PurePosixPath(path).stem in played[schema.repository]:
                continue
            source = ctx.read(path)
            if source is None:
                continue
            tree = parser.parse("\n".join(source.lines).encode("utf-8"))
            replay = _Migration(ctx, schema, path)
            for method in walk(tree.root_node):
                if (
                    method.type == "method_declaration"
                    and text(method.child_by_field_name("name")).lower() == "up"
                ):
                    replay.up(method)


class _Migration:
    def __init__(self, ctx: "ReadContext", schema: Schema, path: str) -> None:
        self.ctx = ctx
        self.schema = schema
        self.path = path

    def span(self, node: Node) -> Span:
        return span(node, self.path, LaravelMigrationsReader.name)

    def unresolved(self, node: Node) -> None:
        source = self.span(node)
        repository = self.ctx.repository_of(self.path)
        self.ctx.findings.append(
            Finding(
                kind="unresolved",
                subject=None,
                reason="non_literal_argument",
                detail=None,
                citations=(
                    Citation(
                        repository=repository.key,
                        path=self.path,
                        start_line=source.start_line,
                        end_line=source.end_line,
                        commit=repository.commit,
                    ),
                ),
            )
        )

    def up(self, method: Node) -> None:
        touched: list[str] = []
        raw: list[Node] = []
        for node in walk(method):
            call = static_call(node)
            if node.type == "member_call_expression":
                receiver, chain = method_chain(node)
                root = static_call(receiver)
                if (
                    root is not None
                    and root[1].name == "connection"
                    and len(chain) == 1
                ):
                    call = (root[0], chain[0])
            if call is None:
                continue
            scope, operation = call
            scope = scope.rsplit("\\", 1)[-1]
            if scope == "DB" and operation.name in {"statement", "unprepared", "raw"}:
                raw.append(node)
            if scope != "Schema":
                continue
            if operation.name in _SCHEMA_IGNORED:
                continue
            # Only known table operations require a table-name argument. Unknown
            # global builder calls must not become non-literal table findings.
            if operation.name not in _TABLE_CALLS and (
                not operation.args or literal_text(operation.args[0]) is None
            ):
                continue
            try:
                name = _string(operation.args)
                touched.append(name)
                if _conditional(node, method):
                    self.schema.mark_uncertain(
                        name, self.span(node), "conditional_schema"
                    )
                    continue
                current = self.schema_call(name, operation)
                if current != name:
                    touched.append(current)
            except _NonLiteralError:
                self.unresolved(node)
        for node in raw:
            if touched:
                for name in dict.fromkeys(touched):
                    self.schema.mark_uncertain(name, self.span(node), "raw_sql")
            else:
                repository = self.ctx.repository_of(self.path)
                source = self.span(node)
                self.ctx.findings.append(
                    Finding(
                        kind="uncertain",
                        subject=None,
                        reason="raw_sql",
                        detail=None,
                        citations=(
                            Citation(
                                repository=repository.key,
                                path=self.path,
                                start_line=source.start_line,
                                end_line=source.end_line,
                                commit=repository.commit,
                            ),
                        ),
                    )
                )

    def schema_call(self, name: str, call: Call) -> str:
        source = self.span(call.node)
        if call.name in {"create", "table"}:
            callback = call.args[1] if len(call.args) > 1 else None
            if callback is None or callback.type not in {
                "anonymous_function",
                "arrow_function",
            }:
                self.schema.mark_uncertain(name, source, "unknown_schema_call")
                return name
            parameters = callback.child_by_field_name("parameters")
            parameter = (
                parameters.named_children[0]
                if parameters and parameters.named_children
                else None
            )
            variable = text(parameter.child_by_field_name("name")) if parameter else ""
            body = callback.child_by_field_name("body")
            if not variable or body is None:
                self.schema.mark_uncertain(name, source, "unknown_schema_call")
                return name
            if call.name == "create":
                if name in self.schema.tables:
                    self.schema.mark_uncertain(name, source, "table_created_twice")
                    return name
                self.schema.create_table(
                    Table(name=name, columns=(), constraints=(), defined_at=source)
                )
            for node in walk(body):
                if node.type != "member_call_expression" or (
                    node.parent is not None
                    and node.parent.type == "member_call_expression"
                ):
                    continue
                receiver, chain = method_chain(node)
                if text(receiver) != variable:
                    continue
                if _conditional(node, body):
                    self.schema.mark_uncertain(
                        name, self.span(node), "conditional_schema"
                    )
                    continue
                try:
                    self.blueprint(name, chain, self.span(node))
                except _NonLiteralError:
                    self.unresolved(node)
        elif call.name == "rename":
            new_name = _string(call.args, 1)
            self.schema.rename_table(name, new_name, source)
            return new_name
        elif call.name in {"drop", "dropIfExists"}:
            if call.name == "drop" or name in self.schema.tables:
                self.schema.drop_table(name, source)
        else:
            self.schema.mark_uncertain(name, source, "unknown_schema_call")
        return name

    def constraint(
        self,
        table: str,
        kind: Literal["primary", "unique", "foreign", "value"],
        columns: tuple[str, ...],
        source: Span,
        *,
        name: str | None = None,
        ref_table: str | None = None,
        ref_columns: tuple[str, ...] = (),
        values: tuple[str, ...] = (),
    ) -> None:
        self.schema.add_constraint(
            table,
            Constraint(
                kind=kind,
                name=name or f"{table}_{'_'.join(columns)}_{kind}",
                columns=columns,
                ref_table=ref_table,
                ref_columns=ref_columns,
                allowed_values=values,
                spans=(source,),
            ),
        )

    def blueprint(self, table: str, chain: tuple[Call, ...], source: Span) -> None:
        first, *modifiers = chain
        if (
            first.name not in _COLUMN_METHODS | _EXPANSIONS | _OPERATIONS | _IGNORED
            or any(c.name not in _MODIFIERS for c in modifiers)
        ):
            self.schema.mark_uncertain(table, source, "unknown_schema_call")
            return
        if first.name in _IGNORED:
            return
        mods = {c.name: c for c in modifiers}
        if first.name in _OPERATIONS:
            self.operation(table, first, mods, source)
            return
        if first.name in _EXPANSIONS:
            self.expansion(table, first, mods, source)
            return
        name = (
            _string(first.args) if first.args else "id" if first.name == "id" else None
        )
        if name is None:
            raise _NonLiteralError
        extra = first.args[1:]
        values: tuple[str, ...] = ()
        if first.name in {"enum", "set"}:
            values_or_none = literal_list(extra[0]) if extra else None
            if values_or_none is None:
                raise _NonLiteralError
            values = values_or_none
            extra = ()
        datatype = first.name + self.type_arguments(extra)
        if _enabled(mods, "unsigned"):
            datatype += " unsigned"
        mandatory = not _enabled(mods, "nullable")
        primary = (
            first.name == "id"
            or first.name.endswith("Increments")
            or first.name == "increments"
        )
        self.column(
            table,
            name,
            datatype,
            mandatory or primary or "primary" in mods,
            source,
            change="change" in mods,
        )
        if primary or "primary" in mods:
            self.constraint(
                table,
                "primary",
                (name,),
                source,
                name=_string(mods["primary"].args)
                if "primary" in mods and mods["primary"].args
                else None,
            )
        if "unique" in mods:
            self.constraint(
                table,
                "unique",
                (name,),
                source,
                name=_string(mods["unique"].args) if mods["unique"].args else None,
            )
        if first.name in {"enum", "set"}:
            self.constraint(table, "value", (name,), source, values=values)
        if {"constrained", "references", "on"} & mods.keys():
            self.foreign_key(table, (name,), mods, source)

    def foreign_key(
        self,
        table: str,
        columns: tuple[str, ...],
        mods: dict[str, Call],
        source: Span,
        *,
        name: str | None = None,
    ) -> None:
        constrained = mods.get("constrained")
        if "on" in mods:
            target = _string(mods["on"].args)
        elif constrained is not None:
            target = (
                _string(constrained.args)
                if constrained.args
                else regular_plural(columns[0].removesuffix("_id"))
            )
        else:
            self.schema.mark_uncertain(table, source, "unknown_schema_call")
            return
        if "references" in mods:
            references = _columns(mods["references"].args)
        elif constrained is not None:
            references = (
                _string(constrained.args, 1) if len(constrained.args) > 1 else "id",
            )
        else:
            # Empty referenced columns let translation resolve the actual PK,
            # including non-id and composite primary keys, without guessing.
            references = ()
        if constrained is not None and len(constrained.args) > 2:
            name = _string(constrained.args, 2)
        self.constraint(
            table,
            "foreign",
            columns,
            source,
            name=name,
            ref_table=target,
            ref_columns=references,
        )

    @staticmethod
    def type_arguments(args: tuple[Node, ...]) -> str:
        if not args:
            return ""
        values = []
        for arg in args:
            raw = text(arg)
            if re.fullmatch(r"[+-]?\d+(?:\.\d+)?|true|false|null", raw):
                values.append(raw)
        return "(" + ",".join(values) + ")" if values else ""

    def column(
        self,
        table: str,
        name: str,
        datatype: str,
        mandatory: bool,
        source: Span,
        *,
        change: bool = False,
    ) -> None:
        column = Column(
            name=name,
            datatype=datatype,
            mandatory=mandatory,
            origin=(source,),
            defined_at=source,
        )
        if change:
            self.schema.change_column(table, name, column)
        else:
            self.schema.add_column(table, column)

    def operation(
        self, table: str, call: Call, mods: dict[str, Call], source: Span
    ) -> None:
        if call.name == "dropPrimary":
            if call.args:
                columns = literal_list(call.args[0])
                index_name = (
                    f"{table}_{'_'.join(columns)}_primary"
                    if columns is not None
                    else _string(call.args)
                )
                self.schema.drop_constraint(table, index_name, source)
            else:
                self.schema.drop_constraint(table, None, source, kind="primary")
        elif call.name == "renameColumn":
            self.schema.rename_column(
                table, _string(call.args), _string(call.args, 1), source
            )
        elif call.name == "dropColumn":
            names = (
                _columns(call.args)
                if len(call.args) == 1
                else tuple(_string((a,)) for a in call.args)
            )
            for name in names:
                self.schema.drop_column(table, name, source)
        elif call.name in {"dropUnique", "dropForeign"}:
            kind = "unique" if call.name == "dropUnique" else "foreign"
            drop_columns = literal_list(call.args[0]) if call.args else None
            drop_name = (
                f"{table}_{'_'.join(drop_columns)}_{kind}"
                if drop_columns is not None
                else _string(call.args)
            )
            self.schema.drop_constraint(table, drop_name, source)
        else:
            columns = _columns(call.args)
            constraint_name = _string(call.args, 1) if len(call.args) > 1 else None
            if call.name == "foreign":
                self.foreign_key(table, columns, mods, source, name=constraint_name)
            else:
                constraint_kind: Literal["primary", "unique"] = (
                    "primary" if call.name == "primary" else "unique"
                )
                self.constraint(
                    table, constraint_kind, columns, source, name=constraint_name
                )

    def expansion(
        self, table: str, call: Call, mods: dict[str, Call], source: Span
    ) -> None:
        method = call.name
        nullable = method.startswith("nullable") or _enabled(mods, "nullable")
        if method in {"timestamps", "timestampsTz", "nullableTimestamps"}:
            datatype = (
                "timestampTz" if method == "timestampsTz" else "timestamp"
            ) + self.type_arguments(call.args)
            for name in ("created_at", "updated_at"):
                self.column(table, name, datatype, False, source)
        elif method in {"softDeletes", "softDeletesTz", "rememberToken"}:
            name = (
                _string(call.args)
                if call.args
                else "remember_token"
                if method == "rememberToken"
                else "deleted_at"
            )
            datatype = (
                "string(100)"
                if method == "rememberToken"
                else ("timestampTz" if method == "softDeletesTz" else "timestamp")
                + self.type_arguments(call.args[1:])
            )
            self.column(table, name, datatype, False, source)
        else:
            name = _string(call.args)
            datatype = (
                "uuid"
                if "Uuid" in method or method == "uuidMorphs"
                else "ulid"
                if "Ulid" in method or method == "ulidMorphs"
                else "unsignedBigInteger"
            )
            self.column(table, name + "_type", "string", not nullable, source)
            self.column(table, name + "_id", datatype, not nullable, source)
