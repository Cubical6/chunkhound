"""Bundle composition: reuse stored bundles first, then pack the rest."""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from chunkhound.services.extraction.fragments import Fragment, FragmentIdentity
from chunkhound.services.extraction.store import StoredBundle

Measure = Callable[[Sequence[int]], int]


@dataclass(frozen=True)
class Reuse:
    bundle: StoredBundle
    # Current fragment index -> stored part for the members this bundle covers.
    assigned: dict[int, dict[str, Any]]


def select_reusable(
    fragments: Sequence[Fragment],
    candidates: Sequence[StoredBundle],
) -> list[Reuse]:
    """Deterministically choose stored bundles whose full input still exists.

    A stored bundle qualifies only when every member identity (as a multiset)
    occurs in the current fragments, because the model saw all of them. The
    bundle covering the most still-uncovered fragments wins; ties go to the
    lowest key. The caller rechecks every assigned part.
    """
    occurrences: dict[FragmentIdentity, list[int]] = defaultdict(list)
    for index, fragment in enumerate(fragments):
        occurrences[fragment.identity()].append(index)
    covered: set[int] = set()
    remaining = sorted(candidates, key=lambda bundle: bundle.key)
    chosen: list[Reuse] = []
    while remaining:
        best: Reuse | None = None
        for bundle in remaining:
            assigned = _assign(bundle, occurrences, covered)
            if assigned and (best is None or len(assigned) > len(best.assigned)):
                best = Reuse(bundle, assigned)
        if best is None:
            break
        chosen.append(best)
        covered.update(best.assigned)
        remaining.remove(best.bundle)
    return chosen


def _assign(
    bundle: StoredBundle,
    occurrences: dict[FragmentIdentity, list[int]],
    covered: set[int],
) -> dict[int, dict[str, Any]]:
    needed: dict[FragmentIdentity, int] = defaultdict(int)
    for member in bundle.members:
        needed[member] += 1
    if any(
        len(occurrences.get(member, ())) < count for member, count in needed.items()
    ):
        return {}
    taken: set[int] = set()
    assigned: dict[int, dict[str, Any]] = {}
    for position, member in enumerate(bundle.members):
        # Prefer an occurrence nobody covers yet; identical fragments count apart.
        pool = [index for index in occurrences[member] if index not in taken]
        free = [index for index in pool if index not in covered]
        index = (free or pool)[0]
        taken.add(index)
        if position in bundle.parts and index not in covered:
            assigned[index] = bundle.parts[position]
    return assigned


def pack(indices: Sequence[int], target: int, measure: Measure) -> list[list[int]]:
    """Greedy in the given order; one fragment always fits by construction."""
    bundles: list[list[int]] = []
    current: list[int] = []
    for index in indices:
        if current and measure([*current, index]) > target:
            bundles.append(current)
            current = []
        if measure([index]) > target:
            raise ValueError("A single fragment exceeds the bundle target")
        current.append(index)
    if current:
        bundles.append(current)
    return bundles


def split_to_fit(
    bundle: Sequence[int], target: int, measure: Measure
) -> list[list[int]]:
    """Halve supplied bundles before sending; never truncate a fragment."""
    if measure(bundle) <= target:
        return [list(bundle)]
    if len(bundle) == 1:
        raise ValueError("A single fragment exceeds the bundle target")
    middle = len(bundle) // 2
    return [
        *split_to_fit(bundle[:middle], target, measure),
        *split_to_fit(bundle[middle:], target, measure),
    ]
