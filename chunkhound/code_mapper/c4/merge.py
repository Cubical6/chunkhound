"""Whole-group component proposals and evidence-constrained relation titles."""

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace

from pydantic import BaseModel, ConfigDict, Field

from chunkhound.code_mapper.c4.grouping import Group
from chunkhound.code_mapper.c4.llm import (
    AnswerRejectedError,
    C4Llm,
    RetryQueue,
    TransientStepError,
    load_c4_prompt,
)
from chunkhound.code_mapper.c4.model import LockedComponent, Marker, ReferenceKind
from chunkhound.code_mapper.c4.runtime import RuntimeUnit


@dataclass(frozen=True)
class ProposedComponent:
    key: str
    name: str
    description: str | None
    groups: tuple[str, ...]
    markers: tuple[Marker, ...]


@dataclass
class MergeResult:
    """Deferred operations mutate this result when RetryQueue is drained.

    Keys are proposal-local, not final C4 IDs. Titles use these keys, or the
    container ID for directly contained groups. Identity maps them later.
    """

    components: list[ProposedComponent]
    direct_groups: list[str]
    fallback: bool
    titles: dict[tuple[str, str], str] = field(default_factory=dict)


class _AnswerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class _ComponentAnswer(_AnswerModel):
    name: str = Field(min_length=1)
    description: str | None
    groups: list[str]


class _MergeTitle(_AnswerModel):
    from_id: str = Field(alias="from")
    to_id: str = Field(alias="to")
    title: str = Field(min_length=1)


class MergeAnswer(_AnswerModel):
    components: list[_ComponentAnswer]
    direct: list[str]
    titles: list[_MergeTitle]


class _RelationTitle(_AnswerModel):
    fingerprint: str
    title: str = Field(min_length=1)


class _TitlesAnswer(_AnswerModel):
    titles: list[_RelationTitle]


