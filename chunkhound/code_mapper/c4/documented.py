"""Extract documentation-only C4 facts with literal, line-bounded evidence."""

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from chunkhound.code_mapper.c4.files import (
    c4_settings,
    compile_excludes,
    in_test_directory,
    matches_exclude,
    own_output_matcher,
)
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
from chunkhound.core.config.config import Config
from chunkhound.core.detection import detect_language
from chunkhound.core.types.common import Language
from chunkhound.services.extraction.budget import (
    effective_target,
    max_fragment_chars,
)
from chunkhound.services.extraction.errors import (
    UnreadableAnswerError,
    translate_call_error,
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
from chunkhound.services.extraction.sources import SourceVersion, read_source
from chunkhound.services.extraction.store import ExtractionStore

EXTRACTION_CACHE = Path(".chunkhound/extraction")
_VALIDATOR_VERSION = 2
# History, not architecture: compared with the start of the lowercase file name.
_HISTORY_DOCUMENTS = (
    "changelog",
    "changes",
    "history",
    "news",
    "release_notes",
    "releases",
    "migration",
    "upgrading",
)
# Written for tools or copied from others, not about the system: file names start
# with the first, contain the second, and the third are directory names.
_INSTRUCTION_DOCUMENTS = ("agents", "claude")
_LICENSE_DOCUMENT = "license"
_NON_DOCUMENTATION_DIRECTORIES = frozenset({"prompts", "vendor"})


@dataclass(frozen=True)
class TopicSources:
    topic: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class DocElement:
    kind: Literal["person", "external", "container", "component"]
    term: str
    citation: Citation
    description: str = ""


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
    version: str = field(default="", compare=False)


class _AnswerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _project_file(project_root: Path, file: str) -> Path | None:
    if Path(file).is_absolute():
        return None
    root = project_root.resolve()
    path = (root / file).resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


def doc_files_for(
    project_root: Path,
    scope_path: Path,
    files: Sequence[str],
    config: Config | None,
    own_output: tuple[Path, str] | None = None,
) -> list[str]:
    """Select scope-root READMEs and the run's Markdown, minus non-sources.

    The selection follows the repository only, never the research of this run:
    equal documents then give an equal outcome without a call.
    """
    root = project_root.resolve()
    scope = scope_path if scope_path.is_absolute() else root / scope_path
    scope = scope.resolve()
    if not scope.is_relative_to(root):
        raise ValueError("Documentation scope must be inside the project")
    candidates = [path.relative_to(root).as_posix() for path in scope.glob("README*")]
    candidates.extend(
        file for file in files if detect_language(Path(file)) == Language.MARKDOWN
    )
    settings = c4_settings(config)
    excludes = compile_excludes(settings)
    relative_scope = PurePosixPath(scope.relative_to(root).as_posix())
    is_own_output = own_output_matcher(root, own_output)

    def is_source(file: str) -> bool:
        path = PurePosixPath(file)
        name = path.name.lower()
        directories = [part.lower() for part in path.parent.parts]
        return not (
            any(part.startswith(".") for part in directories)
            or name.startswith((*_HISTORY_DOCUMENTS, *_INSTRUCTION_DOCUMENTS))
            or _LICENSE_DOCUMENT in name
            or not _NON_DOCUMENTATION_DIRECTORIES.isdisjoint(directories)
            or (settings.exclude_test_code and in_test_directory(file, relative_scope))
            or matches_exclude(file, excludes)
            or is_own_output(file)
        )

    return sorted(
        {
            file
            for file in candidates
            if is_source(file) and _project_file(root, file) is not None
        }
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
        version=locked.version,
    )


class _FragmentQuote(_AnswerModel):
    start_line: int
    end_line: int
    quote: str


class _FragmentElement(_AnswerModel):
    kind: Literal["person", "external"]
    term: str = Field(min_length=1)
    description: str
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

    def __init__(self, system_name: str) -> None:
        self._system = system_name
        self._instructions = load_c4_prompt("documented").replace(
            "{system}", system_name
        )
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

        def stated(citation: Citation, term: str) -> bool:
            return _quote_in_lines(lines, citation.start_line, citation.end_line, term)

        elements = tuple(
            (
                DocElement(item.kind, item.term, citation, item.description),
                item.citation.quote,
            )
            for item in part.elements
            if (citation := cited(item.citation)) is not None
            and stated(citation, item.term)
        )
        # The prompt names the system itself for its internal parts; any other
        # endpoint must be written in the cited lines, like an element term.
        relations = tuple(
            (
                DocRelation(item.from_term, item.to_term, item.title, citation),
                item.citation.quote,
            )
            for item in part.relations
            if (citation := cited(item.citation)) is not None
            and all(
                term == self._system or stated(citation, term)
                for term in (item.from_term, item.to_term)
            )
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
                {
                    "kind": e.kind,
                    "term": e.term,
                    "description": e.description,
                    "citation": quote(e.citation, q),
                }
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
            if isinstance(exc, AnswerRejectedError):
                raise UnreadableAnswerError(rejection_rule(exc)) from exc
            translated = translate_call_error(
                exc, lambda error: isinstance(error, TransientStepError)
            )
            if translated is None:
                raise
            raise translated from exc

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
    system_name: str,
    locked: LockedDocumented | None,
    llm: C4Llm,
    retries: RetryQueue,
    order_hint: Callable[[Fragment], float] | None = None,
) -> DocumentedOutcome:
    """Bounded, resumable extraction over fragments of every selected document.

    Unchanged sets reuse the lock without a call. Otherwise every fragment gets
    a valid outcome (cached, new or recovered) or falls back per fragment. Another
    prompt, schema or validator also counts as changed.
    """
    # A trial only hashes bytes, so it does not require decodable sources.
    sources: dict[str, SourceVersion] = {
        file: read_source(project_root, file, strict=not llm.trial)
        for file in sorted(set(doc_files))
    }
    hashes = {file: source.sha256 for file, source in sources.items()}
    goal = _DocumentedGoal(system_name)
    if locked is not None and locked.hashes == hashes:
        if locked.version == goal.version or llm.trial:
            return _previous_outcome(locked, hashes, project_root, fallback=False)
    if not sources:
        return DocumentedOutcome([], [], hashes, False, version=goal.version)
    if llm.trial:
        return _previous_outcome(locked, hashes, project_root, fallback=False)

    if locked is None:
        reason = "no stored outcome"
    elif locked.hashes == hashes:
        reason = "documentation step changed"
    else:
        added = len(hashes.keys() - locked.hashes.keys())
        removed = len(locked.hashes.keys() - hashes.keys())
        changed = sum(
            hashes[file] != locked.hashes[file]
            for file in hashes.keys() & locked.hashes.keys()
        )
        reason = f"documentation set changed (+{added}/-{removed}/~{changed})"
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
    store = documented_store(project_root, read_only=False)
    call = _C4Call(llm)
    provider = llm.provider_identity("utility")

    def on_attempt(record: AttemptRecord) -> None:
        if record.outcome == "accepted":
            report.record("accepted")
        elif record.outcome == "transient":
            report.record("transient error")
        else:
            report.record(f"rejected ({public_rule(record.rule)})")

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
        [],
        [],
        hashes,
        False,
        counts=counts,
        fragment_total=len(fragments),
        version=goal.version,
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
        f"C4 documented bundles: {docs.counts.reused} reused, "
        f"{docs.counts.new} new, {docs.counts.split} split, "
        f"{docs.fallback_bundles} fell back; fragments "
        f"{docs.fragment_total - failed} covered, {failed} fell back"
    ]
