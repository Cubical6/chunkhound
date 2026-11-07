"""Closed, source-backed C4 decisions with per-item reuse and bounded requests."""

import hashlib
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Literal, Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from chunkhound.code_mapper.c4.curation import CurationState
from chunkhound.code_mapper.c4.documented import (
    EXTRACTION_CACHE,
    DocElement,
    DocRelation,
    DocumentedOutcome,
)
from chunkhound.code_mapper.c4.identity import element_id
from chunkhound.code_mapper.c4.llm import (
    AnswerRejectedError,
    C4Llm,
    RetryQueue,
    StepReport,
    TransientStepError,
    load_c4_prompt,
)
from chunkhound.code_mapper.c4.model import Citation
from chunkhound.code_mapper.c4.tables import ServiceTable, TableRow, read_tables
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

if TYPE_CHECKING:
    from chunkhound.code_mapper.c4.consolidation import MergeGroup

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

    def prompt_item(self, item: dict[str, Any]) -> dict[str, Any]: ...

    def validate(
        self,
        answer: DecisionAnswer,
        items: Mapping[str, SubjectT],
        *,
        cached: bool = False,
    ) -> dict[str, str]: ...

    def fallback(self, subject: SubjectT) -> str: ...


class _ChoiceQuestion(Generic[SubjectT]):
    name: str
    values: frozenset[str]

    def __init__(self) -> None:
        schema = json.dumps(DecisionAnswer.model_json_schema(), sort_keys=True)
        prompt = load_c4_prompt(self.name.removeprefix("c4_"))
        self.version = hashlib.sha256(
            f"{prompt}\n{schema}\n{_VALIDATOR_VERSION}".encode()
        ).hexdigest()

    def prompt_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return item

    def validate(
        self,
        answer: DecisionAnswer,
        items: Mapping[str, SubjectT],
        *,
        cached: bool = False,
    ) -> dict[str, str]:
        counts = Counter(value.id for value in answer.decisions)
        if counts != Counter({key: 1 for key in items}):
            raise AnswerRejectedError("decide: every item id must occur exactly once")
        if any(value.value not in self.values for value in answer.decisions):
            raise AnswerRejectedError("decide: invalid decision value")
        return {value.id: value.value for value in answer.decisions}


class ElementQuestion(_ChoiceQuestion[DocElement]):
    name = "c4_element"
    values = frozenset({"external", "person", "neither"})

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        super().__init__()

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

    def fallback(self, subject: DocElement) -> str:
        return subject.kind


class TableQuestion(_ChoiceQuestion[ServiceTable]):
    name = "c4_table"
    values = frozenset({"service_list", "other"})

    def item(self, subject: ServiceTable) -> dict[str, Any]:
        return {
            "path": subject.path,
            "headings": list(subject.headings),
            "header": list(subject.header),
            "rows": [row.raw for row in subject.rows[:3]],
        }

    def fallback(self, subject: ServiceTable) -> str:
        return "other"


class RowQuestion(_ChoiceQuestion[tuple[ServiceTable, TableRow]]):
    name = "c4_row"
    values = frozenset({"external", "person", "neither"})

    def item(self, subject: tuple[ServiceTable, TableRow]) -> dict[str, Any]:
        table, row = subject
        return {
            "path": table.path,
            "headings": list(table.headings),
            "header": list(table.header),
            "row": row.raw,
        }

    def fallback(self, subject: tuple[ServiceTable, TableRow]) -> str:
        return "neither"


def candidate_metadata(
    state: CurationState, project_root: Path
) -> dict[str, dict[str, Any]]:
    """Minimal actor evidence: a document quote or package and first code site."""
    result = {}
    for id, element in sorted(state.elements.items()):
        if element.kind not in {"person", "external"}:
            continue
        source: dict[str, Any] = {}
        citations = sorted(
            (c for c in state.citations if c.target == id),
            key=lambda c: (c.source != "documentation", c.file, c.start_line),
        )
        if citations and citations[0].source == "documentation":
            citation = citations[0]
            lines = (
                (project_root / citation.file)
                .read_text(encoding="utf-8", errors="replace")
                .splitlines()
            )
            source = {
                "file": citation.file,
                "start_line": citation.start_line,
                "end_line": citation.end_line,
                "quote": "\n".join(lines[citation.start_line - 1 : citation.end_line]),
            }
        else:
            sites = sorted(
                (
                    r
                    for r in state.references
                    if r.relation in state.relations
                    and state.relations[r.relation].to_id == id
                ),
                key=lambda r: (r.from_file, r.line, r.to),
            )
            if sites:
                source = {
                    "package": sites[0].to,
                    "file": sites[0].from_file,
                    "line": sites[0].line,
                }
        result[id] = {
            "id": id,
            "name": element.name,
            "description": element.description or "",
            "source": source,
        }
    return result


