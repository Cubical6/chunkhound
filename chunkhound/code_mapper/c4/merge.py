"""Whole-group component proposals and evidence-constrained relation titles."""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import NoReturn

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from chunkhound.code_mapper.c4.grouping import Group
from chunkhound.code_mapper.c4.llm import (
    AnswerRejectedError,
    C4Llm,
    RetryQueue,
    TransientStepError,
    load_c4_prompt,
)
from chunkhound.code_mapper.c4.model import (
    LockedComponent,
    Marker,
    Reference,
    ReferenceKind,
)
from chunkhound.code_mapper.c4.runtime import RuntimeUnit
from chunkhound.code_mapper.service import _is_retryable_poi_error
from chunkhound.core.detection.language_detector import detect_language
from chunkhound.core.types.common import ChunkType, FileId
from chunkhound.parsers.parser_factory import ParserFactory
from chunkhound.services.extraction.budget import fits, measure_request
from chunkhound.services.extraction.errors import (
    ProviderInputRefusedError,
    TransientCallError,
    UnreadableAnswerError,
    translate_call_error,
)

_SYMBOL_KINDS = frozenset(
    {
        ChunkType.CLASS,
        ChunkType.INTERFACE,
        ChunkType.STRUCT,
        ChunkType.ENUM,
        ChunkType.TRAIT,
        ChunkType.FUNCTION,
        ChunkType.TYPE,
        ChunkType.TYPE_ALIAS,
    }
)
_PART_SUFFIX = re.compile(r"(?:_part\d+)+$")


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

    Pending groups have no placement: their files stay on the container for this
    run and nothing about them is locked, so the next run sends them again.
    """

    components: list[ProposedComponent]
    direct_groups: list[str]
    fallback: bool
    titles: dict[tuple[str, str], str] = field(default_factory=dict)
    pending_groups: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    placed_groups: int = 0
    removed_placements: int = 0


class _AnswerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class _ComponentAnswer(_AnswerModel):
    # A blank name or title costs its row, not the whole answer.
    name: str
    description: str | None
    groups: list[str]


class _MergeTitle(_AnswerModel):
    from_id: str = Field(alias="from")
    to_id: str = Field(alias="to")
    title: str


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
    """Multiplicity and source locations do not change the cached title.

    A changed titles prompt does: otherwise the lock would keep the old titles.
    """
    prompt = hashlib.sha256(load_c4_prompt("titles").encode()).hexdigest()
    payload = json.dumps(
        [prompt, from_key, to_key, sorted(set(refs))], ensure_ascii=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def fallback_title(kinds: Iterable[ReferenceKind]) -> str:
    present = set(kinds)
    if "inherit" in present:
        return "erft van"
    if "call" in present:
        return "roept aan"
    return "importeert"


@dataclass(frozen=True)
class _NormalizedAnswer:
    """What one answer places, by new or existing component name."""

    components: dict[str, tuple[str | None, list[str]]]
    direct: list[str]
    leftover: list[Group]
    removed_placements: int


def normalize_merge_answer(
    answer: MergeAnswer,
    pending: Sequence[Group],
    known: Sequence[ProposedComponent],
) -> _NormalizedAnswer:
    """Repair an answer row by row; only one that places nothing is rejected.

    A repeat keeps the first placement in answer order, even if that row then
    turns out unusable: its groups become leftover and get the narrow retry.
    """
    waiting = {group.id for group in pending}
    names = Counter(item.name for item in known)
    seen: set[str] = set()
    removed = 0

    def keep(ids: Iterable[str]) -> list[str]:
        nonlocal removed
        kept = []
        for group in ids:
            if group in waiting and group not in seen:
                seen.add(group)
                kept.append(group)
            else:
                removed += 1
        return kept

    components: dict[str, tuple[str | None, list[str]]] = {}
    for row in answer.components:
        ids = keep(row.groups)
        if ids and row.name.strip() and names[row.name] <= 1:
            description, merged = components.get(row.name, (None, []))
            components[row.name] = (
                description or row.description,
                [*merged, *ids],
            )
    direct = keep(answer.direct)
    placed = {*direct, *(id for _, ids in components.values() for id in ids)}
    if not placed:
        raise AnswerRejectedError("merge: answer places no group")
    return _NormalizedAnswer(
        components,
        direct,
        [group for group in pending if group.id not in placed],
        removed,
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


def _default_merge(container: str, groups: Sequence[Group]) -> MergeResult:
    """Trial runs only: a real failure must not invent components."""
    return MergeResult(
        [
            ProposedComponent(
                _proposal_key(container, [group.id]),
                group.name,
                None,
                (group.id,),
                ("trial", "not_merged", "provisional"),
            )
            for group in sorted(groups, key=lambda group: group.id)
        ],
        [],
        False,
        placed_groups=len(groups),
    )


def _unplaced(
    placed: MergeResult, waiting: Sequence[Group], reason: str
) -> MergeResult:
    """A failed step places nothing new; its groups are sent again next run."""
    return replace(
        placed,
        fallback=True,
        pending_groups=sorted(group.id for group in waiting),
        failure_reason=reason,
    )


def _propose_components(
    answer: _NormalizedAnswer, container: str, known: Sequence[ProposedComponent]
) -> list[ProposedComponent]:
    result = {item.key: item for item in known}
    by_name = {item.name: item for item in known}
    for name, (description, ids) in answer.components.items():
        cached = by_name.get(name)
        if cached is not None:
            result[cached.key] = replace(
                cached, groups=tuple(sorted((*cached.groups, *ids)))
            )
        else:
            key = _proposal_key(container, ids)
            result[key] = ProposedComponent(
                key, name, description, tuple(sorted(ids)), ()
            )
    return sorted(result.values(), key=lambda item: item.key)


def _merge_titles(
    answer: MergeAnswer,
    result: MergeResult,
    container: str,
    group_links: Mapping[tuple[str, str], Counter[ReferenceKind]],
) -> dict[tuple[str, str], str]:
    """An invalid row is dropped; the later titles step fills the gap."""
    owners = {group: item.key for item in result.components for group in item.groups}
    owners.update(dict.fromkeys(result.direct_groups, container))
    endpoints = {f"group:{group}": key for group, key in owners.items()}
    endpoints["container"] = container
    endpoints.update({f"component:{item.key}": item.key for item in result.components})
    supported = {
        (owners[left], owners[right])
        for (left, right), kinds in group_links.items()
        if left in owners
        and right in owners
        and owners[left] != owners[right]
        and any(count > 0 for count in kinds.values())
    }
    titles: dict[tuple[str, str], str] = {}
    for row in answer.titles:
        left, right = endpoints.get(row.from_id), endpoints.get(row.to_id)
        if left is None or right is None or not row.title.strip():
            continue
        if (left, right) in supported:
            titles.setdefault((left, right), row.title)
    return titles


def _apply_answer(
    answer: MergeAnswer,
    normalized: _NormalizedAnswer,
    placed: MergeResult,
    waiting: Sequence[Group],
    container: str,
    group_links: Mapping[tuple[str, str], Counter[ReferenceKind]],
) -> MergeResult:
    """Add one answer to what is placed so far; for the same pair the first wins."""
    value = MergeResult(
        _propose_components(normalized, container, placed.components),
        sorted((*placed.direct_groups, *normalized.direct)),
        False,
        placed_groups=placed.placed_groups + len(waiting) - len(normalized.leftover),
        removed_placements=placed.removed_placements + normalized.removed_placements,
    )
    value.titles = {
        **_merge_titles(answer, value, container, group_links),
        **placed.titles,
    }
    return value


def _raise_sorted(step: str, exc: Exception) -> NoReturn:
    """Raise a provider failure as one of the step's failure kinds, or as fatal."""
    translated = translate_call_error(exc, _is_retryable_poi_error)
    if translated is None:
        raise exc
    if isinstance(translated, UnreadableAnswerError):
        raise AnswerRejectedError(f"{step}: {translated.rule}") from exc
    if isinstance(translated, TransientCallError):
        raise TransientStepError(str(translated)) from exc
    raise translated from exc


