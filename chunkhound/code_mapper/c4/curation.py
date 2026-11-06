"""Pure, simultaneous drop/merge curation of an assembled source-backed map."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from chunkhound.code_mapper.c4.merge import fallback_title, relation_fingerprint
from chunkhound.code_mapper.c4.model import (
    Citation,
    Element,
    Overrides,
    Reference,
    Relation,
)


@dataclass(frozen=True)
class CurationState:
    """The assembled map and its evidence before or after curation."""

    elements: dict[str, Element]
    relations: dict[str, Relation]
    citations: list[Citation]
    references: list[Reference]
    files: dict[str, list[str]]
    ignored_overrides: tuple[str, ...] = ()
    absorbed: dict[str, str] = field(default_factory=dict)


def _endpoint_reason(elements: dict[str, Element], *ids: str) -> str | None:
    if any(id not in elements for id in ids):
        return "not on the map"
    if any(elements[id].kind not in {"external", "person"} for id in ids):
        return "not an external system or person"
    return None


def _merge_reason(
    elements: dict[str, Element], source: str, target: str, dropped: set[str]
) -> str | None:
    reason = _endpoint_reason(elements, source, target)
    if reason:
        return reason
    if source == target:
        return "same element"
    if elements[source].kind != elements[target].kind:
        return "different kinds"
    if source in dropped or target in dropped:
        return "dropped"
    return None


def _validated(
    elements: dict[str, Element], overrides: Overrides, prefix: str
) -> tuple[set[str], dict[str, str], tuple[str, ...]]:
    dropped: set[str] = set()
    drop_notes: dict[str, str] = {}
    for id in sorted(set(overrides.drop)):
        reason = _endpoint_reason(elements, id)
        if reason:
            drop_notes[id] = f"{prefix} drop ignored for {id} ({reason})"
        else:
            dropped.add(id)

    candidates: dict[str, str] = {}
    merge_notes: dict[str, str] = {}
    for source, target in sorted(overrides.merge.items()):
        reason = _merge_reason(elements, source, target, dropped)
        if reason:
            merge_notes[source] = (
                f"{prefix} merge ignored for {source} -> {target} ({reason})"
            )
        else:
            candidates[source] = target

    # Round two always sees the complete first round, not earlier removals.
    merged: dict[str, str] = {}
    for source, target in candidates.items():
        if target in candidates:
            merge_notes[source] = (
                f"{prefix} merge ignored for {source} -> {target} "
                "(target is merged itself)"
            )
        else:
            merged[source] = target
    return (
        dropped,
        merged,
        tuple(
            [drop_notes[id] for id in sorted(drop_notes)]
            + [merge_notes[id] for id in sorted(merge_notes)]
        ),
    )


def remap_overrides(
    overrides: Overrides, absorbed: dict[str, str]
) -> tuple[Overrides, tuple[str, ...]]:
    """Follow accepted LLM merges without changing handwritten lock rules.

    Colliding rules use the lowest original ID, except that a surviving
    element's own name and description take precedence over absorbed rules.
    """
    updates: dict[str, dict[str, str] | list[str]] = {
        "drop": sorted({absorbed.get(id, id) for id in overrides.drop})
    }
    notes: list[str] = []
    for field_name in ("merge", "names", "descriptions"):
        rules: dict[str, str] = getattr(overrides, field_name)
        remapped: dict[str, str] = {}
        ordered = sorted(
            rules,
            key=lambda id: (
                field_name != "merge" and absorbed.get(id, id) != id,
                id,
            ),
        )
        for source in ordered:
            target = absorbed.get(source, source)
            if target in remapped:
                notes.append(
                    f"C4-overrides: {field_name} ignored for {source} -> {target} "
                    "(conflict after merge)"
                )
                continue
            value = rules[source]
            remapped[target] = (
                absorbed.get(value, value) if field_name == "merge" else value
            )
        updates[field_name] = remapped
    return overrides.model_copy(update=updates), tuple(notes)


def _relation_targets(
    relations: dict[str, Relation], dropped: set[str], merged: dict[str, str]
) -> dict[str, str | None]:
    targets: dict[str, str | None] = {}
    for id, relation in relations.items():
        source = merged.get(relation.from_id, relation.from_id)
        target = merged.get(relation.to_id, relation.to_id)
        if relation.from_id in dropped or relation.to_id in dropped or source == target:
            targets[id] = None
        else:
            targets[id] = f"{source}->{target}"
    return targets


def _curated_relations(
    relations: dict[str, Relation],
    targets: dict[str, str | None],
    references: list[Reference],
    titles: dict[str, str],
) -> dict[str, Relation]:
    by_id: dict[str, list[Relation]] = defaultdict(list)
    for old_id, new_id in targets.items():
        if new_id is not None:
            by_id[new_id].append(relations[old_id])
    refs: dict[str, list[Reference]] = defaultdict(list)
    for reference in references:
        if reference.relation is not None:
            refs[reference.relation].append(reference)

    result: dict[str, Relation] = {}
    for id, originals in sorted(by_id.items()):
        if len(originals) == 1 and originals[0].id == id:
            result[id] = originals[0]
            continue
        preferred = min(originals, key=lambda r: (r.id != id, r.id))
        source, target = id.split("->", 1)
        title = preferred.title
        if refs[id]:
            fingerprint = relation_fingerprint(
                source, target, ((r.kind, r.to) for r in refs[id])
            )
            title = titles.get(
                id, titles.get(fingerprint, fallback_title(r.kind for r in refs[id]))
            )
        counts = Counter(originals[0].reference_counts)
        for relation in originals[1:]:
            counts.update(relation.reference_counts)
        result[id] = preferred.model_copy(
            update={
                "id": id,
                "from_id": source,
                "to_id": target,
                "title": title,
                "status": "found"
                if any(r.status == "found" for r in originals)
                else "documented",
                "reference_counts": dict(counts),
                "markers": sorted({m for r in originals for m in r.markers}),
            }
        )
    return result


def _curated_citations(
    citations: list[Citation],
    dropped: set[str],
    merged: dict[str, str],
    relation_targets: dict[str, str | None],
) -> list[Citation]:
    kept = []
    for citation in citations:
        target = citation.target
        if target in dropped:
            continue
        if target in relation_targets:
            target = relation_targets[target]
            if target is None:
                continue
        elif target is not None:
            target = merged.get(target, target)
        kept.append(citation.model_copy(update={"target": target}))
    return kept


def curate(
    state: CurationState,
    titles: dict[str, str],
    overrides: Overrides,
    *,
    prefix: str = "C4-overrides:",
) -> CurationState:
    """Validate against the original map, then apply all accepted entries at once.

    Reference destinations remain facts about the code. Only their relation IDs
    follow curation; removed relations leave those references unlinked.
    """
    elements, relations = state.elements, state.relations
    citations, references, files = state.citations, state.references, state.files
    dropped, merged, ignored = _validated(elements, overrides, prefix)
    kept_elements = {
        id: element.model_copy(deep=True)
        for id, element in elements.items()
        if id not in dropped and id not in merged
    }
    kept_files = {id: set(files[id]) for id in kept_elements}
    for source, target in merged.items():
        kept_elements[target].markers = sorted(
            set(kept_elements[target].markers) | set(elements[source].markers)
        )
        kept_files[target].update(files[source])

    relation_targets = _relation_targets(relations, dropped, merged)
    kept_references = [
        r.model_copy(update={"relation": relation_targets[r.relation]})
        if r.relation in relation_targets and relation_targets[r.relation] != r.relation
        else r
        for r in references
    ]
    kept_citations = _curated_citations(citations, dropped, merged, relation_targets)

    found = {c.target for c in kept_citations if c.source in {"code", "configuration"}}
    for element in kept_elements.values():
        element.status = "found" if element.id in found else "documented"
    return CurationState(
        elements=kept_elements,
        relations=_curated_relations(
            relations, relation_targets, kept_references, titles
        ),
        citations=kept_citations,
        references=kept_references,
        files={id: sorted(values) for id, values in kept_files.items()},
        ignored_overrides=state.ignored_overrides + ignored,
        absorbed=merged,
    )
