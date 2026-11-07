"""Propose actor groups, verify each pair, and respect symmetric separation rules."""

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from chunkhound.code_mapper.c4.curation import CurationState
from chunkhound.code_mapper.c4.decisions import (
    DecisionCounts,
    PairQuestion,
    SurvivorQuestion,
    _count_summary,
    candidate_metadata,
    run_decisions,
)
from chunkhound.code_mapper.c4.documented import EXTRACTION_CACHE
from chunkhound.code_mapper.c4.llm import (
    AnswerRejectedError,
    C4Llm,
    RetryQueue,
    TransientStepError,
    load_c4_prompt,
)
from chunkhound.code_mapper.c4.model import Overrides
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

_VALIDATOR_VERSION = 1


@dataclass(frozen=True)
class MergeGroup:
    kind: Literal["person", "external"]
    members: tuple[str, ...]
    survivor: str | None = None


@dataclass(frozen=True)
class ConsolidationOutcome:
    merges: dict[str, str]
    report_lines: tuple[str, ...]


class GroupMembers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    members: list[str]


class GroupAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    groups: list[GroupMembers]


def _validate_groups(
    answer: GroupAnswer,
    members: dict[str, dict[str, Any]],
    aliases: dict[str, str],
    *,
    cached: bool,
) -> GroupAnswer:
    seen: set[str] = set()
    groups = []
    for group in answer.groups:
        real = []
        for member in group.members:
            id = member if cached else aliases.get(member, "")
            if id not in members:
                raise AnswerRejectedError("consolidate: group mixes kinds")
            if id in seen:
                raise AnswerRejectedError("consolidate: id in more than one group")
            seen.add(id)
            real.append(id)
        groups.append(GroupMembers(members=sorted(real)))
    return GroupAnswer(groups=groups)


async def _propose_groups(
    *,
    state: CurationState,
    kind: Literal["person", "external"],
    project_root: Path,
    llm: C4Llm,
    retries: RetryQueue,
) -> tuple[list[MergeGroup], DecisionCounts]:
    """One indivisible, independently cached proposal for each actor kind."""
    candidates = candidate_metadata(state, project_root)
    members = {
        id: item for id, item in candidates.items() if state.elements[id].kind == kind
    }
    counts = DecisionCounts(total=int(bool(members)))
    if not members:
        return [], counts
    template = load_c4_prompt("group")
    schema = GroupAnswer.model_json_schema()
    schema_text = json.dumps(schema, sort_keys=True)
    version = hashlib.sha256(
        f"{template}\n{schema_text}\n{_VALIDATOR_VERSION}".encode()
    ).hexdigest()
    parts = {
        "format": DECISION_FORMAT_VERSION,
        "question": "c4_group",
        "question_version": version,
        "provider": asdict(llm.provider_identity("utility")),
        "item": {"kind": kind, "members": list(members.values())},
    }
    store = DecisionStore(
        project_root / EXTRACTION_CACHE / "decisions", read_only=llm.trial
    )
    aliases = {f"M{number}": id for number, id in enumerate(members, 1)}
    stored = store.get("c4_group", parts)
    if stored is not None:
        try:
            checked = _validate_groups(
                GroupAnswer.model_validate(stored), members, aliases, cached=True
            )
        except (ValidationError, AnswerRejectedError):
            pass
        else:
            store.touch("c4_group", key_from_parts(parts))
            counts.reused = 1
            return [
                MergeGroup(kind, tuple(g.members))
                for g in checked.groups
                if len(g.members) > 1
            ], counts
    if llm.trial:
        counts.trial = 1
        counts.fallback = 1
        return [], counts
    prompt_members = [{**members[id], "id": short} for short, id in aliases.items()]
    random.Random(key_from_parts(parts)).shuffle(prompt_members)
    item = {"id": "I1", "kind": kind, "members": prompt_members}
    prompt = f"C4 step: consolidate\nC4 question: c4_group\n{template}\nItems:\n"
    prompt += json.dumps([item], ensure_ascii=False)
    limit = llm.input_limit("utility")
    bounded = measure_request(prompt, schema, []) <= effective_target(limit) and fits(
        prompt, schema, limit, llm.estimate_tokens
    )
    report = llm.report(
        "consolidate",
        "groups" if bounded else f"groups ({kind} item exceeds input budget)",
    )
    result: list[MergeGroup] = []

    async def attempt() -> GroupAnswer:
        with report.attempt():
            if not bounded:
                raise TransientStepError("consolidate: item exceeds input budget")
            answer = await llm.call(
                "consolidate", GroupAnswer, prompt, provider="utility"
            )
            return _validate_groups(answer, members, aliases, cached=False)

    def apply(answer: GroupAnswer, failed: bool) -> None:
        if not failed:
            store.put("c4_group", parts, answer.model_dump())
            counts.new = 1
        else:
            counts.fallback = 1
        result.extend(
            MergeGroup(kind, tuple(g.members))
            for g in answer.groups
            if len(g.members) > 1
        )

    try:
        apply(await attempt(), False)
    except TransientStepError:
        retries.defer(
            f"consolidate:c4_group:{key_from_parts(parts)}",
            attempt,
            lambda: GroupAnswer(groups=[]),
            apply,
            report=report,
        )
    await retries.drain()
    return result, counts


