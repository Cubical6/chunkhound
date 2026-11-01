"""Extract documentation-only C4 facts with literal, line-bounded evidence."""

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from chunkhound.code_mapper.c4.llm import (
    AnswerRejectedError,
    C4Llm,
    RetryQueue,
    TransientStepError,
    load_c4_prompt,
    public_rule,
    rejection_rule,
)
from chunkhound.code_mapper.c4.model import Citation, LockedDocumented
from chunkhound.core.detection import detect_language
from chunkhound.core.types.common import Language
from chunkhound.services.extraction.budget import (
    effective_target,
    max_fragment_chars,
)
from chunkhound.services.extraction.errors import (
    INPUT_REJECTED_MARKERS,
    ProviderInputRefusedError,
    TransientCallError,
    UnreadableAnswerError,
    has_marker,
    is_unreadable,
)
from chunkhound.services.extraction.fragments import Fragment, fragment_document
from chunkhound.services.extraction.runner import (
    AttemptRecord,
    ExtractionCounts,
    Failed,
    Rejected,
    Valid,
    run_extraction,
)
from chunkhound.services.extraction.sources import (
    SourceError,
    SourceVersion,
    read_source,
)
from chunkhound.services.extraction.store import ExtractionStore

EXTRACTION_CACHE = Path(".chunkhound/extraction")
_VALIDATOR_VERSION = 1


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


Span = tuple[str, int, int]


@dataclass
class DocumentedOutcome:
    """RetryQueue mutates this outcome; consume it after draining the queue.

    Citations have no target until identity/assembly assigns final C4 IDs. Their
    verified flag proves the quote, not a static reference between internal nodes.
    Fallback markers live here, never in the locked items, so lock bytes are
    unchanged: ``fallback_fragments`` lists fragments that still failed after
    recovery, ``fallback_citations`` the spans of items taken from the lock.
    """

    elements: list[DocElement]
    relations: list[DocRelation]
    hashes: dict[str, str]
    fallback: bool
    fallback_fragments: frozenset[Span] = frozenset()
    fallback_citations: frozenset[Span] = frozenset()
    counts: ExtractionCounts | None = field(default=None, compare=False)
    fragment_total: int = field(default=0, compare=False)
    fallback_bundles: int = field(default=0, compare=False)


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
        and verify_quote(
            project_root,
            citation.file,
            citation.start_line,
            citation.end_line,
            item.term,
        )
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
    locked: LockedDocumented | None,
    hashes: dict[str, str],
    project_root: Path,
    *,
    fallback: bool,
) -> DocumentedOutcome:
    if locked is None:
        return DocumentedOutcome([], [], dict(hashes), fallback)
    return DocumentedOutcome(
        [
            item
            for item in TypeAdapter(list[DocElement]).validate_python(locked.elements)
            # Older locks retain the citation span, but not the original quote.
            if verify_quote(
                project_root,
                item.citation.file,
                item.citation.start_line,
                item.citation.end_line,
                item.term,
            )
        ],
        TypeAdapter(list[DocRelation]).validate_python(locked.relations),
        dict(locked.hashes),
        fallback,
    )


class _FragmentQuote(_AnswerModel):
    start_line: int
    end_line: int
    quote: str


class _FragmentElement(_AnswerModel):
    kind: Literal["person", "external", "container", "component"]
    term: str = Field(min_length=1)
    citation: _FragmentQuote


class _FragmentRelation(_AnswerModel):
    from_term: str = Field(min_length=1)
    to_term: str = Field(min_length=1)
    title: str = Field(min_length=1)
    citation: _FragmentQuote


class DocumentedPart(_AnswerModel):
    """One fragment's answer; lines are relative to the fragment."""

    elements: list[_FragmentElement]
    relations: list[_FragmentRelation]


@dataclass(frozen=True)
class _Checked:
    """Validated items with absolute citations, plus quotes for storage."""

    elements: tuple[tuple[DocElement, str], ...]
    relations: tuple[tuple[DocRelation, str], ...]


def _quote_in_lines(
    lines: Sequence[str], start_line: int, end_line: int, quote: str
) -> bool:
    """Same rule as verify_quote, on lines already read for this run."""
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        return False
    normalized = " ".join(quote.split())
    span = " ".join(" ".join(lines[start_line - 1 : end_line]).split())
    return bool(normalized) and normalized in span


