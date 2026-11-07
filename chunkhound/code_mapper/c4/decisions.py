"""Closed, source-backed C4 decisions with per-item reuse and bounded requests."""

import hashlib
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Generic, Literal, Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from chunkhound.code_mapper.c4.documented import (
    EXTRACTION_CACHE,
    DocElement,
    DocumentedOutcome,
)
from chunkhound.code_mapper.c4.llm import (
    AnswerRejectedError,
    C4Llm,
    RetryQueue,
    StepReport,
    TransientStepError,
    load_c4_prompt,
)
from chunkhound.services.extraction.budget import (
    effective_target,
    fits,
    measure_request,
)
from chunkhound.services.extraction.store import (
    DECISION_FORMAT_VERSION,
    DecisionStore,
    key_from_parts,
)

SubjectT = TypeVar("SubjectT", contravariant=True)
_VALIDATOR_VERSION = 1


class DecisionValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    value: str


class DecisionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[DecisionValue]


@dataclass
class DecisionCounts:
    total: int = 0
    reused: int = 0
    new: int = 0
    fallback: int = 0
    trial: int = 0


@dataclass
class DecisionResults:
    values: dict[str, str] = field(default_factory=dict)
    counts: DecisionCounts = field(default_factory=DecisionCounts)


class DecisionQuestion(Protocol[SubjectT]):
    name: str
    version: str
    values: frozenset[str]

    def item(self, subject: SubjectT) -> dict[str, Any]: ...

    def validate(
        self,
        answer: DecisionAnswer,
        items: Mapping[str, SubjectT],
        *,
        cached: bool = False,
    ) -> dict[str, str]: ...

    def fallback(self, subject: SubjectT) -> str: ...


class ElementQuestion:
    name = "c4_element"
    values = frozenset({"external", "person", "neither"})

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        schema = json.dumps(DecisionAnswer.model_json_schema(), sort_keys=True)
        prompt = load_c4_prompt("element")
        self.version = hashlib.sha256(
            f"{prompt}\n{schema}\n{_VALIDATOR_VERSION}".encode()
        ).hexdigest()

    def item(self, subject: DocElement) -> dict[str, Any]:
        citation = subject.citation
        lines = (
            (self.project_root / citation.file)
            .read_text(encoding="utf-8", errors="replace")
            .splitlines()
        )
        return {
            "term": subject.term,
            "description": subject.description,
            "citation": {
                "file": citation.file,
                "start_line": citation.start_line,
                "end_line": citation.end_line,
                "quote": "\n".join(lines[citation.start_line - 1 : citation.end_line]),
            },
        }

    def validate(
        self,
        answer: DecisionAnswer,
        items: Mapping[str, DocElement],
        *,
        cached: bool = False,
    ) -> dict[str, str]:
        counts = Counter(value.id for value in answer.decisions)
        if counts != Counter({key: 1 for key in items}):
            raise AnswerRejectedError("decide: every item id must occur exactly once")
        if any(value.value not in self.values for value in answer.decisions):
            raise AnswerRejectedError("decide: invalid decision value")
        return {value.id: value.value for value in answer.decisions}

    def fallback(self, subject: DocElement) -> str:
        return subject.kind


def _store(project_root: Path, *, read_only: bool) -> DecisionStore:
    return DecisionStore(
        project_root / EXTRACTION_CACHE / "decisions", read_only=read_only
    )


def prune_decision_cache(project_root: Path) -> None:
    _store(project_root, read_only=False).prune()


