"""Extract documentation-only C4 facts with literal, line-bounded evidence."""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from chunkhound.code_mapper.c4.llm import (
    AnswerRejectedError,
    C4Llm,
    RetryQueue,
    TransientStepError,
    load_c4_prompt,
)
from chunkhound.code_mapper.c4.model import Citation, LockedDocumented
from chunkhound.core.detection import detect_language
from chunkhound.core.types.common import Language


@dataclass(frozen=True)
class TopicSources:
    topic: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class DocElement:
    kind: Literal["person", "external", "container", "component"]
    term: str
    citation: Citation


@dataclass(frozen=True)
class DocRelation:
    from_term: str
    to_term: str
    title: str
    citation: Citation


@dataclass
class DocumentedOutcome:
    """RetryQueue mutates this outcome; consume it after draining the queue.

    Citations have no target until identity/assembly assigns final C4 IDs. Their
    verified flag proves the quote, not a static reference between internal nodes.
    """

    elements: list[DocElement]
    relations: list[DocRelation]
    hashes: dict[str, str]
    fallback: bool


class _AnswerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Quote(_AnswerModel):
    file: str
    start_line: int
    end_line: int
    quote: str


class _ElementAnswer(_AnswerModel):
    kind: Literal["person", "external", "container", "component"]
    term: str = Field(min_length=1)
    citation: _Quote


class _RelationAnswer(_AnswerModel):
    from_term: str = Field(min_length=1)
    to_term: str = Field(min_length=1)
    title: str = Field(min_length=1)
    citation: _Quote


class DocumentedAnswer(_AnswerModel):
    elements: list[_ElementAnswer]
    relations: list[_RelationAnswer]


def _project_file(project_root: Path, file: str) -> Path | None:
    if Path(file).is_absolute():
        return None
    root = project_root.resolve()
    path = (root / file).resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


def doc_files_for(
    project_root: Path, scope_path: Path, topics: Sequence[TopicSources]
) -> list[str]:
    """Select only scope-root READMEs and existing Markdown cited by topics."""
    root = project_root.resolve()
    scope = scope_path if scope_path.is_absolute() else root / scope_path
    scope = scope.resolve()
    if not scope.is_relative_to(root):
        raise ValueError("Documentation scope must be inside the project")
    candidates = [path.relative_to(root).as_posix() for path in scope.glob("README*")]
    candidates.extend(
        file
        for topic in topics
        for file in topic.files
        if detect_language(Path(file)) == Language.MARKDOWN
    )
    return sorted(
        {file for file in candidates if _project_file(root, file) is not None}
    )


def verify_quote(
    project_root: Path, file: str, start_line: int, end_line: int, quote: str
) -> bool:
    """Whitespace may differ, but the entire quote must occur in this line span."""
    path = _project_file(project_root, file)
    if path is None or start_line < 1 or end_line < start_line:
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    if end_line > len(lines):
        return False
    normalized = " ".join(quote.split())
    span = " ".join(" ".join(lines[start_line - 1 : end_line]).split())
    return bool(normalized) and normalized in span


def check_documented_answer(
    answer: DocumentedAnswer, project_root: Path, doc_files: Sequence[str]
) -> tuple[list[DocElement], list[DocRelation]]:
    """Drop unverified items; rejecting every proposed item is retryable."""
    allowed = set(doc_files)

    def verified(quote: _Quote) -> Citation | None:
        if quote.file not in allowed or not verify_quote(
            project_root, quote.file, quote.start_line, quote.end_line, quote.quote
        ):
            return None
        return Citation(
            target=None,
            file=quote.file,
            start_line=quote.start_line,
            end_line=quote.end_line,
            source="documentation",
            verified=True,
        )

    elements = [
        DocElement(item.kind, item.term, citation)
        for item in answer.elements
        if (citation := verified(item.citation)) is not None
    ]
    relations = [
        DocRelation(item.from_term, item.to_term, item.title, citation)
        for item in answer.relations
        if (citation := verified(item.citation)) is not None
    ]
    if (answer.elements or answer.relations) and not (elements or relations):
        raise AnswerRejectedError("documented: no proposed item has a literal quote")
    return elements, relations


def _previous_outcome(
    locked: LockedDocumented | None, hashes: dict[str, str], *, fallback: bool
) -> DocumentedOutcome:
    if locked is None:
        return DocumentedOutcome([], [], dict(hashes), fallback)
    return DocumentedOutcome(
        TypeAdapter(list[DocElement]).validate_python(locked.elements),
        TypeAdapter(list[DocRelation]).validate_python(locked.relations),
        dict(locked.hashes),
        fallback,
    )


async def extract_documented(
    *,
    project_root: Path,
    doc_files: Sequence[str],
    locked: LockedDocumented | None,
    llm: C4Llm,
    retries: RetryQueue,
) -> DocumentedOutcome:
    """Call utility once for changed sources, with one delayed recovery attempt."""
    documents: dict[str, bytes] = {}
    for file in sorted(set(doc_files)):
        path = _project_file(project_root, file)
        if path is None:
            raise ValueError(f"Documentation source is not a project file: {file}")
        documents[file] = path.read_bytes()
    hashes = {
        file: hashlib.sha256(content).hexdigest() for file, content in documents.items()
    }
    if locked is not None and locked.hashes == hashes:
        return _previous_outcome(locked, hashes, fallback=False)
    if not documents:
        return DocumentedOutcome([], [], hashes, False)
    if llm.trial:
        return _previous_outcome(locked, hashes, fallback=False)

    prompt = (
        load_c4_prompt("documented")
        + "\nInput:\n"
        + json.dumps(
            {
                "documents": [
                    {
                        "file": file,
                        "lines": [
                            {"line": number, "text": line}
                            for number, line in enumerate(
                                content.decode("utf-8").splitlines(), 1
                            )
                        ],
                    }
                    for file, content in documents.items()
                ]
            },
            ensure_ascii=False,
        )
    )
    result = DocumentedOutcome([], [], hashes, False)

    async def attempt() -> DocumentedOutcome:
        answer = await llm.call(
            "documented", DocumentedAnswer, prompt, provider="utility"
        )
        elements, relations = check_documented_answer(answer, project_root, doc_files)
        return DocumentedOutcome(elements, relations, hashes, False)

    def default() -> DocumentedOutcome:
        return _previous_outcome(locked, hashes, fallback=True)

    def apply(value: DocumentedOutcome, fallback: bool) -> None:
        result.elements = value.elements
        result.relations = value.relations
        result.hashes = value.hashes
        result.fallback = fallback

    try:
        apply(await attempt(), False)
    except TransientStepError:
        retries.defer("documented", attempt, default, apply)
    return result