async def propose_groups(
    *,
    state: CurationState,
    kind: Literal["person", "external"],
    project_root: Path,
    llm: C4Llm,
    retries: RetryQueue,
) -> list[MergeGroup]:
    groups, _ = await _propose_groups(
        state=state,
        kind=kind,
        project_root=project_root,
        llm=llm,
        retries=retries,
    )
    return groups


def _separations(
    state: CurationState, overrides: Overrides
) -> tuple[set[tuple[str, str]], list[str]]:
    pairs = set()
    notes = []
    for a, b in sorted({tuple(sorted(pair)) for pair in overrides.keep_apart}):
        reason = None
        if a not in state.elements or b not in state.elements:
            reason = "not on the map"
        elif any(
            state.elements[id].kind not in {"person", "external"} for id in (a, b)
        ):
            reason = "not an external system or person"
        if reason:
            notes.append(f"C4-overrides: keep_apart ignored for {a}, {b} ({reason})")
        else:
            pairs.add((a, b))
    return pairs, notes


def _block_shared_targets(
    merges: dict[str, str],
    pairs: set[tuple[str, str]],
    state: CurationState,
) -> list[str]:
    notes = []
    for a, b in sorted(pairs):
        if a == b or merges.get(a, a) != merges.get(b, b):
            continue
        target = merges.get(a, a)
        blocked = b if a == target else a if b == target else max(a, b)
        merges.pop(blocked, None)
        notes.append(
            f"C4 consolidation: kept apart {state.elements[a].name}, "
            f"{state.elements[b].name} (keep_apart)"
        )
    return notes


def _comparisons(
    subjects: dict[str, MergeGroup],
    survivors: dict[str, str],
) -> dict[str, tuple[str, str]]:
    comparisons = {}
    for key, group in subjects.items():
        survivor = survivors[key]
        if survivor:
            for other in group.members:
                if other != survivor:
                    parts = {"survivor": survivor, "other": other}
                    comparisons[key_from_parts(parts)] = (survivor, other)
    return comparisons


def _decision_notes(
    subjects: dict[str, MergeGroup],
    survivors: dict[str, str],
    comparisons: dict[str, tuple[str, str]],
    values: dict[str, str],
    state: CurationState,
) -> list[str]:
    notes = []
    for key, group in subjects.items():
        if not survivors[key]:
            names = ", ".join(state.elements[id].name for id in group.members)
            notes.append(f"C4 consolidation: kept apart {names} (no survivor decision)")
    for key, (survivor, other) in comparisons.items():
        if values[key] != "same":
            notes.append(
                f"C4 consolidation: kept apart {state.elements[survivor].name}, "
                f"{state.elements[other].name} ({values[key]})"
            )
    return notes


async def consolidate(
    *,
    state: CurationState,
    overrides: Overrides,
    project_root: Path,
    llm: C4Llm,
    retries: RetryQueue,
) -> ConsolidationOutcome:
    pairs, notes = _separations(state, overrides)
    groups = []
    group_counts = DecisionCounts()
    kinds: tuple[Literal["person", "external"], ...] = ("person", "external")
    for kind in kinds:
        proposed, counts = await _propose_groups(
            state=state,
            kind=kind,
            project_root=project_root,
            llm=llm,
            retries=retries,
        )
        group_counts.total += counts.total
        group_counts.reused += counts.reused
        group_counts.new += counts.new
        group_counts.fallback += counts.fallback
        group_counts.trial += counts.trial
        for group in proposed:
            if len(group.members) == 2 and tuple(sorted(group.members)) in pairs:
                a, b = group.members
                notes.append(
                    f"C4 consolidation: kept apart {state.elements[a].name}, "
                    f"{state.elements[b].name} (keep_apart)"
                )
            else:
                groups.append(group)
    metadata = candidate_metadata(state, project_root)
    subjects = {
        key_from_parts({"kind": g.kind, "members": sorted(g.members)}): g
        for g in groups
    }
    survivors = await run_decisions(
        SurvivorQuestion(metadata),
        subjects,
        project_root=project_root,
        llm=llm,
        retries=retries,
        step="consolidate",
        reason="survivors",
    )
    comparisons = _comparisons(subjects, survivors.values)
    decisions = await run_decisions(
        PairQuestion(metadata),
        comparisons,
        project_root=project_root,
        llm=llm,
        retries=retries,
        step="consolidate",
        reason="pairs",
    )
    notes.extend(
        _decision_notes(
            subjects, survivors.values, comparisons, decisions.values, state
        )
    )
    merges = {
        other: survivor
        for key, (survivor, other) in comparisons.items()
        if decisions.values[key] == "same"
    }
    notes.extend(_block_shared_targets(merges, pairs, state))
    changes = (
        ", ".join(
            f"{state.elements[a].name} → {state.elements[b].name}"
            for a, b in sorted(merges.items())
        )
        or "none"
    )
    apart = sum(value in {"different", "unsure"} for value in decisions.values.values())
    line = (
        f"C4 consolidation: groups {_count_summary(group_counts)}; merged: {changes}; "
        f"{apart} kept apart (different/unsure); "
        f"survivors {_count_summary(survivors.counts)}; "
        f"pairs {_count_summary(decisions.counts)}" + ("; trial" if llm.trial else "")
    )
    reports = tuple(
        line for line in llm.report_lines() if line.startswith("C4 consolidate:")
    )
    return ConsolidationOutcome(merges, (line, *notes, *reports))