class _DocumentedGoal:
    name = "documented"
    line_numbering: Literal["relative", "absolute"] = "relative"

    def __init__(self) -> None:
        self._instructions = load_c4_prompt("documented")
        schema = json.dumps(DocumentedPart.model_json_schema(), sort_keys=True)
        self.version = hashlib.sha256(
            f"{self._instructions}\n{schema}\n{_VALIDATOR_VERSION}".encode()
        ).hexdigest()

    def instructions(self) -> str:
        return self._instructions

    def part_model(self) -> type[BaseModel]:
        return DocumentedPart

    def max_completion_tokens(self, bundle_chars: int) -> int:
        return max(2_048, min(16_384, math.ceil(bundle_chars / 10)))

    def validate(self, fragment: Fragment, part: Any) -> _Checked | Rejected:
        offset = fragment.start_line - 1
        size = fragment.end_line - fragment.start_line + 1
        lines = fragment.source.lines

        def cited(quote: _FragmentQuote) -> Citation | None:
            if not 1 <= quote.start_line <= quote.end_line <= size:
                return None
            start, end = quote.start_line + offset, quote.end_line + offset
            if not _quote_in_lines(lines, start, end, quote.quote):
                return None
            return Citation(
                target=None,
                file=fragment.source.path,
                start_line=start,
                end_line=end,
                source="documentation",
                verified=True,
            )

        elements = tuple(
            (DocElement(item.kind, item.term, citation), item.citation.quote)
            for item in part.elements
            if (citation := cited(item.citation)) is not None
            and _quote_in_lines(
                lines, citation.start_line, citation.end_line, item.term
            )
        )
        relations = tuple(
            (
                DocRelation(item.from_term, item.to_term, item.title, citation),
                item.citation.quote,
            )
            for item in part.relations
            if (citation := cited(item.citation)) is not None
        )
        if (part.elements or part.relations) and not (elements or relations):
            return Rejected("no proposed item has a literal quote")
        return _Checked(elements, relations)

    def dump(self, fragment: Fragment, part: _Checked) -> dict[str, Any]:
        offset = fragment.start_line - 1

        def quote(citation: Citation, text: str) -> dict[str, Any]:
            return {
                "start_line": citation.start_line - offset,
                "end_line": citation.end_line - offset,
                "quote": text,
            }

        return {
            "elements": [
                {"kind": e.kind, "term": e.term, "citation": quote(e.citation, q)}
                for e, q in part.elements
            ],
            "relations": [
                {
                    "from_term": r.from_term,
                    "to_term": r.to_term,
                    "title": r.title,
                    "citation": quote(r.citation, q),
                }
                for r, q in part.relations
            ],
        }

    def recheck(
        self, fragment: Fragment, stored: dict[str, Any]
    ) -> _Checked | Rejected:
        try:
            part = DocumentedPart.model_validate(stored)
        except ValidationError:
            return Rejected("invalid answer schema")
        return self.validate(fragment, part)


class _C4Call:
    """Map C4 step failures onto the extraction layer's failure kinds."""

    def __init__(self, llm: C4Llm) -> None:
        self._llm = llm

    async def __call__(
        self, prompt: str, response_model: type[Any], max_completion_tokens: int
    ) -> Any:
        try:
            return await self._llm.call(
                "documented",
                response_model,
                prompt,
                provider="utility",
                max_completion_tokens=max_completion_tokens,
            )
        except Exception as exc:
            if has_marker(exc, INPUT_REJECTED_MARKERS):
                raise ProviderInputRefusedError(str(exc)) from exc
            if isinstance(exc, AnswerRejectedError):
                raise UnreadableAnswerError(rejection_rule(exc)) from exc
            if is_unreadable(exc):
                raise UnreadableAnswerError() from exc
            if isinstance(exc, TransientStepError):
                raise TransientCallError(str(exc)) from exc
            raise

    def estimate_tokens(self, text: str) -> int:
        return self._llm.estimate_tokens(text)