@dataclass
class _DecisionRun(Generic[SubjectT]):
    question: DecisionQuestion[SubjectT]
    subjects: Mapping[str, SubjectT]
    llm: C4Llm
    retries: RetryQueue
    step: Literal["decide", "consolidate"]
    store: DecisionStore
    parts: dict[str, dict[str, Any]]
    result: DecisionResults

    def cached(self, key: str) -> bool:
        stored = self.store.get(self.question.name, self.parts[key])
        if stored is None:
            return False
        try:
            checked = self.question.validate(
                DecisionAnswer.model_validate(stored),
                {key: self.subjects[key]},
                cached=True,
            )
        except (ValidationError, AnswerRejectedError):
            return False
        self.result.values.update(checked)
        self.result.counts.reused += 1
        self.store.touch(self.question.name, key_from_parts(self.parts[key]))
        return True

    def misses(self) -> list[str]:
        missing = []
        for key in sorted(self.subjects):
            if self.cached(key):
                continue
            if self.llm.trial:
                self.result.values[key] = self.question.fallback(self.subjects[key])
                self.result.counts.trial += 1
            else:
                missing.append(key)
        seed = hashlib.sha256(json.dumps(sorted(self.subjects)).encode()).hexdigest()
        random.Random(seed).shuffle(missing)
        return missing

    def prompt(self, keys: Sequence[str]) -> str:
        template = load_c4_prompt(self.question.name.removeprefix("c4_"))
        header = (
            f"C4 step: {self.step}\nC4 question: {self.question.name}\n"
            f"{template}\nItems:\n"
        )
        items = [
            {"id": f"I{number}", **self.parts[key]["item"]}
            for number, key in enumerate(keys, 1)
        ]
        return header + json.dumps(items, ensure_ascii=False)

    def bounded(self, keys: Sequence[str]) -> bool:
        prompt = self.prompt(keys)
        schema = DecisionAnswer.model_json_schema()
        limit = self.llm.input_limit("utility")
        return measure_request(prompt, schema, []) <= effective_target(limit) and fits(
            prompt, schema, limit, self.llm.estimate_tokens
        )

    def bundles(self, missing: Sequence[str]) -> list[tuple[list[str], bool]]:
        bundles: list[tuple[list[str], bool]] = []
        current: list[str] = []
        for key in missing:
            if not self.bounded([key]):
                bundles.append(([key], False))
            elif current and not self.bounded([*current, key]):
                bundles.append((current, True))
                current = [key]
            else:
                current.append(key)
        if current:
            bundles.append((current, True))
        return bundles

    async def bundle(
        self,
        keys: Sequence[str],
        prompt: str | None,
        report: StepReport,
    ) -> None:
        """Each call owns its retry closure; no loop-bound bundle state."""
        ids = {f"I{number}": key for number, key in enumerate(keys, 1)}
        local = {short: self.subjects[key] for short, key in ids.items()}

        async def attempt() -> dict[str, str]:
            with report.attempt():
                if prompt is None:
                    raise TransientStepError(f"{self.step}: item exceeds input budget")
                answer = await self.llm.call(
                    self.step, DecisionAnswer, prompt, provider="utility"
                )
                checked = self.question.validate(answer, local)
                return {ids[short]: value for short, value in checked.items()}

        def fallback() -> dict[str, str]:
            return {key: self.question.fallback(self.subjects[key]) for key in keys}

        def apply(values: dict[str, str], failed: bool) -> None:
            self.result.values.update(values)
            if failed:
                self.result.counts.fallback += len(values)
                return
            # Validate the entire bundle before committing any individual answer.
            for key, value in values.items():
                answer = DecisionAnswer(decisions=[DecisionValue(id=key, value=value)])
                self.store.put(self.question.name, self.parts[key], answer.model_dump())
            self.result.counts.new += len(values)

        try:
            apply(await attempt(), False)
        except TransientStepError:
            bundle_key = key_from_parts({"subjects": sorted(keys)})
            self.retries.defer(
                f"{self.step}:{self.question.name}:{bundle_key}",
                attempt,
                fallback,
                apply,
                report=report,
            )


async def run_decisions(
    question: DecisionQuestion[SubjectT],
    subjects: Mapping[str, SubjectT],
    *,
    project_root: Path,
    llm: C4Llm,
    retries: RetryQueue,
    step: Literal["decide", "consolidate"],
    reason: str,
) -> DecisionResults:
    """Return final decisions only after all delayed bundle retries settle."""
    provider = asdict(llm.provider_identity("utility"))
    parts = {
        key: {
            "format": DECISION_FORMAT_VERSION,
            "question": question.name,
            "question_version": question.version,
            "provider": provider,
            "item": question.item(subject),
        }
        for key, subject in subjects.items()
    }
    run = _DecisionRun(
        question,
        subjects,
        llm,
        retries,
        step,
        _store(project_root, read_only=llm.trial),
        parts,
        DecisionResults(counts=DecisionCounts(total=len(subjects))),
    )
    for keys, bounded in run.bundles(run.misses()):
        detail = reason if bounded else f"{reason} (item exceeds input budget)"
        await run.bundle(
            keys, run.prompt(keys) if bounded else None, llm.report(step, detail)
        )
    await retries.drain()
    return run.result


@dataclass
class DecisionOutcome:
    documented: DocumentedOutcome
    added: list[DocElement]
    kinds: dict[str, str]
    dropped: list[str]
    report_lines: tuple[str, ...]


async def decide(
    *,
    project_root: Path,
    doc_files: Sequence[str],
    system_name: str,
    documented: DocumentedOutcome,
    llm: C4Llm,
    retries: RetryQueue,
) -> DecisionOutcome:
    question = ElementQuestion(project_root)
    # The source identity excludes the suggested kind and extraction list order.
    subjects = {
        key_from_parts(question.item(item)): item
        for item in documented.elements
        if item.kind in {"external", "person"}
    }
    result = await run_decisions(
        question,
        subjects,
        project_root=project_root,
        llm=llm,
        retries=retries,
        step="decide",
        reason="elements",
    )
    elements = []
    dropped = []
    changed = []
    for item in documented.elements:
        if item.kind not in {"external", "person"}:
            elements.append(item)
            continue
        value = result.values[key_from_parts(question.item(item))]
        if value == "neither":
            dropped.append(item.term)
        else:
            elements.append(
                replace(item, kind=cast(Literal["external", "person"], value))
            )
            if value != item.kind:
                changed.append(f"{item.term} → {value}")
    counts = result.counts
    line = (
        f"C4 decisions: elements {counts.total} ({counts.reused} reused, "
        f"{counts.new} new, {counts.fallback} fallback, {counts.trial} trial), "
        f"{len(dropped)} dropped ({', '.join(dropped)}), "
        f"{len(changed)} kind changed ({', '.join(changed)})"
    )
    return DecisionOutcome(
        replace(documented, elements=elements, relations=list(documented.relations)),
        [],
        result.values,
        dropped,
        (line,),
    )
