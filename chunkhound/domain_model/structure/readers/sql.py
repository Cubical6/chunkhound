"""SQL DDL replay with tree-sitter boundaries and quote-aware definitions."""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from tree_sitter_language_pack import get_parser

from chunkhound.domain_model.structure.ordering import natural_order
from chunkhound.domain_model.structure.schema import (
    Column,
    Constraint,
    Schema,
    Span,
    Table,
)

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext

# Tokens retain offsets so both CHECK text and citations come from the source.
_TOKEN = re.compile(
    r"\s+|--[^\n]*|\#[^\n]*|/\*[\s\S]*?\*/|"
    r"'(?:''|\\.|[^'\\])*'|\"(?:\"\"|\\.|[^\"\\])*\"|"
    r"`(?:``|[^`])*`|[\w$]+|[^\s]",
    re.UNICODE,
)
_MODIFIERS = {
    "NOT",
    "NULL",
    "PRIMARY",
    "UNIQUE",
    "REFERENCES",
    "CHECK",
    "CONSTRAINT",
    "DEFAULT",
    "COMMENT",
    "COLLATE",
    "CHARSET",
    "AUTO_INCREMENT",
    "GENERATED",
    "IDENTITY",
}


class _UnparsedError(ValueError):
    pass


@dataclass(frozen=True)
class _Token:
    text: str
    start: int
    end: int

    @property
    def upper(self) -> str:
        return self.text.upper()


def _tokens(text: str) -> list[_Token]:
    return [
        _Token(m.group(), m.start(), m.end())
        for m in _TOKEN.finditer(text)
        if not m.group().isspace() and not m.group().startswith(("--", "#", "/*"))
    ]


def _identifier(token: _Token) -> str:
    text = token.text
    if text.startswith(('"', "`")) and text[-1] == text[0]:
        return text[1:-1].replace(text[0] * 2, text[0])
    if not re.fullmatch(r"[\w$]+", text):
        raise _UnparsedError("Expected identifier")
    return text


@dataclass
class _Cursor:
    tokens: list[_Token]
    index: int = 0

    def at(self, word: str) -> bool:
        return self.index < len(self.tokens) and self.tokens[self.index].upper == word

    def take(self) -> _Token:
        if self.index >= len(self.tokens):
            raise _UnparsedError("Unexpected end")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def accept(self, word: str) -> bool:
        if not self.at(word):
            return False
        self.index += 1
        return True

    def expect(self, word: str) -> None:
        if not self.accept(word):
            raise _UnparsedError(f"Expected {word}")

    def identifier(self) -> str:
        name = _identifier(self.take())
        while self.accept("."):
            name = _identifier(self.take())
        return name

    def group(self) -> list[_Token]:
        self.expect("(")
        start = self.index
        depth = 1
        while self.index < len(self.tokens):
            token = self.take()
            if token.text == "(":
                depth += 1
            elif token.text == ")":
                depth -= 1
                if depth == 0:
                    return self.tokens[start : self.index - 1]
        raise _UnparsedError("Unclosed parentheses")


def _parts(tokens: list[_Token]) -> list[list[_Token]]:
    parts: list[list[_Token]] = []
    start = depth = 0
    for i, token in enumerate(tokens):
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
        elif token.text == "," and depth == 0:
            parts.append(tokens[start:i])
            start = i + 1
    parts.append(tokens[start:])
    return parts


def _names(tokens: list[_Token]) -> tuple[str, ...]:
    names = []
    for part in _parts(tokens):
        cursor = _Cursor(part)
        names.append(cursor.identifier())
        if cursor.index != len(part):
            raise _UnparsedError("Non-column index expression")
    return tuple(names)


