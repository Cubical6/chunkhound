"""Stable element IDs, mutual-majority component identity, and run history."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from chunkhound.code_mapper.c4.model import ElementKind, HistoryEdge, HistoryKind
from chunkhound.utils.git_safe import GitCommandError, run_git
from chunkhound.utils.text import slugify_kebab

PREFIXES: Mapping[ElementKind, str] = MappingProxyType(
    {
        "system": "systeem:",
        "container": "container:",
        "storage": "opslag:",
        "external": "extern:",
        "person": "persoon:",
        "component": "component:",
    }
)


def element_id(kind: ElementKind, term: str) -> str:
    return PREFIXES[kind] + slugify_kebab(term, ascii_only=True)


def detect_renames(project_root: Path, base_sha: str) -> dict[str, str] | None:
    """Return committed old-to-new paths, or None when Git comparison is unavailable."""
    try:
        base = run_git(
            ["rev-parse", "--verify", "--end-of-options", f"{base_sha}^{{commit}}"],
            cwd=project_root,
        )
        if base.returncode != 0:
            return None
        diff = run_git(
            ["diff", "-M", "--name-status", "-z", base.stdout.strip(), "HEAD", "--"],
            cwd=project_root,
        )
        if diff.returncode != 0:
            return None
    except (GitCommandError, OSError, ValueError):
        return None

    renames: dict[str, str] = {}
    # NUL separation preserves tabs, newlines, and Git-quoted path characters.
    fields = iter(diff.stdout.rstrip("\0").split("\0")) if diff.stdout else iter(())
    for status in fields:
        path = next(fields)
        if status.startswith(("R", "C")):
            destination = next(fields)
            if status.startswith("R"):
                renames[path] = destination
    return renames


@dataclass
class IdentityResult:
    ids: dict[str, str]
    history: list[HistoryEdge]
    tombstones: dict[str, str]


def _overlaps(
    previous: Mapping[str, frozenset[str]],
    current: Mapping[str, tuple[str, frozenset[str]]],
    renames: Mapping[str, str],
) -> tuple[Counter[tuple[str, str]], Counter[str], Counter[str]]:
    # R2 gives each file at most one component in each run. Indexing by file
    # avoids comparing every old component's set to every new component's set.
    old_owner = {
        renames.get(path, path): old_id
        for old_id, files in previous.items()
        for path in files
    }
    new_owner = {path: key for key, (_, files) in current.items() for path in files}
    pairs: Counter[tuple[str, str]] = Counter()
    old_sizes: Counter[str] = Counter()
    new_sizes: Counter[str] = Counter()
    for path in old_owner.keys() & new_owner.keys():
        old_id, key = old_owner[path], new_owner[path]
        pairs[old_id, key] += 1
        old_sizes[old_id] += 1
        new_sizes[key] += 1
    return pairs, old_sizes, new_sizes


def _history(
    previous: Mapping[str, frozenset[str]],
    ids: Mapping[str, str],
    inherited: Mapping[str, str],
    significant: list[tuple[str, str]],
) -> list[HistoryEdge]:
    successors = Counter(old_id for old_id, _ in significant)
    predecessors = Counter(key for _, key in significant)
    history = []
    for old_id, key in significant:
        kind: HistoryKind = "continuation"
        if predecessors[key] > 1:
            kind = "merge"
        elif successors[old_id] > 1:
            kind = "split"
        history.append(HistoryEdge(from_id=old_id, to_id=ids[key], kind=kind))
    history.extend(
        HistoryEdge(from_id="", to_id=ids[key], kind="new")
        for key in sorted(ids.keys() - inherited.keys())
    )
    surviving_ids = set(inherited.values())
    history.extend(
        HistoryEdge(from_id=old_id, to_id="", kind="removed")
        for old_id in sorted(previous.keys() - surviving_ids)
    )
    return history


def assign_component_ids(
    *,
    previous: Mapping[str, frozenset[str]],
    current: Mapping[str, tuple[str, frozenset[str]]],
    renames: Mapping[str, str],
    taken_found: frozenset[str],
    documented_without_files: frozenset[str],
    tombstones: Mapping[str, str],
) -> IdentityResult:
    """Apply R3 over shared files; never reissue a removed component ID.

    Inputs have disjoint component memberships (R2). New/deleted files do not
    affect either majority denominator. History labels describe significant
    overlap, not inheritance: merge precedes split, then continuation. Empty
    endpoints mark new/removed IDs, including non-inheriting split/merge IDs.
    Component tombstones map the removed ID to itself; other entries survive.
    """
    pairs, old_sizes, new_sizes = _overlaps(previous, current, renames)
    retired = set(tombstones) | set(tombstones.values())
    inherited = {
        key: old_id
        for (old_id, key), count in pairs.items()
        if old_id not in retired
        and 2 * count > old_sizes[old_id]
        and 2 * count > new_sizes[key]
    }
    ids = dict(inherited)
    # Only found/previous/retired IDs reserve names. Membership in
    # documented_without_files alone deliberately does not reserve an ID.
    reserved = set(previous) | set(taken_found) | retired
    for key, (name, _) in sorted(current.items()):
        if key in inherited:
            continue
        base = element_id("component", name)
        candidate = base
        suffix = 2
        while candidate in reserved:
            candidate = f"{base}-{suffix}"
            suffix += 1
        ids[key] = candidate
        reserved.add(candidate)

    significant = sorted(
        (old_id, key)
        for (old_id, key), count in pairs.items()
        if 10 * count >= old_sizes[old_id] or 10 * count >= new_sizes[key]
    )
    updated_tombstones = dict(tombstones)
    for old_id in previous.keys() - set(inherited.values()):
        updated_tombstones.setdefault(old_id, old_id)
    return IdentityResult(
        ids=ids,
        history=_history(previous, ids, inherited, significant),
        tombstones=updated_tombstones,
    )