class _Collector:
    """Merge items from first attempts, recovery and fallback without duplicates."""

    def __init__(self, outcome: DocumentedOutcome) -> None:
        self.outcome = outcome
        self._elements: set[tuple[object, ...]] = set()
        self._relations: set[tuple[object, ...]] = set()

    def add(
        self, elements: Sequence[DocElement], relations: Sequence[DocRelation]
    ) -> None:
        for element in elements:
            c = element.citation
            key = (element.kind, element.term, c.file, c.start_line, c.end_line)
            if key not in self._elements:
                self._elements.add(key)
                self.outcome.elements.append(element)
        for relation in relations:
            c = relation.citation
            relation_key = (
                relation.from_term,
                relation.to_term,
                relation.title,
                c.file,
                c.start_line,
                c.end_line,
            )
            if relation_key not in self._relations:
                self._relations.add(relation_key)
                self.outcome.relations.append(relation)

        def position(citation: Citation) -> tuple[str, int, int]:
            return (citation.file, citation.start_line, citation.end_line)

        self.outcome.elements.sort(
            key=lambda e: (*position(e.citation), e.kind, e.term)
        )
        self.outcome.relations.sort(
            key=lambda r: (*position(r.citation), r.from_term, r.to_term, r.title)
        )


def _locked_items(
    locked: LockedDocumented | None,
) -> tuple[list[DocElement], list[DocRelation]]:
    if locked is None:
        return [], []
    return (
        TypeAdapter(list[DocElement]).validate_python(locked.elements),
        TypeAdapter(list[DocRelation]).validate_python(locked.relations),
    )


def _fall_back(
    fragments: Sequence[Fragment],
    locked: LockedDocumented | None,
    collector: _Collector,
) -> None:
    """Spec §8.6: lock items whose span lies wholly inside a failed fragment.

    Elements still need their term inside the span; relations only the span,
    because the lock keeps no quote text (weaker, as before).
    """
    outcome = collector.outcome
    elements, relations = _locked_items(locked)
    spans: set[Span] = set()
    kept_elements: list[DocElement] = []
    kept_relations: list[DocRelation] = []
    for fragment in fragments:
        path = fragment.source.path
        outcome.fallback_fragments |= {(path, fragment.start_line, fragment.end_line)}

        def inside(citation: Citation) -> bool:
            return (
                citation.file == path
                and fragment.start_line <= citation.start_line
                and citation.end_line <= fragment.end_line
            )

        for element in elements:
            c = element.citation
            if inside(c) and _quote_in_lines(
                fragment.source.lines, c.start_line, c.end_line, element.term
            ):
                kept_elements.append(element)
                spans.add((c.file, c.start_line, c.end_line))
        for relation in relations:
            c = relation.citation
            if inside(c):
                kept_relations.append(relation)
                spans.add((c.file, c.start_line, c.end_line))
    outcome.fallback_citations |= spans
    outcome.fallback = True
    collector.add(kept_elements, kept_relations)


def documented_store(project_root: Path, *, read_only: bool) -> ExtractionStore:
    return ExtractionStore(
        project_root / EXTRACTION_CACHE, "documented", read_only=read_only
    )