def _values(tokens: list[_Token]) -> tuple[str, ...]:
    values = []
    for part in _parts(tokens):
        text = "".join(t.text for t in part)
        if len(part) == 1 and text.startswith(("'", '"')):
            quote = text[0]
            values.append(
                text[1:-1]
                .replace(quote * 2, quote)
                .replace("\\" + quote, quote)
                .replace("\\\\", "\\")
            )
        elif re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
            values.append(text)
        else:
            raise _UnparsedError("Non-literal value")
    return tuple(values)


def _datatype(tokens: list[_Token]) -> str:
    # Normalize separators, not the contents of string literals in enum types.
    result = ""
    previous = ""
    for token in tokens:
        text = token.text if token.text.startswith(("'", '"')) else token.text.lower()
        separator = (
            ""
            if not result or text in {"(", ")", ",", "."} or previous in {"(", ",", "."}
            else " "
        )
        result += separator + text
        previous = text
    return result


@dataclass
class _Statement:
    path: str
    text: str
    line: int
    copy_rows: tuple[tuple[str, ...], ...] = ()

    def span(self, tokens: list[_Token] | None = None) -> Span:
        start = tokens[0].start if tokens else 0
        end = tokens[-1].end if tokens else len(self.text.rstrip())
        return Span(
            path=self.path,
            start_line=self.line + self.text[:start].count("\n"),
            end_line=self.line + self.text[:end].count("\n"),
            reader="sql",
        )


def _constraint(
    cursor: _Cursor,
    statement: _Statement,
    known_columns: tuple[str, ...],
    inline: str | None = None,
) -> Constraint:
    start = cursor.index
    name = cursor.identifier() if cursor.accept("CONSTRAINT") else None
    span: Span
    columns: tuple[str, ...] = (inline,) if inline else ()
    kind: Literal["primary", "unique", "foreign"]
    if cursor.accept("PRIMARY"):
        cursor.expect("KEY")
        kind = "primary"
    elif cursor.accept("UNIQUE"):
        kind = "unique"
        if not cursor.accept("KEY"):
            cursor.accept("INDEX")
        if not inline and not cursor.at("("):
            name = cursor.identifier()
    elif cursor.accept("FOREIGN"):
        cursor.expect("KEY")
        kind = "foreign"
        if not cursor.at("("):
            name = name or cursor.identifier()
    elif cursor.at("REFERENCES") and inline:
        kind = "foreign"
    elif cursor.accept("CHECK"):
        expression = cursor.group()
        span = statement.span(cursor.tokens[start : cursor.index])
        # Parenthesized expressions are equivalent for recognizing literal IN.
        simple = expression
        while simple and simple[0].text == "(":
            nested = _Cursor(simple)
            inner = nested.group()
            if nested.index != len(simple):
                break
            simple = inner
        check = _Cursor(simple)
        if len(simple) >= 3:
            try:
                column = check.identifier()
                if check.accept("IN"):
                    values = _values(check.group())
                    if check.index == len(simple) and column in known_columns:
                        return Constraint(
                            kind="value",
                            name=name,
                            columns=(column,),
                            allowed_values=values,
                            spans=(span,),
                        )
            except _UnparsedError:
                pass
        columns = tuple(
            dict.fromkeys(
                _identifier(t)
                for t in expression
                if not t.text.startswith("'")
                and (t.text.startswith(('"', "`")) or re.fullmatch(r"[\w$]+", t.text))
                and _identifier(t) in known_columns
            )
        )
        return Constraint(
            kind="check",
            name=name,
            columns=columns,
            statement=statement.text[
                cursor.tokens[start].start : cursor.tokens[cursor.index - 1].end
            ],
            spans=(span,),
        )
    else:
        raise _UnparsedError("Unknown constraint")
    if not inline:
        columns = _names(cursor.group())
    ref_table = None
    ref_columns: tuple[str, ...] = ()
    if kind == "foreign":
        cursor.expect("REFERENCES")
        ref_table = cursor.identifier()
        if cursor.at("("):
            ref_columns = _names(cursor.group())
        while cursor.index < len(cursor.tokens):
            if cursor.accept("MATCH"):
                if cursor.take().upper not in {"FULL", "PARTIAL", "SIMPLE"}:
                    raise _UnparsedError("Unknown foreign-key match")
            elif cursor.accept("ON"):
                if cursor.take().upper not in {"DELETE", "UPDATE"}:
                    raise _UnparsedError("Unknown foreign-key event")
                action = cursor.take().upper
                if action == "SET":
                    if cursor.take().upper not in {"NULL", "DEFAULT"}:
                        raise _UnparsedError("Unknown foreign-key action")
                elif action == "NO":
                    cursor.expect("ACTION")
                elif action not in {"RESTRICT", "CASCADE"}:
                    raise _UnparsedError("Unknown foreign-key action")
            else:
                break
    span = statement.span(cursor.tokens[start : cursor.index])
    return Constraint(
        kind=kind,
        name=name,
        columns=columns,
        ref_table=ref_table,
        ref_columns=ref_columns,
        spans=(span,),
    )