async def _ask_merge(llm: C4Llm, prompt: str) -> MergeAnswer:
    """One provider call, with its failures sorted into the step's failure kinds."""
    try:
        return await llm.call(
            "merge",
            MergeAnswer,
            prompt,
            provider="synthesis",
            max_completion_tokens=max(8192, min(32768, len(prompt) // 4)),
        )
    except AnswerRejectedError:
        raise
    except Exception as exc:
        _raise_sorted("merge", exc)


@dataclass(frozen=True)
class _MergeAliases:
    """G<n> and E<n> hold for one call, so the model repeats no long IDs."""

    groups: dict[str, Group]
    components: dict[str, ProposedComponent]

    def group_id(self, alias: str) -> str:
        """A real ID is no alias of this call, so it stays unknown as well."""
        group = self.groups.get(alias)
        return group.id if group else f"unknown:{alias}"

    def endpoint(self, token: str) -> str:
        if token == "container":
            return token
        kind, _, alias = token.partition(":")
        if kind == "group" and alias in self.groups:
            return f"group:{self.groups[alias].id}"
        if kind == "component" and alias in self.components:
            return f"component:{self.components[alias].key}"
        return f"unknown:{token}"

    def translate(self, answer: MergeAnswer) -> MergeAnswer:
        """Back to real IDs, so an unknown alias fails like an unknown group."""
        return MergeAnswer(
            components=[
                row.model_copy(
                    update={"groups": [self.group_id(alias) for alias in row.groups]}
                )
                for row in answer.components
            ],
            direct=[self.group_id(alias) for alias in answer.direct],
            titles=[
                row.model_copy(
                    update={
                        "from_id": self.endpoint(row.from_id),
                        "to_id": self.endpoint(row.to_id),
                    }
                )
                for row in answer.titles
            ],
        )


def _merge_aliases(
    pending: Sequence[Group], known: Sequence[ProposedComponent]
) -> _MergeAliases:
    ordered = sorted(pending, key=lambda group: group.id)
    return _MergeAliases(
        {f"G{number}": group for number, group in enumerate(ordered, 1)},
        {f"E{number}": item for number, item in enumerate(known, 1)},
    )


def _group_dir(group: Group) -> str:
    return PurePosixPath(group.files[0]).parent.as_posix()


def _file_symbols(project_root: Path, file: str, factory: ParserFactory) -> list[str]:
    """Approximate what a file offers; a parser failure must not drop the file."""
    path = project_root / file
    try:
        language = detect_language(path)
        if not language.is_programming_language:
            return []
        chunks = factory.create_parser(language).parse_file(path, FileId(0))
    except Exception as exc:
        logger.debug("C4 merge could not parse {}: {}", file, exc)
        return []
    return sorted(
        {
            _PART_SUFFIX.sub("", chunk.symbol)
            for chunk in chunks
            if chunk.chunk_type in _SYMBOL_KINDS
            and not chunk.symbol.startswith("_")
            and not any(mark in chunk.symbol for mark in (".", "::", "_line_"))
        }
    )


def _file_links(
    aliases: _MergeAliases,
    groups: Sequence[Group],
    references: Sequence[Reference],
) -> list[list[int | str]]:
    """Links that can steer a placement; direct groups and other containers cannot.

    A number is the position of a file in the prompt's groups; E<n> is an existing
    component, summed over all its files.
    """
    by_id = {group.id: group for group in groups}
    endpoints: dict[str, int | str] = {
        file: alias
        for alias, item in aliases.components.items()
        for group in item.groups
        for file in by_id[group].files
    }
    pending = (file for group in aliases.groups.values() for file in group.files)
    endpoints.update((file, position) for position, file in enumerate(pending))
    counts: Counter[tuple[int | str, int | str]] = Counter()
    for reference in references:
        left = endpoints.get(reference.from_file)
        right = endpoints.get(reference.to)
        if (
            reference.status == "counts"
            and left is not None
            and right is not None
            and left != right
            and (isinstance(left, int) or isinstance(right, int))
        ):
            counts[left, right] += 1

    def order(end: int | str) -> tuple[bool, int | str]:
        return isinstance(end, str), end

    return [
        [left, right, counts[left, right]]
        for left, right in sorted(
            counts, key=lambda pair: (order(pair[0]), order(pair[1]))
        )
    ]


def _merge_prompt(
    aliases: _MergeAliases,
    groups: Sequence[Group],
    references: Sequence[Reference],
    symbols: Mapping[str, list[str]] | None,
) -> str:
    """Without symbols, each file row holds only its name."""
    by_id = {group.id: group for group in groups}

    def file_row(file: str) -> dict[str, object]:
        row: dict[str, object] = {"name": PurePosixPath(file).name}
        if symbols is not None:
            row["symbols"] = symbols[file]
        return row

    payload = {
        "groups": [
            {
                "id": alias,
                "dir": _group_dir(group),
                "files": [file_row(file) for file in group.files],
            }
            for alias, group in aliases.groups.items()
        ],
        "existing": [
            {
                "id": alias,
                "name": item.name,
                "description": item.description,
                "dirs": sorted({_group_dir(by_id[group]) for group in item.groups}),
            }
            for alias, item in aliases.components.items()
        ],
        "file_links": _file_links(aliases, groups, references),
    }
    return load_c4_prompt("merge") + "\nInput:\n" + json.dumps(payload)


async def merge_container(
    *,
    container: RuntimeUnit,
    project_root: Path,
    references: Sequence[Reference],
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
        result.pending_groups = value.pending_groups
        result.failure_reason = value.failure_reason
        result.placed_groups = value.placed_groups
        result.removed_placements = value.removed_placements

    if llm.trial:
        value = _default_merge(container.id, pending)
        value.components = [*known, *value.components]
        apply(value, False)
        return result
    factory = ParserFactory()
    symbols = {
        file: _file_symbols(project_root, file, factory)
        for group in pending
        for file in group.files
    }
    schema = MergeAnswer.model_json_schema()
    limit = llm.input_limit("synthesis")

    def fitted(aliases: _MergeAliases) -> str | None:
        """Symbols go first; None means this call must not be made."""
        for names in (symbols, None):
            prompt = _merge_prompt(aliases, groups, references, names)
            if fits(prompt, schema, limit, llm.estimate_tokens):
                return prompt
        return None

    def too_large(aliases: _MergeAliases) -> str:
        prompt = _merge_prompt(aliases, groups, references, None)
        size = measure_request(prompt, schema, ())
        return f"invoer te groot: {size} tekens, limiet {limit.max_chars}"

    nothing_placed = MergeResult(list(known), [], False)
    aliases = _merge_aliases(pending, known)
    prompt = fitted(aliases)
    if prompt is None:
        apply(_unplaced(nothing_placed, pending, too_large(aliases)), False)
        return result
    report = llm.report(
        "merge",
        f"container {json.dumps(container.id)}: {len(pending)} niet-geclaimde groepen",
    )

    async def call_once(
        aliases: _MergeAliases,
        prompt: str,
        placed: MergeResult,
        waiting: Sequence[Group],
    ) -> tuple[MergeResult, list[Group]]:
        """Return the new result and what is left; a refusal is not retried."""
        try:
            with report.attempt():
                answer = aliases.translate(await _ask_merge(llm, prompt))
                normalized = normalize_merge_answer(answer, waiting, placed.components)
                value = _apply_answer(
                    answer, normalized, placed, waiting, container.id, group_links
                )
                return value, normalized.leftover
        except ProviderInputRefusedError:
            reason = report.outcomes[-1]
            report.mark_fallback()
            return _unplaced(placed, waiting, reason), []

    def defer_last_call(
        aliases: _MergeAliases,
        prompt: str,
        placed: MergeResult,
        waiting: Sequence[Group],
    ) -> None:
        """The queue is drained once, so this call cannot defer again."""

        async def attempt() -> MergeResult:
            value, leftover = await call_once(aliases, prompt, placed, waiting)
            if not leftover:
                return value
            report.mark_fallback()
            return _unplaced(value, leftover, "antwoord onvolledig")

        def default() -> MergeResult:
            reason = report.outcomes[-1].removesuffix(", terugval")
            return _unplaced(placed, waiting, reason)

        retries.defer(f"merge:{container.id}", attempt, default, apply, report=report)

    try:
        value, leftover = await call_once(aliases, prompt, nothing_placed, pending)
    except TransientStepError:
        defer_last_call(aliases, prompt, nothing_placed, pending)
        return result
    apply(value, False)
    if not leftover:
        return result
    narrow_aliases = _merge_aliases(leftover, value.components)
    narrow = fitted(narrow_aliases)
    if narrow is None:
        apply(_unplaced(value, leftover, too_large(narrow_aliases)), False)
        return result
    defer_last_call(narrow_aliases, narrow, value, leftover)
    return result


@dataclass(frozen=True)
class TitleRequest:
    """What a relation is known to connect: without it no title can say why."""

    from_name: str
    from_description: str
    to_name: str
    to_description: str
    kinds: Mapping[ReferenceKind, int]
    targets: tuple[str, ...]


def _titles_prompt(
    container: str, pending: Mapping[str, TitleRequest], *, targets: bool
) -> str:
    rows = [
        {
            "fingerprint": key,
            "from": {"name": item.from_name, "description": item.from_description},
            "to": {"name": item.to_name, "description": item.to_description},
            "kinds": dict(sorted(item.kinds.items())),
            **({"targets": list(item.targets)} if targets else {}),
        }
        for key, item in sorted(pending.items())
    ]
    return (
        load_c4_prompt("titles")
        + "\nInput:\n"
        + json.dumps({"container": container, "relations": rows})
    )


async def title_relations(
    *,
    container: str,
    pending: Mapping[str, TitleRequest],
    llm: C4Llm,
    retries: RetryQueue,
) -> dict[str, str]:
    """Title only uncached fingerprints. Drain retries before consuming results.

    The caller owns relation markers/cache exclusion: RetryQueue reports fallback
    operations, while this prescribed mapping contains only fingerprint/title.
    A prompt that does not fit or is refused gets fallback titles, like any other
    failure, so they stay out of the lock.
    """
    if not pending:
        return {}

    def default() -> dict[str, str]:
        return {
            key: fallback_title(kind for kind, count in item.kinds.items() if count > 0)
            for key, item in pending.items()
        }

    if llm.trial:
        return default()
    schema = _TitlesAnswer.model_json_schema()
    limit = llm.input_limit("synthesis")
    prompts = [
        _titles_prompt(container, pending, targets=targets) for targets in (True, False)
    ]
    prompt = next(
        (p for p in prompts if fits(p, schema, limit, llm.estimate_tokens)), None
    )
    report = llm.report(
        "titles",
        f"container {json.dumps(container)}: "
        f"{len(pending)} nieuwe of gewijzigde relaties",
    )
    refused = prompt is None
    if prompt is None:
        size = measure_request(prompts[-1], schema, ())
        report.record(f"invoer te groot: {size} tekens, limiet {limit.max_chars}")

    async def attempt() -> dict[str, str]:
        nonlocal refused
        if refused or prompt is None:
            raise TransientStepError("titles: input refused")
        try:
            with report.attempt():
                try:
                    answer = await llm.call(
                        "titles", _TitlesAnswer, prompt, provider="synthesis"
                    )
                except AnswerRejectedError:
                    raise
                except Exception as exc:
                    _raise_sorted("titles", exc)
                if Counter(row.fingerprint for row in answer.titles) != Counter(
                    {key: 1 for key in pending}
                ) or any(not row.title.strip() for row in answer.titles):
                    raise AnswerRejectedError(
                        "titles: every fingerprint must occur exactly once"
                    )
                return {row.fingerprint: row.title for row in answer.titles}
        except ProviderInputRefusedError as exc:
            refused = True
            raise TransientStepError("titles: input refused") from exc

    result: dict[str, str] = {}

    def apply(value: dict[str, str], fallback: bool) -> None:
        result.update(value)

    try:
        apply(await attempt(), False)
    except TransientStepError:
        retries.defer(f"titles:{container}", attempt, default, apply, report=report)
    return result
