"""Coordinate C4 analysis, delayed recovery, and cache-safe finalization."""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from itertools import chain
from pathlib import Path
from typing import Any, TypeVar

from pydantic import TypeAdapter

from chunkhound.code_mapper.c4.assemble import (
    AssemblyInput,
    assemble,
    assemble_with_unlinked,
)
from chunkhound.code_mapper.c4.classify import Classification, ClassifyItem, classify
from chunkhound.code_mapper.c4.contract import (
    Contract,
    ContractCounts,
    build_contract,
    repository_lookup,
    with_git_data,
)
from chunkhound.code_mapper.c4.documented import (
    DocElement,
    DocRelation,
    DocumentedOutcome,
    TopicSources,
    doc_files_for,
    extract_documented,
    prune_documented_cache,
)
from chunkhound.code_mapper.c4.documented import (
    report_lines as documented_report_lines,
)
from chunkhound.code_mapper.c4.files import select_scope_files
from chunkhound.code_mapper.c4.grouping import Group, build_groups
from chunkhound.code_mapper.c4.identity import (
    IdentityResult,
    assign_component_ids,
    detect_renames,
    element_id,
)
from chunkhound.code_mapper.c4.llm import C4Llm, RetryQueue, StepReport
from chunkhound.code_mapper.c4.merge import (
    MergeResult,
    ProposedComponent,
    TitleRequest,
    merge_container,
    relation_fingerprint,
    title_relations,
)
from chunkhound.code_mapper.c4.model import (
    SCHEMA_VERSION,
    C4Evidence,
    C4Model,
    Element,
    LockedClassification,
    LockedComponent,
    LockedDocumented,
    LockedRelation,
    LockedTransition,
    Marker,
    MergedArrow,
    Overrides,
    ReferenceKind,
    Relation,
    RunInfo,
    RunKind,
    ScopeLock,
)
from chunkhound.code_mapper.c4.references import ReferenceScan, scan_references
from chunkhound.code_mapper.c4.runtime import RuntimeScan, scan_runtime
from chunkhound.code_mapper.c4.summaries import derive_views, label_arrows, summary_key
from chunkhound.code_mapper.c4.topic_coverage import compute_coverage
from chunkhound.core.config.config import Config

T = TypeVar("T")


@dataclass(frozen=True)
class C4Options:
    c4: bool
    markdown: bool
    trial: bool


class LlmSteps(RetryQueue):
    """Track each delayed operation's outcome without guessing from its text."""

    def __init__(self, queue: RetryQueue) -> None:
        self.queue = queue
        self.fallbacks: set[str] = set()

    def defer(
        self,
        key: str,
        attempt: Callable[[], Awaitable[T]],
        fallback: Callable[[], T],
        apply: Callable[[T, bool], None],
        *,
        report: StepReport | None = None,
    ) -> None:
        def tracked(value: T, failed: bool) -> None:
            if failed:
                self.fallbacks.add(key)
            apply(value, failed)

        self.queue.defer(key, attempt, fallback, tracked, report=report)

    async def drain(self) -> int:
        return await self.queue.drain()


@dataclass
class C4Draft:
    project_root: Path
    scope_path: Path
    scope_label: str
    files: list[str]
    references: ReferenceScan
    runtime: RuntimeScan
    classifications: dict[str, Classification]
    steps: LlmSteps
    input_fingerprint: str
    direct_groups: dict[str, list[str]] = field(default_factory=dict)
    grouping: list[Group] = field(default_factory=list)
    merges: dict[str, MergeResult] = field(default_factory=dict)
    unknown_overrides: list[str] = field(default_factory=list)
    prepared: bool = False
    excluded_as_test_code: int = 0
    excluded_by_pattern: int = 0


@dataclass
class C4Build:
    model: C4Model
    evidence: C4Evidence
    lock: ScopeLock | None
    fallback_count: int
    report_extra: list[str] = field(default_factory=list)
    contract: Contract | None = None
    contract_counts: ContractCounts | None = None
    # Per repository id: why it has no remote URL, for the report.
    repository_reasons: dict[str, str] = field(default_factory=dict)


