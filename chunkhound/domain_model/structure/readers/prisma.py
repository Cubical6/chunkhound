"""Read Prisma storage models into the reader-local schema."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from tree_sitter import Node
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


def _text(node: Node, data: bytes) -> str:
    return data[node.start_byte : node.end_byte].decode("utf-8")


def _without_comments(text: str) -> str:
    # Preserve quoted URLs and escaped quotes while removing line comments.
    return re.sub(
        r'"(?:\\.|[^"\\])*"|//[^\n]*',
        lambda m: "" if m.group().startswith("//") else m.group(),
        text,
    )


def _enum_values(node: Node, data: bytes) -> tuple[str, ...]:
    text = _without_comments(_text(node, data))
    body = text.partition("{")[2].rpartition("}")[0]
    # The bundled grammar does not parse enum value attributes reliably.
    token = re.compile(
        r'@@\w+(?:\s*\([^)]*\))?|(@?\w+)(?:\s+@map\s*\(\s*"([^"\\]*)"\s*\))?|"(?:\\.|[^"\\])*"'
    )
    return tuple(
        m.group(2) if m.group(2) is not None else m.group(1)
        for m in token.finditer(body)
        if m.group(1) and not m.group(1).startswith("@")
    )


def _map(text: str, prefix: str) -> str | None:
    match = re.search(rf'{prefix}map\s*\(\s*"([^"\\]*)"\s*\)', text)
    return match.group(1) if match else None


def _span(path: str, node: Node) -> Span:
    return Span(
        path=path,
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
        reader="prisma",
    )


def _array(text: str, name: str) -> tuple[str, ...] | None:
    match = re.search(rf"{name}\s*\[([^\]]*)\]", text)
    if not match:
        return None
    values = tuple(part.strip() for part in match.group(1).split(","))
    return values if all(re.fullmatch(r"\w+", value) for value in values) else None


class PrismaReader:
    name = "prisma"
    patterns: tuple[str, ...] = ("**/*.prisma",)

    def read(self, ctx: ReadContext) -> None:
        # Gather declarations first so relations can resolve mapped names in any file.
        blocks: dict[str, list[tuple[str, Node, bytes]]] = {}
        for path in ctx.paths:
            source = ctx.read(path)
            if source is None:
                continue
            data = "\n".join(source.lines).encode("utf-8")
            root = get_parser("prisma").parse(data).root_node
            key = ctx.repository_of(path).key
            blocks.setdefault(key, []).extend(
                (path, node, data)
                for node in root.named_children
                if node.type in ("model_block", "enum_block")
            )
        for key, declarations in blocks.items():
            self._repository(ctx, key, declarations)

    def _repository(
        self, ctx: ReadContext, key: str, declarations: list[tuple[str, Node, bytes]]
    ) -> None:
        models: dict[str, tuple[str, Node, bytes]] = {}
        enums: dict[str, tuple[str, ...]] = {}
        for path, node, data in declarations:
            identifiers = [n for n in node.named_children if n.type == "identifier"]
            if not identifiers:
                continue
            name = _text(identifiers[0], data)
            if node.type == "enum_block":
                enums[name] = _enum_values(node, data)
            elif not re.search(r"@@ignore\b", _text(node, data)):
                models[name] = (path, node, data)
        names = {
            name: _map(_text(node, data), "@@") or name
            for name, (_, node, data) in models.items()
        }
        field_maps: dict[str, dict[str, str]] = {}
        for name, (_, node, data) in models.items():
            mapping = {}
            for field_node in (
                n for n in node.named_children if n.type == "model_field"
            ):
                field_text = _without_comments(_text(field_node, data))
                match = re.match(r"(\w+)\s+", field_text)
                if match:
                    mapping[match.group(1)] = _map(
                        field_text, r"(?<!@)@"
                    ) or match.group(1)
            field_maps[name] = mapping
        schema = Schema(reader=self.name, repository=key)
        for name, (path, node, data) in models.items():
            columns: list[Column] = []
            constraints: list[Constraint] = []
            uncertain: list[tuple[str, Span]] = []
            for child in node.named_children:
                text = _without_comments(_text(child, data))
                span = _span(path, child)
                if child.type == "model_multi_attribute":
                    match = re.match(r"@@(id|unique)\s*\(", text)
                    if match:
                        fields = _array(text, r"\(") or _array(text, r"fields\s*:")
                        if fields and all(f in field_maps[name] for f in fields):
                            constraints.append(
                                Constraint(
                                    kind="primary"
                                    if match.group(1) == "id"
                                    else "unique",
                                    columns=tuple(field_maps[name][f] for f in fields),
                                    spans=(span,),
                                )
                            )
                        else:
                            uncertain.append(("unparsed_statement", span))
                    continue
                if child.type != "model_field":
                    continue
                match = re.match(r"(\w+)\s+(\w+)(\[\]|\?)?", text)
                if not match or re.search(r"(?<!@)@ignore\b", text):
                    continue
                field, typ, modifier = match.groups()
                if modifier == "[]":
                    continue
                if typ in models:
                    if re.search(r"@relation\b", text):
                        local = _array(text, r"fields\s*:")
                        remote = _array(text, r"references\s*:")
                        if (
                            local
                            and remote
                            and len(local) == len(remote)
                            and all(f in field_maps[name] for f in local)
                            and all(f in field_maps[typ] for f in remote)
                        ):
                            constraints.append(
                                Constraint(
                                    kind="foreign",
                                    columns=tuple(field_maps[name][f] for f in local),
                                    ref_table=names[typ],
                                    ref_columns=tuple(
                                        field_maps[typ][f] for f in remote
                                    ),
                                    spans=(span,),
                                )
                            )
                        elif local or remote:
                            uncertain.append(("unparsed_statement", span))
                    continue
                if typ not in enums and typ not in {
                    "String",
                    "Boolean",
                    "Int",
                    "BigInt",
                    "Float",
                    "Decimal",
                    "DateTime",
                    "Json",
                    "Bytes",
                    "Unsupported",
                }:
                    uncertain.append(("unparsed_statement", span))
                    continue
                col = field_maps[name][field]
                db = re.search(r"@db\.\w+(?:\([^)]*\))?", text)
                datatype = typ + (" " + db.group() if db else "")
                columns.append(
                    Column(
                        name=col,
                        datatype=datatype,
                        mandatory=modifier != "?",
                        origin=(span,),
                        defined_at=span,
                    )
                )
                attributes: tuple[tuple[str, Literal["primary", "unique"]], ...] = (
                    ("id", "primary"),
                    ("unique", "unique"),
                )
                for attr, kind in attributes:
                    if re.search(rf"(?<!@)@{attr}\b", text):
                        constraints.append(
                            Constraint(kind=kind, columns=(col,), spans=(span,))
                        )
                if typ in enums:
                    constraints.append(
                        Constraint(
                            kind="value",
                            columns=(col,),
                            allowed_values=enums[typ],
                            spans=(span,),
                        )
                    )
            schema.create_table(
                Table(
                    name=names[name],
                    model_class=name,
                    columns=tuple(columns),
                    constraints=tuple(constraints),
                    defined_at=_span(path, node),
                    uncertain=tuple(uncertain),
                )
            )
        ctx.schemas.append(schema)