async def extract_documented(
    *,
    project_root: Path,
    doc_files: Sequence[str],
    locked: LockedDocumented | None,
    llm: C4Llm,
    retries: RetryQueue,
    order_hint: Callable[[Fragment], float] | None = None,
) -> DocumentedOutcome:
    """Bounded, resumable extraction over fragments of every selected document.

    Unchanged sets reuse the lock without a call. Otherwise every fragment gets
    a valid outcome (cached, new or recovered) or falls back per fragment.
    """
    sources: dict[str, SourceVersion] = {}
    for file in sorted(set(doc_files)):
        try:
            sources[file] = read_source(project_root, file, strict=True)
        except SourceError as exc:
            raise ValueError(
                f"Documentation source is not a project file: {file}"
            ) from exc
    hashes = {file: source.sha256 for file, source in sources.items()}
    if locked is not None and locked.hashes == hashes:
        return _previous_outcome(locked, hashes, project_root, fallback=False)
    if not sources:
        return DocumentedOutcome([], [], hashes, False)
    if llm.trial:
        return _previous_outcome(locked, hashes, project_root, fallback=False)

    if locked is None:
        reason = "geen opgeslagen uitkomst"
    else:
        added = len(hashes.keys() - locked.hashes.keys())
        removed = len(locked.hashes.keys() - hashes.keys())
        changed = sum(
            hashes[file] != locked.hashes[file]
            for file in hashes.keys() & locked.hashes.keys()
        )
        reason = f"documentatieset gewijzigd (+{added}/-{removed}/~{changed})"
    report = llm.report("documented", reason)

    limit = llm.input_limit("utility")
    max_chars = max_fragment_chars(effective_target(limit))
    fragments = [
        fragment
        for file, source in sources.items()
        for fragment in fragment_document(
            source,
            max_chars=max_chars,
            markdown=detect_language(Path(file)) == Language.MARKDOWN,
        )
    ]
    goal = _DocumentedGoal()
    store = documented_store(project_root, read_only=False)
    call = _C4Call(llm)
    provider = llm.provider_identity("utility")

    def on_attempt(record: AttemptRecord) -> None:
        if record.outcome == "accepted":
            report.record("geaccepteerd")
        elif record.outcome == "transient":
            report.record("tijdelijke fout")
        else:
            report.record(f"afgekeurd ({public_rule(record.rule)})")

    async def extract(
        subset: Sequence[Fragment],
    ) -> dict[int, Valid[_Checked] | Failed]:
        result = await run_extraction(
            goal,
            subset,
            call=call,
            provider=provider,
            limit=limit,
            store=store,
            concurrency=llm.concurrency,
            order_hint=order_hint,
            on_attempt=on_attempt,
        )
        counts.reused += result.counts.reused
        counts.new += result.counts.new
        counts.split += result.counts.split
        valid = [part.part for part in result.parts.values() if isinstance(part, Valid)]
        collector.add(
            [element for checked in valid for element, _ in checked.elements],
            [relation for checked in valid for relation, _ in checked.relations],
        )
        failed_bundles.clear()
        failed_bundles.update(result.failed_bundles)
        return result.parts

    counts = ExtractionCounts()
    outcome = DocumentedOutcome(
        [], [], hashes, False, counts=counts, fragment_total=len(fragments)
    )
    collector = _Collector(outcome)
    failed_bundles: dict[str, tuple[int, ...]] = {}
    await extract(fragments)

    for origin, indices in list(failed_bundles.items()):
        pending = [fragments[index] for index in indices]
        remaining: list[Fragment] = list(pending)

        async def recover(
            pending: list[Fragment] = pending, remaining: list[Fragment] = remaining
        ) -> list[Fragment]:
            parts = await extract(pending)
            still = [
                pending[i]
                for i, part in sorted(parts.items())
                if isinstance(part, Failed)
            ]
            remaining[:] = still
            if not still:
                return []
            rules = [
                part.rule
                for part in parts.values()
                if isinstance(part, Failed) and part.kind == "rejected"
            ]
            if rules:
                raise AnswerRejectedError(f"documented: {public_rule(rules[0])}")
            raise TransientStepError("documented: fragments still failing")

        def fallback(remaining: list[Fragment] = remaining) -> list[Fragment]:
            return list(remaining)

        def apply(value: list[Fragment], failed: bool) -> None:
            if failed and value:
                outcome.fallback_bundles += 1
                _fall_back(value, locked, collector)

        retries.defer(f"documented:{origin}", recover, fallback, apply, report=report)
    return outcome


def prune_documented_cache(project_root: Path) -> None:
    """Drop long-unused entries; call only after a non-fatal, non-trial run."""
    documented_store(project_root, read_only=False).prune()


def report_lines(docs: DocumentedOutcome) -> list[str]:
    """Bundle accounting for a run that extracted documentation."""
    if docs.counts is None:
        return []
    failed = len(docs.fallback_fragments)
    return [
        f"C4 documented-bundels: {docs.counts.reused} hergebruikt, "
        f"{docs.counts.new} nieuw, {docs.counts.split} gesplitst, "
        f"{docs.fallback_bundles} teruggevallen; fragmenten "
        f"{docs.fragment_total - failed} gedekt, {failed} teruggevallen"
    ]