def is_laravel_dump(path: str) -> bool:
    """Schema dumps belong to the Laravel replay, not a second SQL schema."""
    return bool(re.search(r"(?:^|/)database/schema/[^/]+\.sql$", path))


def sql_statements(path: str, data: bytes) -> list[_Statement]:
    """Recover statement boundaries once for both standalone SQL and dumps."""
    statements: list[_Statement] = []
    masked = bytearray(data)
    consumed = 0
    # pg_dump COPY payloads are data, not SQL. Hide entire blocks from the
    # grammar while retaining byte offsets and line numbers for later DDL.
    for header in re.finditer(
        rb"(?im)^[ \t]*COPY[ \t]+[^\r\n]*\bFROM[ \t]+stdin[ \t]*;[ \t]*(?:\r?\n|$)",
        data,
    ):
        if header.start() < consumed:
            continue
        terminator = re.search(rb"(?m)^\\\.\r?(?:\n|$)", data[header.end() :])
        rows_end = header.end() + terminator.start() if terminator else len(data)
        consumed = header.end() + terminator.end() if terminator else len(data)
        rows = tuple(
            tuple(row.split("\t"))
            for row in data[header.end() : rows_end].decode("utf-8").splitlines()
        )
        statements.append(
            _Statement(
                path,
                header.group().decode("utf-8").strip().removesuffix(";"),
                data[: header.start()].count(b"\n") + 1,
                rows,
            )
        )
        masked[header.start() : consumed] = re.sub(
            rb"[^\r\n]", b" ", data[header.start() : consumed]
        )
    data = bytes(masked)
    tree = get_parser("sql").parse(data)
    # Grammar recovery may split CREATE into a statement and a sibling ERROR.
    # Reunite those fragments at the tree's top-level terminators.
    start: tuple[int, int] | None = None
    end = 0
    for node in (*tree.root_node.children, None):
        if node is None or node.type == ";":
            if start is not None:
                statements.append(
                    _Statement(path, data[start[0] : end].decode("utf-8"), start[1])
                )
            start = None
        elif node.type != "comment":
            if start is None:
                start = (node.start_byte, node.start_point.row + 1)
            end = node.end_byte
    return sorted(statements, key=lambda statement: statement.line)


def dumped_migrations(statements: list[_Statement]) -> set[str]:
    """Read only literal migration names from the dump's migration ledger."""
    names: set[str] = set()
    for statement in statements:
        cursor = _Cursor(_tokens(statement.text))
        try:
            if cursor.accept("COPY"):
                table = cursor.identifier()
                columns = _names(cursor.group())
                cursor.expect("FROM")
                cursor.expect("STDIN")
                if table == "migrations":
                    index = columns.index("migration")
                    for row in statement.copy_rows:
                        if index < len(row) and row[index] != r"\N":
                            names.add(
                                re.sub(
                                    r"\\(.)",
                                    lambda m: {"t": "\t", "n": "\n", "r": "\r"}.get(
                                        m[1], m[1]
                                    ),
                                    row[index],
                                )
                            )
                continue
            if not cursor.accept("INSERT"):
                continue
            cursor.expect("INTO")
            if cursor.identifier() != "migrations":
                continue
            columns = _names(cursor.group()) if cursor.at("(") else ()
            index = columns.index("migration") if columns else 1
            cursor.expect("VALUES")
            while cursor.at("("):
                values = _parts(cursor.group())
                value = values[index]
                if len(value) == 1 and value[0].text.startswith(("'", '"')):
                    names.add(_values(value)[0])
                if not cursor.accept(","):
                    break
        except (_UnparsedError, ValueError, IndexError):
            continue
    return names


