"""Deterministic fragments with original line numbers and heading context.

Every source line belongs to exactly one fragment. Fragment identity excludes
line numbers, so inserting a line elsewhere keeps other fragments reusable.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import accumulate
from typing import Literal

from chunkhound.services.extraction.sources import SourceVersion

FRAGMENTATION_VERSION = 1

# Widest fragment id used when measuring; bundles stay far below 10k fragments.
MEASURE_FID = "F9999"

_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)(.*)$")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")

Numbering = Literal["relative", "absolute"]


class FragmentTooLargeError(ValueError):
    """A single line exceeds the fragment budget; fragments never truncate."""

    def __init__(self, path: str, line: int, max_chars: int) -> None:
        super().__init__(
            f"Line {path}:{line} does not fit in a fragment of {max_chars} characters"
        )
        self.path = path
        self.line = line


@dataclass(frozen=True)
class FragmentIdentity:
    path: str
    text_sha256: str
    context_sha256: str
    fragmentation_version: int


@dataclass(frozen=True)
class Fragment:
    source: SourceVersion
    start_line: int
    end_line: int
    heading_path: tuple[str, ...]

    @property
    def lines(self) -> tuple[str, ...]:
        return self.source.lines[self.start_line - 1 : self.end_line]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def identity(self) -> FragmentIdentity:
        context = json.dumps(
            [self.source.path, list(self.heading_path)], ensure_ascii=False
        )
        return FragmentIdentity(
            path=self.source.path,
            text_sha256=hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
            context_sha256=hashlib.sha256(context.encode("utf-8")).hexdigest(),
            fragmentation_version=FRAGMENTATION_VERSION,
        )

    def header(self, fid: str) -> str:
        return _header(fid, self.source.path, self.heading_path)

    def render(self, fid: str, numbering: Numbering) -> str:
        first = 1 if numbering == "relative" else self.start_line
        body = [f"{first + offset}| {line}" for offset, line in enumerate(self.lines)]
        return "\n".join([self.header(fid), *body])


def _header(fid: str, path: str, heading_path: Sequence[str]) -> str:
    return " › ".join([f"=== {fid} · {path}", *heading_path])


@dataclass
class _Section:
    start: int  # heading line (1-based); 1 for the root
    end: int
    level: int  # 0 for the root
    title: str | None
    children: list["_Section"] = field(default_factory=list)


@dataclass(frozen=True)
class _Layout:
    headings: dict[int, tuple[int, str]]
    in_code: tuple[bool, ...]  # 1-based via index - 1
    front_matter: tuple[int, int] | None


def _scan_markdown(lines: Sequence[str]) -> _Layout:
    headings: dict[int, tuple[int, str]] = {}
    in_code = [False] * len(lines)
    front_matter: tuple[int, int] | None = None
    start = 0
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() in {"---", "..."}:
                front_matter = (1, index + 1)
                for covered in range(index + 1):
                    in_code[covered] = True
                start = index + 1
                break
    fence: str | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        if fence is not None:
            in_code[index] = True
            stripped = line.strip()
            if stripped.startswith(fence) and set(stripped) == {fence[0]}:
                fence = None
            continue
        if match := _FENCE.match(line):
            fence = match.group(1)
            in_code[index] = True
            continue
        if match := _ATX.match(line):
            title = _CLOSING_HASHES.sub("", match.group(2)).strip()
            headings[index + 1] = (len(match.group(1)), title)
    return _Layout(headings, tuple(in_code), front_matter)


def _section_tree(line_count: int, headings: dict[int, tuple[int, str]]) -> _Section:
    root = _Section(start=1, end=line_count, level=0, title=None)
    stack = [root]
    for line in sorted(headings):
        level, title = headings[line]
        while stack[-1].level >= level:
            stack.pop().end = line - 1
        section = _Section(start=line, end=line_count, level=level, title=title)
        stack[-1].children.append(section)
        stack.append(section)
    return root


class _Splitter:
    def __init__(
        self, source: SourceVersion, layout: _Layout, root: _Section, max_chars: int
    ) -> None:
        self.source = source
        self.layout = layout
        self.max_chars = max_chars
        # Rendered width of each line with absolute numbering plus its newline.
        widths = [
            len(f"{number}| {line}") + 1 for number, line in enumerate(source.lines, 1)
        ]
        self.prefix = [0, *accumulate(widths)]
        self.paths = _paths_by_line(len(source.lines), root)
        self.ranges: list[tuple[int, int]] = []

    def path(self, start: int) -> tuple[str, ...]:
        return self.paths[start - 1]

    def fits(self, start: int, end: int) -> bool:
        header = len(_header(MEASURE_FID, self.source.path, self.path(start)))
        return header + self.prefix[end] - self.prefix[start - 1] <= self.max_chars

    def section(self, node: _Section) -> None:
        if self.fits(node.start, node.end):
            self.ranges.append((node.start, node.end))
            return
        intro_start = node.start
        if node.level == 0 and self.layout.front_matter is not None:
            front_start, front_end = self.layout.front_matter
            self.flat(front_start, front_end)
            intro_start = front_end + 1
        intro_end = node.children[0].start - 1 if node.children else node.end
        if intro_start <= intro_end:
            self.flat(intro_start, intro_end)
        for child in node.children:
            self.section(child)

    def flat(self, start: int, end: int) -> None:
        if self.fits(start, end):
            self.ranges.append((start, end))
            return
        current: tuple[int, int] | None = None
        for unit_start, unit_end in self._paragraphs(start, end):
            if current is not None and self.fits(current[0], unit_end):
                current = (current[0], unit_end)
                continue
            if current is not None:
                self.ranges.append(current)
                current = None
            if self.fits(unit_start, unit_end):
                current = (unit_start, unit_end)
            else:
                self._lines(unit_start, unit_end)
        if current is not None:
            self.ranges.append(current)

    def _paragraphs(self, start: int, end: int) -> list[tuple[int, int]]:
        """Blank lines outside code close a unit; they stay attached to it."""
        units: list[tuple[int, int]] = []
        unit_start = start
        for line in range(start, end):
            if (
                not self.source.lines[line - 1].strip()
                and not self.layout.in_code[line - 1]
            ):
                units.append((unit_start, line))
                unit_start = line + 1
        if unit_start <= end:
            units.append((unit_start, end))
        return units

    def _lines(self, start: int, end: int) -> None:
        current: tuple[int, int] | None = None
        for line in range(start, end + 1):
            if not self.fits(line, line):
                raise FragmentTooLargeError(self.source.path, line, self.max_chars)
            if current is not None and self.fits(current[0], line):
                current = (current[0], line)
                continue
            if current is not None:
                self.ranges.append(current)
            current = (line, line)
        if current is not None:
            self.ranges.append(current)


def _paths_by_line(line_count: int, root: _Section) -> list[tuple[str, ...]]:
    """Context of a piece starting at a line: enclosing headings above that line.

    A piece that starts on a heading line gets its parents' chain; the heading
    itself is part of the piece's text.
    """
    paths: list[tuple[str, ...]] = [()] * line_count

    def visit(node: _Section, chain: tuple[str, ...]) -> None:
        inner = chain if node.title is None else (*chain, node.title)
        body_start = node.start if node.title is None else node.start + 1
        for line in range(body_start, node.end + 1):
            paths[line - 1] = inner
        if node.title is not None:
            paths[node.start - 1] = chain
        for child in node.children:
            visit(child, inner)

    visit(root, ())
    return paths


def fragment_document(
    source: SourceVersion, *, max_chars: int, markdown: bool
) -> list[Fragment]:
    """Split by heading subtrees (Markdown), then paragraphs, then lines."""
    if not source.lines:
        return []
    if markdown:
        layout = _scan_markdown(source.lines)
    else:
        layout = _Layout({}, (False,) * len(source.lines), None)
    root = _section_tree(len(source.lines), layout.headings)
    splitter = _Splitter(source, layout, root, max_chars)
    splitter.section(root)
    return [
        Fragment(source, start, end, splitter.path(start))
        for start, end in sorted(splitter.ranges)
    ]


def fragment_ranges(
    source: SourceVersion,
    ranges: Sequence[tuple[int, int]],
    *,
    max_chars: int,
) -> list[Fragment]:
    """Application-supplied ranges; overlap is a caller bug, not merged here."""
    ordered = sorted(ranges)
    for (_, previous_end), (start, _) in zip(ordered, ordered[1:], strict=False):
        if start <= previous_end:
            raise ValueError(f"Overlapping ranges for {source.path}")
    layout = _Layout({}, (False,) * len(source.lines), None)
    root = _section_tree(len(source.lines), {})
    splitter = _Splitter(source, layout, root, max_chars)
    for start, end in ordered:
        if start < 1 or end < start or end > len(source.lines):
            raise ValueError(f"Invalid range {start}-{end} for {source.path}")
        splitter.flat(start, end)
    return [
        Fragment(source, start, end, splitter.path(start))
        for start, end in sorted(splitter.ranges)
    ]
