"""Source-positioned Markdown tables and visible text from the existing grammars."""

from collections.abc import Sequence
from dataclasses import dataclass
from html import unescape
from pathlib import Path

import tree_sitter_markdown
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from chunkhound.parsers.mappings.markdown import MarkdownMapping


@dataclass(frozen=True)
class TableRow:
    line: int
    cells: tuple[str, ...]
    raw: str


@dataclass(frozen=True)
class ServiceTable:
    path: str
    headings: tuple[str, ...]
    header: tuple[str, ...]
    rows: tuple[TableRow, ...]


def _visible(node: Node, source: bytes) -> str:
    if node.type in {
        "emphasis_delimiter",
        "code_span_delimiter",
        "strikethrough_delimiter",
    }:
        return ""
    if node.type == "backslash_escape":
        return source[node.start_byte + 1 : node.end_byte].decode("utf-8")
    if node.type in {
        "inline_link",
        "full_reference_link",
        "collapsed_reference_link",
        "shortcut_link",
        "image",
    }:
        return "".join(
            _visible(child, source)
            for child in node.named_children
            if child.type in {"link_text", "image_description"}
        )
    # Most text is held in gaps between grammar nodes, not in text children.
    parts = []
    offset = node.start_byte
    for child in node.children:
        parts.append(source[offset : child.start_byte].decode("utf-8"))
        parts.append(_visible(child, source))
        offset = child.end_byte
    parts.append(source[offset : node.end_byte].decode("utf-8"))
    return "".join(parts)


def _text(node: Node, source: bytes, parser: Parser) -> str:
    content = source[node.start_byte : node.end_byte]
    tree = parser.parse(content)
    return unescape(_visible(tree.root_node, content)).strip()


def _heading(node: Node, source: bytes, parser: Parser) -> tuple[int, str]:
    content = node.child_by_field_name("heading_content")
    assert content is not None  # Both grammar heading forms require content.
    if node.type == "atx_heading":
        level = len(source[node.children[0].start_byte : node.children[0].end_byte])
    else:
        level = 1 if node.children[-1].type == "setext_h1_underline" else 2
    return level, _text(content, source, parser)


def _cells(node: Node, source: bytes, parser: Parser) -> tuple[str, ...]:
    return tuple(
        _text(child, source, parser)
        for child in node.named_children
        if child.type == "pipe_table_cell"
    )


def read_tables(project_root: Path, doc_files: Sequence[str]) -> list[ServiceTable]:
    """Read only selected documents; retain original 1-based rows and source text."""
    language = Language(tree_sitter_markdown.language())
    block = Parser(language)
    inline = Parser(Language(tree_sitter_markdown.inline_language()))
    query = Query(
        language,
        MarkdownMapping().get_table_query()
        + "\n(atx_heading) @heading\n(setext_heading) @heading",
    )
    tables = []
    for path in doc_files:
        source = (project_root / path).read_bytes()
        lines = source.decode("utf-8", errors="replace").splitlines()
        tree = block.parse(source)
        captures = QueryCursor(query).captures(tree.root_node)
        nodes = [*captures.get("pipe_table", []), *captures.get("heading", [])]
        headings: list[tuple[int, str]] = []
        for node in sorted(nodes, key=lambda item: item.start_byte):
            if node.type != "pipe_table":
                level, title = _heading(node, source, inline)
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, title))
                continue
            header = next(
                child
                for child in node.named_children
                if child.type == "pipe_table_header"
            )
            rows = tuple(
                TableRow(
                    child.start_point.row + 1,
                    _cells(child, source, inline),
                    lines[child.start_point.row],
                )
                for child in node.named_children
                if child.type == "pipe_table_row"
            )
            tables.append(
                ServiceTable(
                    path,
                    tuple(title for _, title in headings),
                    _cells(header, source, inline),
                    rows,
                )
            )
    return tables