def relation_fingerprint(
    from_key: str, to_key: str, refs: Iterable[tuple[ReferenceKind, str]]
) -> str:
    """Multiplicity and source locations do not change the cached title."""
    payload = json.dumps([from_key, to_key, sorted(set(refs))], ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def fallback_title(kinds: Iterable[ReferenceKind]) -> str:
    present = set(kinds)
    if "inherit" in present:
        return "erft van"
    if "call" in present:
        return "roept aan"
    return "importeert"


def check_merge_answer(
    answer: MergeAnswer, groups: Sequence[Group], container: str
) -> None:
    """Reject lost, repeated, foreign, invented or empty group placements."""
    placed = [group for item in answer.components for group in item.groups]
    placed.extend(answer.direct)
    expected = Counter(group.id for group in groups)
    if (
        any(group.container != container for group in groups)
        or any(count != 1 for count in expected.values())
        or Counter(placed) != expected
        or any(not item.groups or not item.name.strip() for item in answer.components)
    ):
        raise AnswerRejectedError(
            "merge: every local group must be placed exactly once"
        )


def _proposal_key(container: str, groups: Iterable[str]) -> str:
    payload = json.dumps([container, sorted(groups)], ensure_ascii=True)
    return "proposal:" + hashlib.sha256(payload.encode()).hexdigest()


def _locked_owners(
    container: str, existing: Mapping[str, LockedComponent]
) -> dict[str, str]:
    owners: dict[str, str] = {}
    for key, item in existing.items():
        if item.container != container:
            continue
        for group in item.groups:
            if group in owners and owners[group] != key:
                raise ValueError(f"merge: conflicting locked placement for {group}")
            owners[group] = key
    return owners


def _known_components(
    container: str,
    groups: Sequence[Group],
    existing: Mapping[str, LockedComponent],
    placements: Mapping[str, str],
) -> tuple[list[ProposedComponent], list[Group]]:
    owners = _locked_owners(container, existing)
    assigned: dict[str, list[str]] = {}
    pending = []
    for group in groups:
        if group.container != container:
            raise ValueError(f"merge: foreign input group {group.id}")
        key = placements.get(group.id, owners.get(group.id))
        if key is None:
            pending.append(group)
            continue
        if key in existing and existing[key].container != container:
            raise ValueError(f"merge: override crosses containers for {group.id}")
        assigned.setdefault(key, []).append(group.id)
    components = []
    for key, ids in sorted(assigned.items()):
        cached = existing.get(key)
        components.append(
            ProposedComponent(
                key,
                cached.name if cached else key.removeprefix("component:"),
                cached.description if cached else None,
                tuple(sorted(ids)),
                (),
            )
        )
    return components, pending


def _default_merge(container: str, groups: Sequence[Group], trial: bool) -> MergeResult:
    marker: Marker = "trial" if trial else "fallback"
    return MergeResult(
        [
            ProposedComponent(
                _proposal_key(container, [group.id]),
                group.name,
                None,
                (group.id,),
                (marker, "not_merged", "provisional"),
            )
            for group in sorted(groups, key=lambda group: group.id)
        ],
        [],
        not trial,
    )


def _propose_components(
    answer: MergeAnswer, container: str, known: Sequence[ProposedComponent]
) -> list[ProposedComponent]:
    result = {item.key: item for item in known}
    used_names: set[str] = set()
    for item in answer.components:
        matches = [cached for cached in known if cached.name == item.name]
        if len(matches) > 1 or item.name in used_names:
            raise AnswerRejectedError("merge: ambiguous component name")
        used_names.add(item.name)
        if matches:
            cached = matches[0]
            result[cached.key] = replace(
                cached, groups=tuple(sorted((*cached.groups, *item.groups)))
            )
        else:
            key = _proposal_key(container, item.groups)
            result[key] = ProposedComponent(
                key, item.name, item.description, tuple(sorted(item.groups)), ()
            )
    return sorted(result.values(), key=lambda item: item.key)


def _merge_titles(
    answer: MergeAnswer,
    result: MergeResult,
    container: str,
    group_links: Mapping[tuple[str, str], Counter[ReferenceKind]],
) -> dict[tuple[str, str], str]:
    owners = {group: item.key for item in result.components for group in item.groups}
    owners.update(dict.fromkeys(result.direct_groups, container))
    endpoints = {f"group:{group}": key for group, key in owners.items()}
    endpoints["container"] = container
    endpoints.update(
        {
            f"component:{item.key}": item.key
            for item in result.components
            if not item.key.startswith("proposal:")
        }
    )
    supported = {
        (owners[left], owners[right])
        for (left, right), kinds in group_links.items()
        if left in owners
        and right in owners
        and owners[left] != owners[right]
        and any(count > 0 for count in kinds.values())
    }
    titles = {}
    for row in answer.titles:
        pair = (endpoints.get(row.from_id), endpoints.get(row.to_id))
        if pair not in supported or pair in titles or not row.title.strip():
            raise AnswerRejectedError(
                "merge: unknown, duplicate or unsupported title pair"
            )
        # Membership in supported proves both endpoints are non-null.
        titles[(str(pair[0]), str(pair[1]))] = row.title
    return titles


def _merge_prompt(
    container: RuntimeUnit,
    pending: Sequence[Group],
    known: Sequence[ProposedComponent],
    group_links: Mapping[tuple[str, str], Counter[ReferenceKind]],
) -> str:
    payload = {
        "container": container.id,
        "groups": [
            asdict(group) for group in sorted(pending, key=lambda group: group.id)
        ],
        "existing": [
            {"key": item.key, "name": item.name, "groups": item.groups}
            for item in known
        ],
        "links": [
            {"from": left, "to": right, "kinds": dict(sorted(kinds.items()))}
            for (left, right), kinds in sorted(group_links.items())
        ],
    }
    return load_c4_prompt("merge") + "\nInput:\n" + json.dumps(payload)


async def merge_container(
    *,
    container: RuntimeUnit,
    groups: Sequence[Group],
    group_links: Mapping[tuple[str, str], Counter[ReferenceKind]],
    existing: Mapping[str, LockedComponent],
    placements: Mapping[str, str],
    llm: C4Llm,
    retries: RetryQueue,
) -> MergeResult:
    """Reuse locked groups and overrides; send only unclaimed groups for merging."""
    known, pending = _known_components(container.id, groups, existing, placements)
    result = MergeResult(list(known), [], False)
    if not pending:
        return result

    def apply(value: MergeResult, fallback: bool) -> None:
        result.components = value.components
        result.direct_groups = value.direct_groups
        result.fallback = value.fallback
        result.titles = value.titles

    def default() -> MergeResult:
        value = _default_merge(container.id, pending, llm.trial)
        value.components = [*known, *value.components]
        return value

    if llm.trial:
        apply(default(), False)
        return result
    prompt = _merge_prompt(container, pending, known, group_links)
    report = llm.report(
        "merge",
        f"container {json.dumps(container.id)}: {len(pending)} niet-geclaimde groepen",
    )

    async def attempt() -> MergeResult:
        with report.attempt():
            answer = await llm.call("merge", MergeAnswer, prompt, provider="synthesis")
            check_merge_answer(answer, pending, container.id)
            value = MergeResult(
                _propose_components(answer, container.id, known),
                sorted(answer.direct),
                False,
            )
            value.titles = _merge_titles(answer, value, container.id, group_links)
            return value

    try:
        apply(await attempt(), False)
    except TransientStepError:
        retries.defer(f"merge:{container.id}", attempt, default, apply, report=report)
    return result


async def title_relations(
    *,
    container: str,
    pending: Mapping[str, Counter[ReferenceKind]],
    llm: C4Llm,
    retries: RetryQueue,
) -> dict[str, str]:
    """Title only uncached fingerprints. Drain retries before consuming results.

    The caller owns relation markers/cache exclusion: RetryQueue reports fallback
    operations, while this prescribed mapping contains only fingerprint/title.
    """
    if not pending:
        return {}

    def default() -> dict[str, str]:
        return {
            key: fallback_title(kind for kind, count in kinds.items() if count > 0)
            for key, kinds in pending.items()
        }

    if llm.trial:
        return default()
    prompt = (
        load_c4_prompt("titles")
        + "\nInput:\n"
        + json.dumps(
            {
                "container": container,
                "relations": [
                    {"fingerprint": key, "kinds": dict(sorted(kinds.items()))}
                    for key, kinds in sorted(pending.items())
                ],
            }
        )
    )
    report = llm.report(
        "titles",
        f"container {json.dumps(container)}: "
        f"{len(pending)} nieuwe of gewijzigde relaties",
    )

    async def attempt() -> dict[str, str]:
        with report.attempt():
            answer = await llm.call(
                "titles", _TitlesAnswer, prompt, provider="synthesis"
            )
            if Counter(row.fingerprint for row in answer.titles) != Counter(
                {key: 1 for key in pending}
            ) or any(not row.title.strip() for row in answer.titles):
                raise AnswerRejectedError(
                    "titles: every fingerprint must occur exactly once"
                )
            return {row.fingerprint: row.title for row in answer.titles}

    result: dict[str, str] = {}

    def apply(value: dict[str, str], fallback: bool) -> None:
        result.update(value)

    try:
        apply(await attempt(), False)
    except TransientStepError:
        retries.defer(f"titles:{container}", attempt, default, apply, report=report)
    return result