def _classification_items(draft: C4Draft) -> list[ClassifyItem]:
    declarations: dict[str, list[dict[str, object]]] = defaultdict(list)
    for declaration in draft.runtime.dependencies:
        declarations[declaration.name].append(asdict(declaration))
    items = [
        ClassifyItem(
            name,
            "dependency",
            {
                "declarations": declarations[name],
                "imports": draft.references.external_sites.get(name, []),
            },
        )
        for name in sorted(declarations.keys() | draft.references.external_sites.keys())
    ]
    items.extend(
        ClassifyItem(c.manifest, "container", asdict(c))
        for c in draft.runtime.uncertain
    )
    items.extend(
        ClassifyItem(c.key, "storage", asdict(c)) for c in draft.runtime.storage
    )
    # A storage key may be referenced by several configuration sources.
    return list({item.key: item for item in items}.values())


def _scan(draft: C4Draft, lock: ScopeLock | None) -> RuntimeScan:
    accepted = {
        item.manifest: draft.classifications[item.manifest].value == "yes"
        for item in draft.runtime.uncertain
    }
    runtime = scan_runtime(
        project_root=draft.project_root,
        scope_path=draft.scope_path,
        files=draft.files,
        locked_containers=lock.containers if lock else {},
        tombstones=lock.tombstones if lock else {},
        accepted=accepted,
    )
    if lock is not None:
        runtime.system_id = lock.system
    runtime.containers = [
        replace(
            unit,
            markers=tuple(
                sorted(
                    set(unit.markers)
                    | set(draft.classifications[unit.manifest].markers)
                )
            ),
        )
        if unit.manifest in draft.classifications
        else unit
        for unit in runtime.containers
    ]
    return runtime


def _group_links(draft: C4Draft) -> dict[tuple[str, str], Counter[ReferenceKind]]:
    owners = {file: group.id for group in draft.grouping for file in group.files}
    links: dict[tuple[str, str], Counter[ReferenceKind]] = defaultdict(Counter)
    for ref in draft.references.references:
        source, target = owners.get(ref.from_file), owners.get(ref.to)
        if ref.status == "counts" and source and target and source != target:
            links[source, target][ref.kind] += 1
    return dict(links)


async def _prepare(draft: C4Draft, llm: C4Llm, lock: ScopeLock | None) -> None:
    draft.runtime = _scan(draft, lock)
    draft.grouping = build_groups(
        files=sorted(draft.runtime.container_of),
        container_of=draft.runtime.container_of,
        container_roots={unit.id: unit.root for unit in draft.runtime.containers},
        container_names={unit.id: unit.name for unit in draft.runtime.containers},
    )
    # Overrides are scope-wide, so only all groups together show which are unknown.
    draft.unknown_overrides = sorted(
        set(lock.overrides.placements if lock else ())
        - {group.id for group in draft.grouping}
    )
    links = _group_links(draft)
    groups_by_container = defaultdict(list)
    for group in draft.grouping:
        groups_by_container[group.container].append(group)
    for container in draft.runtime.containers:
        groups = groups_by_container[container.id]
        claimed = {
            group
            for component in (lock.components.values() if lock else ())
            for group in component.groups
        }
        cached_direct = set(lock.direct_groups.get(container.id, ()) if lock else ())
        cached_direct.difference_update(claimed)
        cached_direct.difference_update(lock.overrides.placements if lock else ())
        draft.direct_groups[container.id] = sorted(
            group.id for group in groups if group.id in cached_direct
        )
        groups = [group for group in groups if group.id not in cached_direct]
        group_ids = {group.id for group in groups}
        draft.merges[container.id] = await merge_container(
            container=container,
            project_root=draft.project_root,
            references=draft.references.references,
            groups=groups,
            group_links={
                pair: kinds
                for pair, kinds in links.items()
                if pair[0] in group_ids and pair[1] not in cached_direct
            },
            existing=lock.components if lock else {},
            placements=lock.overrides.placements if lock else {},
            llm=llm,
            retries=draft.steps,
        )
    draft.prepared = True


