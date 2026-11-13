"""SQL CREATE reader: tree-sitter boundaries, quote-aware CREATE TABLE contents.

Named mysqldump constraints are intentionally read from source, not AST children:
that syntax is a known hole in the SQL grammar. ALTER/replay is a later phase.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from tree_sitter_language_pack import get_parser

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
    "CHARACTER",
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


class SQLReader:
    name = "sql"
    patterns: tuple[str, ...] = ("**/*.sql",)

    def read(self, ctx: "ReadContext") -> None:
        parser = get_parser("sql")
        statements: list[tuple[Schema, _Statement]] = []
        schemas: dict[str, Schema] = {}
        for path in ctx.paths:
            source = ctx.read(path)
            if source is None:
                continue
            repository = ctx.repository_of(path).key
            if repository not in schemas:
                schemas[repository] = Schema(reader=self.name, repository=repository)
                ctx.schemas.append(schemas[repository])
            data = "\n".join(source.lines).encode("utf-8")
            tree = parser.parse(data)
            # Grammar recovery may split a CREATE into a statement and a sibling
            # ERROR. Reunite those fragments at the tree's top-level terminators.
            start: tuple[int, int] | None = None
            end = 0
            for node in (*tree.root_node.children, None):
                if node is None or node.type == ";":
                    if start is not None:
                        statements.append(
                            (
                                schemas[repository],
                                _Statement(
                                    path, data[start[0] : end].decode("utf-8"), start[1]
                                ),
                            )
                        )
                    start = None
                elif node.type != "comment":
                    if start is None:
                        start = (node.start_byte, node.start_point.row + 1)
                    end = node.end_byte
        enums: dict[tuple[str, str], tuple[tuple[str, ...], Span]] = {}
        for schema, statement in statements:
            tokens = _tokens(statement.text)
            cursor = _Cursor(tokens)
            if not cursor.accept("CREATE"):
                continue
            if cursor.accept("TYPE"):
                try:
                    name = cursor.identifier()
                    cursor.expect("AS")
                    cursor.expect("ENUM")
                    enums[(schema.repository, name)] = (
                        _values(cursor.group()),
                        statement.span(),
                    )
                except _UnparsedError:
                    continue
        for schema, statement in statements:
            cursor = _Cursor(_tokens(statement.text))
            if not cursor.accept("CREATE"):
                continue
            if cursor.accept("TABLE"):
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
                while (
                    item.index < len(part) and part[item.index].upper not in _MODIFIERS
                ):
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
                    enum = enums.get((schema.repository, enum_name))
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
        schema.create_table(
            Table(
                name=name,
                columns=tuple(columns),
                constraints=tuple(valid),
                defined_at=statement.span(),
                uncertain=tuple(uncertain),
            ),
            if_not_exists=if_not_exists,
        )