class SQLReader:
    name = "sql"
    patterns: tuple[str, ...] = ("**/*.sql",)

    def read(self, ctx: "ReadContext") -> None:
        statements: list[tuple[Schema, _Statement]] = []
        schemas: dict[str, Schema] = {}
        for path in sorted(ctx.paths, key=natural_order):
            if is_laravel_dump(path) or re.match(r"U\d", path.rsplit("/", 1)[-1]):
                continue
            source = ctx.read(path)
            if source is None:
                continue
            repository = ctx.repository_of(path).key
            if repository not in schemas:
                schemas[repository] = Schema(reader=self.name, repository=repository)
                ctx.schemas.append(schemas[repository])
            data = "\n".join(source.lines).encode("utf-8")
            statements.extend(
                (schemas[repository], statement)
                for statement in sql_statements(path, data)
            )
        self.replay(statements)

    def replay(self, statements: list[tuple[Schema, _Statement]]) -> None:
        """Apply DDL to the supplied schemas, including Laravel dump schemas."""
        enums: dict[tuple[str, str], tuple[tuple[str, ...], Span]] = {}
        for schema, statement in statements:
            cursor = _Cursor(_tokens(statement.text))
            if cursor.accept("ALTER"):
                self._alter(schema, statement, cursor, enums)
                continue
            if cursor.accept("DROP"):
                self._drop(schema, statement, cursor)
                continue
            if cursor.accept("RENAME"):
                self._rename(schema, statement, cursor)
                continue
            if not cursor.accept("CREATE"):
                continue
            if cursor.accept("TYPE"):
                try:
                    name = cursor.identifier()
                    cursor.expect("AS")
                    cursor.expect("ENUM")
                    values = _values(cursor.group())
                    self._finished(cursor)
                    enums[(schema.repository, name)] = (values, statement.span())
                except _UnparsedError:
                    continue
            elif cursor.accept("TABLE"):
                self._table(schema, statement, cursor, enums)
            elif cursor.accept("UNIQUE") and cursor.accept("INDEX"):
                table_name = None
                try:
                    cursor.accept("CONCURRENTLY")
                    if_not_exists = cursor.accept("IF")
                    if if_not_exists:
                        cursor.expect("NOT")
                        cursor.expect("EXISTS")
                    name = cursor.identifier()
                    cursor.expect("ON")
                    table_name = cursor.identifier()
                    if cursor.accept("USING"):
                        cursor.identifier()
                    columns = _names(cursor.group())
                    table = schema.tables.get(table_name)
                    if (
                        if_not_exists
                        and table is not None
                        and any(c.name == name for c in table.constraints)
                    ):
                        continue
                    schema.add_constraint(
                        table_name,
                        Constraint(
                            kind="unique",
                            name=name,
                            columns=columns,
                            spans=(statement.span(),),
                        ),
                    )
                except _UnparsedError:
                    if table_name:
                        schema.mark_uncertain(table_name, statement.span())

    def _rename(self, schema: Schema, statement: _Statement, cursor: _Cursor) -> None:
        name = None
        try:
            cursor.expect("TABLE")
            for part in _parts(cursor.tokens[cursor.index :]):
                item = _Cursor(part)
                name = item.identifier()
                item.expect("TO")
                new_name = item.identifier()
                self._finished(item)
                schema.rename_table(name, new_name, statement.span(part))
        except _UnparsedError:
            if name:
                schema.mark_uncertain(name, statement.span())

    @staticmethod
    def _finished(cursor: _Cursor) -> None:
        if cursor.index != len(cursor.tokens):
            raise _UnparsedError("Unrecognized trailing syntax")

    def _drop(self, schema: Schema, statement: _Statement, cursor: _Cursor) -> None:
        name = None
        try:
            if cursor.accept("TABLE"):
                if cursor.accept("IF"):
                    cursor.expect("EXISTS")
                for part in _parts(cursor.tokens[cursor.index :]):
                    item = _Cursor(part)
                    name = item.identifier()
                    item.accept("CASCADE") or item.accept("RESTRICT")
                    self._finished(item)
                    schema.drop_table(name, statement.span(part))
            elif cursor.accept("INDEX"):
                if cursor.accept("IF"):
                    cursor.expect("EXISTS")
                index = cursor.identifier()
                if cursor.accept("ON"):
                    name = cursor.identifier()
                    self._finished(cursor)
                    schema.drop_constraint(name, index, statement.span())
                else:
                    self._finished(cursor)
                    for table in tuple(schema.tables.values()):
                        if any(c.name == index for c in table.constraints):
                            schema.drop_constraint(table.name, index, statement.span())
        except _UnparsedError:
            if name:
                schema.mark_uncertain(name, statement.span())

    def _alter(
        self,
        schema: Schema,
        statement: _Statement,
        cursor: _Cursor,
        enums: dict[tuple[str, str], tuple[tuple[str, ...], Span]],
    ) -> None:
        name = None
        try:
            cursor.expect("TABLE")
            if cursor.accept("IF"):
                cursor.expect("EXISTS")
            cursor.accept("ONLY")
            name = cursor.identifier()
        except _UnparsedError:
            return
        for part in _parts(cursor.tokens[cursor.index :]):
            try:
                self._alter_part(schema, statement, name, _Cursor(part), enums)
            except _UnparsedError:
                schema.mark_uncertain(name, statement.span(part))

    def _alter_part(
        self,
        schema: Schema,
        statement: _Statement,
        name: str,
        item: _Cursor,
        enums: dict[tuple[str, str], tuple[tuple[str, ...], Span]],
    ) -> None:
        span = statement.span(item.tokens)
        table = schema.tables.get(name)
        columns = tuple(c.name for c in table.columns) if table else ()
        if item.accept("OWNER"):
            item.expect("TO")
            item.identifier()
            self._finished(item)
            return
        if item.accept("ADD"):
            if item.accept("FULLTEXT") or item.accept("SPATIAL"):
                if not (item.accept("KEY") or item.accept("INDEX")):
                    raise _UnparsedError("Expected index")
                return
            if item.accept("INDEX") or item.accept("KEY"):
                return  # Ordinary indexes do not contribute to the model.
            if item.index < len(item.tokens) and item.tokens[item.index].upper in {
                "CONSTRAINT",
                "PRIMARY",
                "UNIQUE",
                "FOREIGN",
                "CHECK",
            }:
                constraint = _constraint(item, statement, columns)
                self._finished(item)
                schema.add_constraint(name, constraint)
            else:
                item.accept("COLUMN")
                definition = self._definition(
                    statement,
                    name,
                    [item.tokens[item.index :]],
                    enums,
                    schema.repository,
                )
                if definition.uncertain or len(definition.columns) != 1:
                    raise _UnparsedError("Unknown column definition")
                schema.add_column(name, definition.columns[0])
                for constraint in definition.constraints:
                    schema.add_constraint(name, constraint)
        elif item.accept("DROP"):
            if item.accept("PRIMARY"):
                item.expect("KEY")
                self._finished(item)
                schema.drop_constraint(name, None, span, kind="primary")
            elif item.accept("CONSTRAINT") or item.accept("INDEX"):
                constraint_name = item.identifier()
                self._finished(item)
                schema.drop_constraint(name, constraint_name, span)
            elif item.accept("FOREIGN"):
                item.expect("KEY")
                constraint_name = item.identifier()
                self._finished(item)
                schema.drop_constraint(name, constraint_name, span)
            else:
                item.accept("COLUMN")
                column_name = item.identifier()
                self._finished(item)
                schema.drop_column(name, column_name, span)
        elif item.accept("RENAME"):
            if item.accept("COLUMN"):
                old = item.identifier()
                item.expect("TO")
                new = item.identifier()
                self._finished(item)
                schema.rename_column(name, old, new, span)
            else:
                item.expect("TO")
                new = item.identifier()
                self._finished(item)
                schema.rename_table(name, new, span)
        elif item.at("MODIFY") or item.at("CHANGE"):
            change = item.take().upper == "CHANGE"
            item.accept("COLUMN")
            old = (
                item.identifier()
                if change
                else _Cursor(item.tokens, item.index).identifier()
            )
            definition = self._definition(
                statement, name, [item.tokens[item.index :]], enums, schema.repository
            )
            if definition.uncertain or len(definition.columns) != 1:
                raise _UnparsedError("Unknown column definition")
            schema.change_column(name, old, definition.columns[0])
            for constraint in definition.constraints:
                schema.add_constraint(name, constraint)
        elif item.accept("ALTER"):
            item.accept("COLUMN")
            column_name = item.identifier()
            column = (
                next((c for c in table.columns if c.name == column_name), None)
                if table
                else None
            )
            updates: dict[str, str | bool | Span | tuple[Span, ...]] = {
                "origin": (span,),
                "defined_at": span,
            }
            if item.accept("TYPE"):
                start = item.index
                while item.index < len(item.tokens) and not item.at("USING"):
                    if item.at("("):
                        item.group()
                    else:
                        item.take()
                type_tokens = item.tokens[start : item.index]
                if not type_tokens:
                    raise _UnparsedError("Missing type")
                updates["datatype"] = _datatype(type_tokens)
                item.index = len(item.tokens)
            elif item.accept("SET"):
                if item.accept("DEFAULT"):
                    return  # Defaults neither constrain roles nor add citations.
                item.expect("NOT")
                item.expect("NULL")
                updates["mandatory"] = True
            elif item.accept("DROP"):
                if item.accept("DEFAULT"):
                    self._finished(item)
                    return
                item.expect("NOT")
                item.expect("NULL")
                updates["mandatory"] = False
            elif item.accept("ADD"):
                item.expect("GENERATED")
                if not item.accept("ALWAYS"):
                    item.expect("BY")
                    item.expect("DEFAULT")
                item.expect("AS")
                item.expect("IDENTITY")
                if item.at("("):
                    item.group()
                self._finished(item)
                return
            else:
                raise _UnparsedError("Unknown column alteration")
            self._finished(item)
            if column is None:
                schema.mark_uncertain(name, span)
            else:
                schema.change_column(
                    name, column_name, column.model_copy(update=updates)
                )
        else:
            raise _UnparsedError("Unknown table alteration")

    def _table(
        self,
        schema: Schema,
        statement: _Statement,
        cursor: _Cursor,
        enums: dict[tuple[str, str], tuple[tuple[str, ...], Span]],
    ) -> None:
        name = None
        try:
            if_not_exists = cursor.accept("IF")
            if if_not_exists:
                cursor.expect("NOT")
                cursor.expect("EXISTS")
            name = cursor.identifier()
            parts = _parts(cursor.group())
        except _UnparsedError:
            if name:
                schema.mark_uncertain(name, statement.span())
            return
        schema.create_table(
            self._definition(statement, name, parts, enums, schema.repository),
            if_not_exists=if_not_exists,
        )

    def _definition(
        self,
        statement: _Statement,
        name: str,
        parts: list[list[_Token]],
        enums: dict[tuple[str, str], tuple[tuple[str, ...], Span]],
        repository: str,
    ) -> Table:
        columns: list[Column] = []
        constraints: list[Constraint] = []
        uncertain: list[tuple[str, Span]] = []
        table_constraints = {"CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "CHECK"}
        ignored_indexes = {"KEY", "INDEX", "FULLTEXT", "SPATIAL"}
        column_names = []
        for part in parts:
            if part and part[0].upper not in table_constraints | ignored_indexes:
                try:
                    column_names.append(_Cursor(part).identifier())
                except _UnparsedError:
                    pass  # The main pass records this part as uncertain.
        known_columns = tuple(column_names)
        for part in parts:
            if not part:
                continue
            item = _Cursor(part)
            if part[0].upper in table_constraints:
                try:
                    constraints.append(_constraint(item, statement, known_columns))
                except _UnparsedError:
                    uncertain.append(("unparsed_statement", statement.span(part)))
                continue
            if part[0].upper in ignored_indexes:
                continue  # Ordinary indexes are explicitly outside the contract.
            try:
                column_name = item.identifier()
                start = item.index
                while item.index < len(part):
                    if part[item.index].upper in _MODIFIERS or (
                        (item.at("CHARACTER") or item.at("CHAR"))
                        and item.index + 1 < len(part)
                        and part[item.index + 1].upper == "SET"
                    ):
                        break
                    if item.at("("):
                        item.group()
                    else:
                        item.take()
                type_tokens = part[start : item.index]
                if not type_tokens:
                    raise _UnparsedError("Missing type")
                span = statement.span(part)
                columns.append(
                    Column(
                        name=column_name,
                        datatype=_datatype(type_tokens),
                        mandatory=False,
                        origin=(span,),
                        defined_at=span,
                    )
                )
                if type_tokens[0].upper == "ENUM":
                    values = _values(_Cursor(type_tokens, 1).group())
                    constraints.append(
                        Constraint(
                            kind="value",
                            columns=(column_name,),
                            allowed_values=values,
                            spans=(span,),
                        )
                    )
                else:
                    type_cursor = _Cursor(type_tokens)
                    enum_name = type_cursor.identifier()
                    enum = enums.get((repository, enum_name))
                    if enum:
                        constraints.append(
                            Constraint(
                                kind="value",
                                columns=(column_name,),
                                allowed_values=enum[0],
                                spans=(enum[1],),
                            )
                        )
                while item.index < len(part):
                    if item.accept("NOT"):
                        item.expect("NULL")
                        columns[-1] = columns[-1].model_copy(update={"mandatory": True})
                    elif item.accept("NULL"):
                        columns[-1] = columns[-1].model_copy(
                            update={"mandatory": False}
                        )
                    elif part[item.index].upper in {
                        "CONSTRAINT",
                        "PRIMARY",
                        "UNIQUE",
                        "REFERENCES",
                        "CHECK",
                    }:
                        constraints.append(
                            _constraint(item, statement, known_columns, column_name)
                        )
                    elif item.accept("DEFAULT"):
                        # A default expression is not a constraint. Skip balanced calls.
                        if item.at("("):
                            item.group()
                        elif item.index < len(part):
                            item.take()
                            if item.at("("):
                                item.group()
                    elif item.at("("):
                        item.group()
                    else:
                        item.take()
            except _UnparsedError:
                uncertain.append(("unparsed_statement", statement.span(part)))
        known_columns = tuple(c.name for c in columns)
        valid = []
        for constraint in constraints:
            if all(n in known_columns for n in constraint.columns):
                valid.append(constraint)
            else:
                uncertain.append(("unparsed_statement", constraint.spans[0]))
        return Table(
            name=name,
            columns=tuple(columns),
            constraints=tuple(valid),
            defined_at=statement.span(),
            uncertain=tuple(uncertain),
        )