class SurvivorQuestion(_ChoiceQuestion["MergeGroup"]):
    name = "c4_survivor"
    values = frozenset[str]()

    def __init__(self, candidates: Mapping[str, dict[str, Any]]) -> None:
        self.candidates = candidates
        super().__init__()

    def item(self, subject: "MergeGroup") -> dict[str, Any]:
        return {
            "members": [
                {key: self.candidates[id][key] for key in ("id", "name", "description")}
                for id in sorted(subject.members)
            ]
        }

    def prompt_item(self, item: dict[str, Any]) -> dict[str, Any]:
        members = [
            {**member, "id": f"M{number}"}
            for number, member in enumerate(item["members"], 1)
        ]
        seed = key_from_parts(item)
        random.Random(seed).shuffle(members)
        return {"members": members}

    def validate(
        self,
        answer: DecisionAnswer,
        items: Mapping[str, "MergeGroup"],
        *,
        cached: bool = False,
    ) -> dict[str, str]:
        if Counter(v.id for v in answer.decisions) != Counter({k: 1 for k in items}):
            raise AnswerRejectedError(
                "consolidate: every item id must occur exactly once"
            )
        checked = {}
        for value in answer.decisions:
            members = sorted(items[value.id].members)
            aliases = {f"M{n}": id for n, id in enumerate(members, 1)}
            real = value.value if cached else aliases.get(value.value, "")
            if real not in members or real not in self.candidates:
                raise AnswerRejectedError("consolidate: survivor outside its group")
            checked[value.id] = real
        return checked

    def fallback(self, subject: "MergeGroup") -> str:
        return ""


class PairQuestion(_ChoiceQuestion[tuple[str, str]]):
    name = "c4_pair"
    values = frozenset({"same", "different", "unsure"})

    def __init__(self, candidates: Mapping[str, dict[str, Any]]) -> None:
        self.candidates = candidates
        super().__init__()

    def item(self, subject: tuple[str, str]) -> dict[str, Any]:
        survivor, other = subject
        return {"survivor": self.candidates[survivor], "other": self.candidates[other]}

    def prompt_item(self, item: dict[str, Any]) -> dict[str, Any]:
        aliases = {
            id: f"M{n}"
            for n, id in enumerate(
                sorted((item["survivor"]["id"], item["other"]["id"])), 1
            )
        }
        return {
            role: {**member, "id": aliases[member["id"]]}
            for role, member in item.items()
        }

    def fallback(self, subject: tuple[str, str]) -> str:
        return "different"


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
            {"id": f"I{number}", **self.question.prompt_item(self.parts[key]["item"])}
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


async def _decide_rows(
    project_root: Path, doc_files: Sequence[str], llm: C4Llm, retries: RetryQueue
) -> tuple[DecisionResults, DecisionResults, dict[str, tuple[ServiceTable, TableRow]]]:
    table_question = TableQuestion()
    source_tables = read_tables(project_root, doc_files)
    tables = {
        key_from_parts(table_question.item(table)): table for table in source_tables
    }
    selected = await run_decisions(
        table_question,
        tables,
        project_root=project_root,
        llm=llm,
        retries=retries,
        step="decide",
        reason="tables",
    )
    row_question = RowQuestion()
    rows = {
        key_from_parts(row_question.item((table, row))): (table, row)
        for table in source_tables
        if selected.values[key_from_parts(table_question.item(table))] == "service_list"
        for row in table.rows
    }
    classified = await run_decisions(
        row_question,
        rows,
        project_root=project_root,
        llm=llm,
        retries=retries,
        step="decide",
        reason="rows",
    )
    return selected, classified, rows


def _add_rows(
    elements: list[DocElement],
    relations: list[DocRelation],
    subjects: Mapping[str, tuple[ServiceTable, TableRow]],
    values: Mapping[str, str],
    system_name: str,
) -> list[DocElement]:
    seen = {element_id(item.kind, item.term) for item in elements}
    added = []
    for key, (table, row) in subjects.items():
        value = values[key]
        term = row.cells[0] if row.cells else ""
        if value == "neither" or not term:
            continue
        kind = cast(Literal["external", "person"], value)
        identity = element_id(kind, term)
        if identity in seen:
            continue
        seen.add(identity)
        citation = Citation(
            target=None,
            file=table.path,
            start_line=row.line,
            end_line=row.line,
            source="documentation",
            verified=True,
        )
        added.append(DocElement(kind, term, citation))
        source, target = (
            (system_name, term) if kind == "external" else (term, system_name)
        )
        relations.append(DocRelation(source, target, "uses", citation))
    elements.extend(added)
    return added


def _count_summary(counts: DecisionCounts) -> str:
    return (
        f"{counts.total} ({counts.reused} reused, {counts.new} new, "
        f"{counts.fallback} fallback, {counts.trial} trial)"
    )


async def decide(
    *,
    project_root: Path,
    doc_files: Sequence[str],
    system_name: str,
    documented: DocumentedOutcome,
    llm: C4Llm,
    retries: RetryQueue,
) -> DecisionOutcome:
    tables, rows, row_subjects = await _decide_rows(
        project_root, doc_files, llm, retries
    )
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
    relations = list(documented.relations)
    added = _add_rows(elements, relations, row_subjects, rows.values, system_name)
    added_names = []
    for item in added:
        citation = item.citation
        span = str(citation.start_line)
        if citation.end_line != citation.start_line:
            span += f"-{citation.end_line}"
        added_names.append(f"{item.term} ({citation.file}:{span})")
    service_count = sum(value == "service_list" for value in tables.values.values())
    line = (
        f"C4 decisions: tables {_count_summary(tables.counts)}, "
        f"{service_count} service tables; rows {_count_summary(rows.counts)}, "
        f"{len(added)} added ({', '.join(added_names)}); "
        f"elements {_count_summary(result.counts)}, "
        f"{len(dropped)} dropped ({', '.join(dropped)}), "
        f"{len(changed)} kind changed ({', '.join(changed)})"
    )
    return DecisionOutcome(
        replace(documented, elements=elements, relations=relations),
        added,
        result.values,
        dropped,
        (line,),
    )
