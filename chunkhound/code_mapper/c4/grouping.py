"""Deterministic container-local groups with persisted file ownership.

File identities (Group.files and group_membership keys) are project-relative POSIX
paths. Unit positions and rule prefixes are relative to the explicit runtime root.
Membership values are local rule IDs; public group IDs qualify them by container.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from loguru import logger

from chunkhound.code_mapper.c4.codeboarding.names import (
    ROOT_SCOPE_ID,
    AffinityGrouper,
    ComponentRule,
    KinshipGrouper,
    Links,
    Partition,
    ScopeSpec,
    TreeSpec,
    Unit,
    draft_scope,
    draft_tree,
    replay,
    role_words_for,
)
from chunkhound.code_mapper.c4.model import Reference
from chunkhound.core.detection.language_detector import detect_language
from chunkhound.core.types.common import FileId
from chunkhound.parsers.parser_factory import ParserFactory


@dataclass(frozen=True)
class Group:
    id: str
    container: str
    name: str
    prefix: str
    files: tuple[str, ...]


@dataclass
class GroupingResult:
    tree_specs: dict[str, TreeSpec]
    groups: list[Group]
    new_group_ids: frozenset[str]
    group_membership: dict[str, dict[str, str]]


def _unit(project_root: Path, file: str, root: str, factory: ParserFactory) -> Unit:
    path = project_root / file
    relative = Path(file).relative_to(root)
    language = detect_language(path)
    try:
        parser = factory.create_parser(language)
        names = tuple(chunk.symbol for chunk in parser.parse_file(path, FileId(0)))
    except Exception as exc:
        # A parser failure must not remove a file from the partition's coverage.
        logger.debug("C4 grouping could not parse {}: {}", file, exc)
        names = ()
    position = relative.parent.parts
    return Unit(file, language.value, names, position, (*position, relative.stem))


def _container_links(
    references: Sequence[Reference], container_of: Mapping[str, str], files: set[str]
) -> dict[str, Counter[tuple[str, str]]]:
    links: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    for reference in references:
        left, right = reference.from_file, reference.to
        if reference.status != "counts" or left == right:
            continue
        if left not in files or right not in files:
            continue
        container = container_of[left]
        if container_of[right] == container:
            links[container][left, right] += 1
    return links


def _new_directories(
    partition: Partition, previous: Mapping[str, str], root: str
) -> dict[tuple[str, ...], list[Unit]]:
    """Find genuinely new branches, not previously known term/fallback residue."""
    known_directories: set[tuple[str, ...]] = {()}
    for file in previous:
        position = Path(file).relative_to(root).parent.parts
        known_directories.update(
            position[:depth] for depth in range(1, len(position) + 1)
        )
    candidates = {
        unit.unit_id: unit
        for units in partition.new_scopes.values()
        for unit in units
        if unit.unit_id not in previous
    }
    candidates.update(
        (unit.unit_id, unit)
        for unit in partition.unplaced
        if unit.unit_id not in previous
    )
    branches: dict[tuple[str, ...], list[Unit]] = defaultdict(list)
    for file in sorted(candidates):
        unit = candidates[file]
        for depth in range(1, len(unit.position) + 1):
            prefix = unit.position[:depth]
            if prefix not in known_directories:
                branches[prefix].append(unit)
                break
    return branches


def _extend_scope(
    scope: ScopeSpec,
    partition: Partition,
    previous: Mapping[str, str],
    root: str,
    role_words: frozenset[str],
    links: Links,
) -> set[str]:
    """Append rules only; never let new words re-vote existing ownership."""
    added: set[str] = set()
    for prefix, units in sorted(_new_directories(partition, previous, root).items()):
        local_id = scope.next_id()
        scope.rules.append(
            ComponentRule(local_id, "/".join(prefix), prefixes=(prefix,))
        )
        added.add(local_id)
        partition.assignment.update((unit.unit_id, local_id) for unit in units)

    unplaced = [
        unit for unit in partition.unplaced if unit.unit_id not in partition.assignment
    ]
    if unplaced:
        drafted, placement = draft_scope(
            ROOT_SCOPE_ID, unplaced, role_words, KinshipGrouper(), links=links
        )
        for rule in drafted.rules:
            local_id = scope.next_id()
            scope.rules.append(replace(rule, component_id=local_id, parts=()))
            added.add(local_id)
            partition.assignment.update(
                (unit.unit_id, local_id)
                for unit in placement.members[rule.component_id]
            )
    return added


def _prefix(rule: ComponentRule) -> str:
    """A container-relative common prefix; '.' denotes the container root."""
    prefixes = rule.prefixes or rule.fallback_prefixes
    if not prefixes:
        return "."
    common = []
    for segments in zip(*prefixes):
        if len(set(segments)) != 1:
            break
        common.append(segments[0])
    return "/".join(common) or "."


def _place_container(
    tree: TreeSpec,
    units: list[Unit],
    previous: Mapping[str, str] | None,
    root: str,
    links: Links,
) -> tuple[ScopeSpec, dict[str, str], set[str]]:
    scope = tree.scope(ROOT_SCOPE_ID)
    if scope is None:
        raise ValueError("C4 grouping tree has no root scope")
    role_words = role_words_for(tree.machinery)
    partition = replay(units, scope, role_words)
    if previous is None:
        added = {rule.component_id for rule in scope.rules}
    else:
        # Membership beats changed symbols and new rules, including for loose files.
        partition.assignment.update(
            (unit.unit_id, previous[unit.unit_id])
            for unit in units
            if unit.unit_id in previous
        )
        added = _extend_scope(scope, partition, previous, root, role_words, links)
    return (
        scope,
        {unit.unit_id: partition.assignment[unit.unit_id] for unit in units},
        added,
    )


def _groups_for(
    container: str, scope: ScopeSpec, membership: Mapping[str, str]
) -> list[Group]:
    members: dict[str, list[str]] = defaultdict(list)
    for file, local_id in membership.items():
        members[local_id].append(file)
    return [
        Group(
            f"{container}/{rule.component_id}",
            container,
            rule.name,
            _prefix(rule),
            tuple(members[rule.component_id]),
        )
        for rule in scope.rules
        if members[rule.component_id]
    ]


def build_groups(
    *,
    project_root: Path,
    files: Sequence[str],
    container_of: Mapping[str, str],
    container_roots: Mapping[str, str],
    references: Sequence[Reference],
    stored: Mapping[str, dict[str, Any]],
    stored_membership: Mapping[str, Mapping[str, str]],
) -> GroupingResult:
    """Draft once, then replay stable membership without any language model.

    Runtime supplies roots, including provisional scope roots. Previous membership
    includes direct groups, not just those claimed by a semantic component.
    """
    factory = ParserFactory()
    files_set = set(files)
    by_container: dict[str, list[Unit]] = defaultdict(list)
    for file in sorted(files_set):
        container = container_of[file]
        by_container[container].append(
            _unit(project_root, file, container_roots[container], factory)
        )
    links = _container_links(references, container_of, files_set)
    tree_specs: dict[str, TreeSpec] = {}
    groups: list[Group] = []
    new_ids: set[str] = set()
    membership: dict[str, dict[str, str]] = {}
    for container, units in sorted(by_container.items()):
        container_links: Links = links.get(container, {})
        if container in stored:
            tree = TreeSpec.from_dict(stored[container])
        else:
            tree = draft_tree(
                units, AffinityGrouper(), max_depth=1, links=container_links
            )
        scope, ownership, added = _place_container(
            tree,
            units,
            stored_membership[container] if container in stored else None,
            container_roots[container],
            container_links,
        )
        membership[container] = ownership
        groups.extend(_groups_for(container, scope, ownership))
        new_ids.update(f"{container}/{local_id}" for local_id in added)
        tree_specs[container] = tree
    return GroupingResult(tree_specs, groups, frozenset(new_ids), membership)