# Request-size limits change cost, not analysis results; keeping them out of the
# fingerprint lets existing locks keep their history across the upgrade.
_FINGERPRINT_EXCLUDE = {
    "llm": {"utility_max_input_chars", "utility_max_input_tokens"},
}


def _fingerprint_config(config: Config) -> dict[str, Any]:
    data = config.model_dump(mode="json", exclude=_FINGERPRINT_EXCLUDE)
    # The default patterns come from a set, so their order differs per process.
    data["indexing"]["include"] = sorted(data["indexing"]["include"])
    return data


def _input_fingerprint(
    project_root: Path, files: list[str], config: Config | None, scope_path: Path
) -> str:
    """Hash actual analyzed bytes, not Git status or modification timestamps."""
    hashes = {}
    for file in files:
        digest = hashlib.sha256()
        with (project_root / file).open("rb") as source:
            for block in iter(lambda: source.read(65536), b""):
                digest.update(block)
        hashes[file] = digest.hexdigest()
    payload = {
        "files": hashes,
        "scope": scope_path.relative_to(project_root).as_posix(),
        "config": _fingerprint_config(config) if config else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def analyze_c4(
    *,
    project_root: Path,
    scope_path: Path,
    scope_label: str,
    config: Config | None,
    llm: C4Llm,
    lock: ScopeLock | None,
    retries: RetryQueue,
    own_output: tuple[Path, str] | None = None,
) -> C4Draft:
    """Read disk once; retain mutable step outcomes until delayed recovery."""
    selection = select_scope_files(
        scope_path=scope_path,
        project_root=project_root,
        config=config,
        own_output=own_output,
    )
    files = selection.files
    references = await scan_references(project_root=project_root, files=files)
    runtime = scan_runtime(
        project_root=project_root,
        scope_path=scope_path,
        files=files,
        locked_containers=lock.containers if lock else {},
        tombstones=lock.tombstones if lock else {},
    )
    draft = C4Draft(
        project_root,
        scope_path,
        scope_label,
        files,
        references,
        runtime,
        {},
        LlmSteps(retries),
        _input_fingerprint(project_root, files, config, scope_path),
        excluded_as_test_code=selection.excluded_as_test_code,
        excluded_by_pattern=selection.excluded_by_pattern,
    )
    items = _classification_items(draft)
    draft.classifications = await classify(
        items, llm=llm, lock=lock, retries=draft.steps
    )
    if all(item.key in draft.classifications for item in items):
        await _prepare(draft, llm, lock)
    return draft


def _failed_containers(draft: C4Draft) -> frozenset[str]:
    return frozenset(id for id, merge in draft.merges.items() if merge.fallback)


def _carry_locked_components(
    draft: C4Draft, identity: IdentityResult, lock: ScopeLock
) -> dict[str, LockedComponent]:
    """Keep what a failed merge could still match to a renamed directory.

    Its unplaced groups may be that component under a new name, so retiring its
    ID now would lose it. A component with a living group is never kept: on the
    next run that group would have two owners, which merge rejects.
    """
    failed = _failed_containers(draft)
    living = {group.id for group in draft.grouping}
    inherited = set(identity.ids.values())
    carried = {
        id: component
        for id, component in lock.components.items()
        if component.container in failed
        and id not in inherited
        and living.isdisjoint(component.groups)
    }
    for id in carried:
        del identity.tombstones[id]
    identity.history = [
        edge
        for edge in identity.history
        if edge.kind != "removed" or edge.from_id not in carried
    ]
    return carried


def _identify(
    draft: C4Draft, docs: DocumentedOutcome, lock: ScopeLock | None
) -> tuple[
    IdentityResult,
    dict[str, tuple[ProposedComponent, str]],
    bool,
    dict[str, LockedComponent],
]:
    groups = {g.id: g for g in draft.grouping}
    proposals = {p.key: p for merge in draft.merges.values() for p in merge.components}
    renames = detect_renames(draft.project_root, lock.base_sha if lock else "")
    identity = assign_component_ids(
        previous={id: frozenset(c.files) for id, c in lock.components.items()}
        if lock
        else {},
        current={
            key: (
                p.name,
                frozenset(file for group in p.groups for file in groups[group].files),
            )
            for key, p in proposals.items()
        },
        renames=renames or {},
        taken_found=frozenset(
            {draft.runtime.system_id} | {u.id for u in draft.runtime.containers}
        ),
        documented_without_files=frozenset(
            element_id(e.kind, e.term) for e in docs.elements
        ),
        tombstones=lock.tombstones if lock else {},
    )
    carried: dict[str, LockedComponent] = {}
    if lock:
        carried = _carry_locked_components(draft, identity, lock)
        current_manifests = {unit.manifest for unit in draft.runtime.containers}
        for manifest, id in lock.containers.items():
            if manifest not in current_manifests:
                identity.tombstones[manifest] = id
    return (
        identity,
        {key: (p, identity.ids[key]) for key, p in proposals.items()},
        renames is not None,
        carried,
    )


def _merged_titles(draft: C4Draft, identity: IdentityResult) -> dict[str, str]:
    titles = {}
    for outcome in draft.merges.values():
        for (source, target), title in outcome.titles.items():
            source = identity.ids.get(source, source)
            target = identity.ids.get(target, target)
            titles[f"{source}->{target}"] = title
    return titles


def _fingerprints(
    evidence: C4Evidence, relations: Sequence[Relation]
) -> dict[str, str]:
    refs: dict[str, list[tuple[ReferenceKind, str]]] = defaultdict(list)
    for reference in evidence.references:
        if reference.relation:
            refs[reference.relation].append((reference.kind, reference.to))
    return {
        r.id: relation_fingerprint(r.from_id, r.to_id, refs[r.id])
        for r in relations
        if r.id in refs
    }


def _title_targets(evidence: C4Evidence) -> dict[str, tuple[str, ...]]:
    reached: dict[str, set[str]] = defaultdict(set)
    for reference in evidence.references:
        if reference.relation:
            reached[reference.relation].add(reference.to.removeprefix("package:"))
    return {id: tuple(sorted(targets)[:5]) for id, targets in reached.items()}


def _pending_titles(
    inp: AssemblyInput,
    elements: Sequence[Element],
    relations: Sequence[Relation],
    evidence: C4Evidence,
    lock: ScopeLock | None,
) -> dict[str, dict[str, TitleRequest]]:
    by_id = {element.id: element for element in elements}
    fingerprints = _fingerprints(evidence, relations)
    targets = _title_targets(evidence)
    pending: dict[str, dict[str, TitleRequest]] = defaultdict(dict)
    for relation in relations:
        fingerprint = fingerprints.get(relation.id)
        if (
            fingerprint is None
            or relation.id in inp.titles
            or relation.id in inp.overrides.titles
        ):
            continue
        cached = lock.relations.get(relation.id) if lock else None
        if cached and cached.fingerprint == fingerprint:
            inp.titles[fingerprint] = cached.title
            continue
        source = by_id[relation.from_id]
        container = source.parent if source.kind == "component" else source.id
        assert container is not None
        target = by_id[relation.to_id]
        pending[container][fingerprint] = TitleRequest(
            from_name=source.name,
            from_description=source.description or "",
            to_name=target.name,
            to_description=target.description or "",
            kinds=Counter(relation.reference_counts),
            targets=targets.get(relation.id, ()),
        )
    return dict(pending)


async def _titles(
    inp: AssemblyInput, draft: C4Draft, llm: C4Llm, lock: ScopeLock | None
) -> tuple[list[Element], list[Relation], C4Evidence]:
    elements, relations, evidence = assemble(inp)
    fingerprints = _fingerprints(evidence, relations)
    pending = _pending_titles(inp, elements, relations, evidence, lock)
    outcomes = {
        container: await title_relations(
            container=container, pending=items, llm=llm, retries=draft.steps
        )
        for container, items in pending.items()
    }
    await draft.steps.drain()
    for outcome in outcomes.values():
        inp.titles.update(outcome)
    elements, relations, evidence = assemble(inp)
    markers: dict[str, Marker] = {}
    for container, items in pending.items():
        if llm.trial or f"titles:{container}" in draft.steps.fallbacks:
            markers.update(dict.fromkeys(items, "trial" if llm.trial else "fallback"))
    for relation in relations:
        marker = markers.get(fingerprints.get(relation.id, ""))
        if marker and marker not in relation.markers:
            relation.markers = sorted([*relation.markers, marker])
    return elements, relations, evidence


def _lock_components(
    inp: AssemblyInput, evidence: C4Evidence
) -> dict[str, LockedComponent]:
    groups = {g.id: g for g in inp.groups}
    return {
        id: LockedComponent(
            name=p.name,
            description=p.description,
            container=groups[p.groups[0]].container,
            groups=list(p.groups),
            files=evidence.element_files[id],
        )
        for p, id in inp.components.values()
        if not {"fallback", "trial"}.intersection(p.markers)
    }


def _direct_groups(draft: C4Draft) -> dict[str, list[str]]:
    return {
        container: sorted(
            set(draft.direct_groups[container]) | set(merge.direct_groups)
        )
        for container, merge in draft.merges.items()
    }


def _final_fingerprint(
    draft: C4Draft,
    topics: Sequence[TopicSources] | None,
    docs: DocumentedOutcome,
    head_sha: str,
    overrides: Overrides,
) -> str:
    payload = {
        "analysis": draft.input_fingerprint,
        # Resolution consults project paths outside the analyzed file scope.
        "references": [
            reference.model_dump(mode="json")
            for reference in draft.references.references
        ],
        "imports_only_files": sorted(draft.references.imports_only_files),
        "external_sites": {
            name: sorted(sites)
            for name, sites in draft.references.external_sites.items()
        },
        "head": head_sha,
        "scope": draft.scope_label,
        "topics": [asdict(topic) for topic in topics] if topics is not None else None,
        "documentation": docs.hashes,
        "overrides": overrides.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _replay_history(
    identity: IdentityResult,
    renames: bool,
    fingerprint: str,
    lock: ScopeLock | None,
) -> bool:
    previous = lock.transition if lock else None
    if previous is None or previous.input_fingerprint != fingerprint:
        return renames
    identity.history = [edge.model_copy(deep=True) for edge in previous.history]
    return previous.renames


def _transition(
    draft: C4Draft, model: C4Model, inp: AssemblyInput, fingerprint: str
) -> LockedTransition | None:
    if draft.steps.fallbacks or inp.documented.fallback or model.run.kind == "trial":
        return None
    if any(c.fallback for c in draft.classifications.values()):
        return None
    if any(m.fallback for m in draft.merges.values()):
        return None
    marked: Iterable[Element | Relation | MergedArrow] = chain(
        model.elements, model.relations, model.merged
    )
    if any({"fallback", "trial"}.intersection(item.markers) for item in marked):
        return None
    return LockedTransition(
        input_fingerprint=fingerprint,
        history=model.history,
        renames=model.run.renames,
    )


def _build_lock(
    draft: C4Draft,
    model: C4Model,
    evidence: C4Evidence,
    inp: AssemblyInput,
    identity: IdentityResult,
    fingerprint: str,
    lock: ScopeLock | None,
    carried: dict[str, LockedComponent],
) -> ScopeLock:
    fingerprints = _fingerprints(evidence, model.relations)
    titles = {r.id: r.title for r in model.relations}
    docs = inp.documented
    return ScopeLock(
        # The next run must still see renames made since the last complete merge.
        base_sha=lock.base_sha
        if lock and _failed_containers(draft)
        else model.run.head_sha,
        system=draft.runtime.system_id,
        containers={
            unit.manifest: unit.id
            for unit in draft.runtime.containers
            if not {"fallback", "trial"}.intersection(unit.markers)
        },
        direct_groups=_direct_groups(draft),
        transition=_transition(draft, model, inp, fingerprint),
        components={**_lock_components(inp, evidence), **carried},
        tombstones=identity.tombstones,
        relations={
            r.id: LockedRelation(title=r.title, fingerprint=fingerprints[r.id])
            for r in model.relations
            if r.id in fingerprints
            and not {"fallback", "trial"}.intersection(r.markers)
        },
        classifications={
            key: LockedClassification(
                value=c.value, votes=list(c.votes), markers=list(c.markers)
            )
            for key, c in draft.classifications.items()
            if not {"fallback", "trial"}.intersection(c.markers)
        },
        documented=None
        if docs.fallback
        else LockedDocumented(
            hashes=docs.hashes,
            elements=TypeAdapter(list[DocElement]).dump_python(
                docs.elements, mode="json"
            ),
            relations=TypeAdapter(list[DocRelation]).dump_python(
                docs.relations, mode="json"
            ),
        ),
        summaries={
            summary_key((id, titles[id]) for id in arrow.underlying): arrow.label
            for arrow in model.merged
            if not {"fallback", "trial"}.intersection(arrow.markers)
        },
        overrides=inp.overrides.model_copy(deep=True),
    )


def _source_line(draft: C4Draft) -> str:
    return (
        f"C4-bron: {len(draft.files)} bestanden geanalyseerd, "
        f"{draft.excluded_as_test_code} uitgesloten als testcode, "
        f"{draft.excluded_by_pattern} door c4.exclude"
    )


def _merge_lines(draft: C4Draft, trial: bool) -> list[str]:
    """Only groups a call was about; a trial makes no call, whatever it proposes."""
    lines = []
    for container, merge in sorted(draft.merges.items()):
        pending = len(merge.pending_groups)
        if trial or not (merge.placed_groups or pending):
            continue
        unplaced = (
            f"{pending} niet geplaatst ({merge.failure_reason}), " if pending else ""
        )
        lines.append(
            f"C4-merge {container}: {merge.placed_groups + pending} bouwstenen, "
            f"{merge.placed_groups} geplaatst, {unplaced}"
            f"{merge.removed_placements} plaatsingen verwijderd"
        )
    lines.extend(
        f"C4-merge: override voor onbekende groep genegeerd: {group}"
        for group in draft.unknown_overrides
    )
    return lines


def _named(names: tuple[str, ...], noun: str) -> str:
    listed = f" ({', '.join(names)})" if names else ""
    return f"{len(names)} {noun}{listed}"


def _contract_lines(
    contract: Contract, counts: ContractCounts, repository_reasons: dict[str, str]
) -> list[str]:
    return [
        f"C4-contract: {len(contract.elements)} elementen, "
        f"{len(contract.relations)} relaties, {len(contract.sources)} bronnen, "
        f"{len(contract.merged_labels)} labels, {len(contract.topics)} topics",
        f"C4-contract weggelaten: {counts.components_without_container} componenten "
        f"zonder container, {counts.elements_without_source} elementen zonder bron, "
        f"{counts.components_without_valid_container} componenten zonder geldige "
        f"container, {counts.relations_without_endpoint} relaties zonder eindpunt, "
        f"{counts.relations_without_source} relaties zonder bron, "
        f"{counts.labels} labels, "
        f"{counts.relations_inside_container} relaties binnen een container, "
        f"{counts.redundant_direct_relations} overbodige relaties van directe "
        "bestanden",
        "C4-contract zonder relatie weggelaten: "
        f"{_named(counts.externals_without_relation, 'externe systemen')}, "
        f"{_named(counts.persons_without_relation, 'personen')}",
        f"C4-contract onvolledig: {counts.without_technology} zonder technologie, "
        f"{counts.without_description} zonder omschrijving, "
        f"{counts.container_relations_without_protocol} relaties tussen containers "
        "zonder protocol",
        *(
            f"C4-contract repository {id}: geen bronlinks ({reason})"
            for id, reason in sorted(repository_reasons.items())
        ),
    ]


async def finish_c4(
    *,
    draft: C4Draft,
    topics: Sequence[TopicSources] | None,
    llm: C4Llm,
    lock: ScopeLock | None,
    retries: RetryQueue,
    head_sha: str,
    kind: RunKind,
    config: Config | None = None,
    own_output: tuple[Path, str] | None = None,
) -> C4Build:
    """Finalize dependent steps only after their deferred inputs are settled."""
    topic_files = {file for topic in topics or () for file in topic.files}
    docs = await extract_documented(
        project_root=draft.project_root,
        doc_files=doc_files_for(
            draft.project_root, draft.scope_path, topics or (), config, own_output
        ),
        locked=lock.documented if lock else None,
        llm=llm,
        retries=draft.steps,
        # Research only orders the calls; it never limits coverage.
        order_hint=lambda fragment: float(fragment.source.path in topic_files),
    )
    await retries.drain()
    if not draft.prepared:
        await _prepare(draft, llm, lock)
        await retries.drain()
    identity, components, renames, carried = _identify(draft, docs, lock)
    overrides = lock.overrides if lock else Overrides()
    fingerprint = _final_fingerprint(draft, topics, docs, head_sha, overrides)
    renames = _replay_history(identity, renames, fingerprint, lock)
    inp = AssemblyInput(
        draft.runtime,
        draft.references,
        draft.grouping,
        components,
        _direct_groups(draft),
        draft.classifications,
        docs,
        _merged_titles(draft, identity),
        overrides,
        _failed_containers(draft),
        draft.project_root,
    )
    elements, relations, evidence = await _titles(inp, draft, llm, lock)
    coverage = compute_coverage(
        element_files=evidence.element_files,
        direct_files={},
        topics=None if llm.trial else topics,
    )
    for element in elements:
        element.coverage = coverage[element.id]
        if element.kind == "component" and element.coverage.status == "undescribed":
            element.markers.append("undescribed")
            element.markers.sort()
        if docs.fallback and any(
            c.target == element.id
            and c.source == "documentation"
            and (c.file, c.start_line, c.end_line) in docs.fallback_citations
            for c in evidence.citations
        ):
            if "fallback" not in element.markers:
                element.markers.append("fallback")
                element.markers.sort()
    merged = await label_arrows(
        derive_views(elements, relations),
        titles_by_relation={r.id: r.title for r in relations},
        locked=lock.summaries if lock else {},
        overrides=inp.overrides.labels,
        llm=llm,
        retries=draft.steps,
    )
    await retries.drain()
    fallback_count = sum("fallback" in element.markers for element in elements)
    model = C4Model(
        run=RunInfo(
            id="",
            kind=kind,
            schema_version=SCHEMA_VERSION,
            head_sha=head_sha,
            scope=draft.scope_label,
            fallback_count=fallback_count,
            fallback_fragments=len(docs.fallback_fragments),
            renames=renames,
        ),
        elements=elements,
        relations=relations,
        merged=merged,
        history=identity.history,
    )
    updated = (
        None
        if llm.trial
        else _build_lock(
            draft, model, evidence, inp, identity, fingerprint, lock, carried
        )
    )
    if not llm.trial:
        prune_documented_cache(draft.project_root)
    unlinked = assemble_with_unlinked(inp)[3]
    report_extra = [
        *documented_report_lines(docs),
        "C4 documentatierelaties niet gekoppeld: "
        f"{unlinked.no_match} geen treffer, {unlinked.ambiguous} meerdere "
        f"treffers, {unlinked.not_allowed} niet toegestaan",
        _source_line(draft),
        *_merge_lines(draft, llm.trial),
    ]
    contract: Contract | None = None
    contract_counts: ContractCounts | None = None
    repository_reasons: dict[str, str] = {}
    if kind == "full":
        contract, contract_counts = build_contract(
            model, evidence, topics, repository_lookup(draft.project_root)
        )
        contract, repository_reasons = with_git_data(
            contract, draft.project_root, head_sha
        )
        report_extra += _contract_lines(contract, contract_counts, repository_reasons)
    else:
        report_extra.append("C4-contract: niet geschreven (proefrun)")
    return C4Build(
        model,
        evidence,
        updated,
        fallback_count,
        report_extra,
        contract,
        contract_counts,
        repository_reasons,
    )
