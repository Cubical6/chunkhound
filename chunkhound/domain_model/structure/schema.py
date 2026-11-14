"""Reader-local, repository-local storage schema with atomic replay operations."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _SchemaModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Span(_SchemaModel):
    path: str
    start_line: int
    end_line: int
    reader: str


class Column(_SchemaModel):
    name: str
    datatype: str | None
    mandatory: bool | None
    origin: tuple[Span, ...]
    defined_at: Span


class Constraint(_SchemaModel):
    kind: Literal["primary", "unique", "foreign", "value", "check"]
    name: str | None = None
    columns: tuple[str, ...]
    ref_table: str | None = None
    ref_columns: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()
    statement: str | None = None
    spans: tuple[Span, ...]


class Table(_SchemaModel):
    name: str
    columns: tuple[Column, ...]
    constraints: tuple[Constraint, ...]
    defined_at: Span
    model_class: str | None = None
    uncertain: tuple[tuple[str, Span], ...] = ()
    # Table renames, like column changes, retain their source history.
    origin: tuple[Span, ...] = ()


class TableClaims(_SchemaModel):
    """Lower-source assertions, never a request to create storage elements."""

    table: str
    span: Span
    model_class: str | None = None
    columns: tuple[Column, ...] = ()
    constraints: tuple[Constraint, ...] = ()


@dataclass
class Schema:
    reader: str
    repository: str
    tables: dict[str, Table] = field(default_factory=dict)
    orphans: list[tuple[str, str, Span]] = field(default_factory=list)
    claims: list[TableClaims] = field(default_factory=list)

    def mark_uncertain(
        self, name: str, span: Span, reason: str = "unparsed_statement"
    ) -> None:
        table = self.tables.get(name)
        if table is None:
            self.orphans.append((name, reason, span))
            return
        self.tables[name] = table.model_copy(
            update={"uncertain": (*table.uncertain, (reason, span))}
        )

    def create_table(self, table: Table, *, if_not_exists: bool = False) -> None:
        if table.name in self.tables:
            if not if_not_exists:
                self.mark_uncertain(table.name, table.defined_at, "table_created_twice")
            return
        self.tables[table.name] = table

    def drop_table(self, name: str, span: Span) -> None:
        if name not in self.tables:
            self.mark_uncertain(name, span)
            return
        del self.tables[name]

    def rename_table(self, name: str, new_name: str, span: Span) -> None:
        if name not in self.tables or new_name in self.tables:
            self.mark_uncertain(name, span)
            return
        table = self.tables[name]
        renamed = table.model_copy(
            update={
                "name": new_name,
                "origin": (*(table.origin or (table.defined_at,)), span),
            }
        )
        self.tables = {
            new_name if key == name else key: renamed if key == name else value
            for key, value in self.tables.items()
        }
        for key, value in self.tables.items():
            self.tables[key] = value.model_copy(
                update={
                    "constraints": tuple(
                        c.model_copy(update={"ref_table": new_name})
                        if c.ref_table == name
                        else c
                        for c in value.constraints
                    )
                }
            )

    def add_column(self, name: str, column: Column) -> None:
        table = self.tables.get(name)
        if table is None or any(c.name == column.name for c in table.columns):
            self.mark_uncertain(name, column.defined_at)
            return
        self.tables[name] = table.model_copy(
            update={"columns": (*table.columns, column)}
        )

    def drop_column(self, name: str, column: str, span: Span) -> None:
        table = self.tables.get(name)
        if table is None or not any(c.name == column for c in table.columns):
            self.mark_uncertain(name, span)
            return
        self.tables[name] = table.model_copy(
            update={
                "columns": tuple(c for c in table.columns if c.name != column),
                "constraints": tuple(
                    c for c in table.constraints if column not in c.columns
                ),
            }
        )

    def change_column(self, name: str, old_name: str, column: Column) -> None:
        table = self.tables.get(name)
        if (
            table is None
            or not any(c.name == old_name for c in table.columns)
            or any(c.name == column.name and c.name != old_name for c in table.columns)
        ):
            self.mark_uncertain(name, column.defined_at)
            return
        old = next(c for c in table.columns if c.name == old_name)
        column = column.model_copy(update={"origin": (*old.origin, *column.origin)})
        self.tables[name] = table.model_copy(
            update={
                "columns": tuple(
                    column if c.name == old_name else c for c in table.columns
                ),
                "constraints": tuple(
                    c.model_copy(
                        update={
                            "columns": tuple(
                                column.name if n == old_name else n for n in c.columns
                            )
                        }
                    )
                    for c in table.constraints
                ),
            }
        )
        for key, value in self.tables.items():
            self.tables[key] = value.model_copy(
                update={
                    "constraints": tuple(
                        c.model_copy(
                            update={
                                "ref_columns": tuple(
                                    column.name if n == old_name else n
                                    for n in c.ref_columns
                                )
                            }
                        )
                        if c.ref_table == name
                        else c
                        for c in value.constraints
                    )
                }
            )

    def rename_column(
        self, name: str, old_name: str, new_name: str, span: Span
    ) -> None:
        table = self.tables.get(name)
        column = (
            next((c for c in table.columns if c.name == old_name), None)
            if table
            else None
        )
        if column is None:
            self.mark_uncertain(name, span)
            return
        self.change_column(
            name,
            old_name,
            column.model_copy(
                update={
                    "name": new_name,
                    "origin": (span,),
                    "defined_at": span,
                }
            ),
        )

    def add_constraint(self, name: str, constraint: Constraint) -> None:
        table = self.tables.get(name)
        if (
            table is None
            or not set(constraint.columns).issubset(c.name for c in table.columns)
            or any(
                (constraint.name is not None and c.name == constraint.name)
                or (constraint.kind == c.kind == "primary")
                for c in table.constraints
            )
        ):
            self.mark_uncertain(name, constraint.spans[0])
            return
        self.tables[name] = table.model_copy(
            update={"constraints": (*table.constraints, constraint)}
        )

    def drop_constraint(
        self,
        name: str,
        constraint_name: str | None,
        span: Span,
        *,
        kind: str | None = None,
    ) -> None:
        def matches(constraint: Constraint) -> bool:
            return (
                constraint.kind == kind
                if kind is not None
                else constraint.name == constraint_name
            )

        table = self.tables.get(name)
        if table is None or not any(matches(c) for c in table.constraints):
            self.mark_uncertain(name, span)
            return
        self.tables[name] = table.model_copy(
            update={
                "constraints": tuple(c for c in table.constraints if not matches(c))
            }
        )
