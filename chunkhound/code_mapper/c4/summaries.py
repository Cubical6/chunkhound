"""Deterministic C4 view projections and cached, bounded presentation labels."""

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from chunkhound.code_mapper.c4.llm import (
    AnswerRejectedError,
    C4Llm,
    RetryQueue,
    TransientStepError,
    load_c4_prompt,
)
from chunkhound.code_mapper.c4.model import Element, Marker, MergedArrow, Relation


class SummariesAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    labels: dict[str, Annotated[str, Field(min_length=1, max_length=60)]]


def summary_key(underlying: Iterable[tuple[str, str]]) -> str:
    payload = json.dumps(sorted(set(underlying)), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def fallback_label(titles: Sequence[str]) -> str:
    unique = sorted(set(titles))
    joined = "; ".join(unique)
    if len(joined) <= 60:
        return joined
    suffix = f" (+{len(unique) - 1})" if len(unique) > 1 else ""
    return unique[0][: 60 - len(suffix)] + suffix


def _project(id: str, visible: set[str], elements: Mapping[str, Element]) -> str | None:
    while id not in visible:
        parent = elements[id].parent
        if parent is None:
            return None
        id = parent
    return id


def _view_arrows(
    view: str,
    visible: set[str],
    elements: Mapping[str, Element],
    relations: Sequence[Relation],
) -> list[MergedArrow]:
    underlying: dict[tuple[str, str], set[str]] = defaultdict(set)
    markers: dict[tuple[str, str], set[Marker]] = defaultdict(set)
    for relation in relations:
        source = _project(relation.from_id, visible, elements)
        target = _project(relation.to_id, visible, elements)
        if source is None or target is None or source == target:
            continue
        underlying[source, target].add(relation.id)
        markers[source, target].update(relation.markers)
    return [
        MergedArrow.model_validate(
            {
                "id": f"{view}:{source}->{target}",
                "view": view,
                "from": source,
                "to": target,
                "label": "",
                "underlying": sorted(ids),
                "markers": sorted(markers[source, target]),
            }
        )
        for (source, target), ids in sorted(underlying.items())
    ]


def derive_views(
    elements: Sequence[Element], relations: Sequence[Relation]
) -> list[MergedArrow]:
    by_id = {e.id: e for e in elements}
    context = {e.id for e in elements if e.kind in {"system", "person", "external"}}
    containers = {
        e.id for e in elements if e.kind != "component" and e.kind != "system"
    }
    views = {"context": context, "containers": containers}
    for element in elements:
        if element.kind == "container":
            views[f"components:{element.id}"] = (containers - {element.id}) | {
                e.id
                for e in elements
                if e.kind == "component" and e.parent == element.id
            }
    return [
        arrow
        for view, visible in sorted(views.items())
        for arrow in _view_arrows(view, visible, by_id, relations)
    ]


def _prepare_labels(
    arrows: list[MergedArrow],
    titles_by_relation: Mapping[str, str],
    locked: Mapping[str, str],
    overrides: Mapping[str, str],
) -> tuple[dict[str, list[MergedArrow]], dict[str, list[str]]]:
    pending: dict[str, list[MergedArrow]] = defaultdict(list)
    titles: dict[str, list[str]] = {}
    for arrow in arrows:
        pairs = [(id, titles_by_relation[id]) for id in arrow.underlying]
        key = summary_key(pairs)
        unique = sorted({title for _, title in pairs})
        if arrow.id in overrides:
            arrow.label = overrides[arrow.id]
        elif key in locked:
            arrow.label = locked[key]
        elif len(unique) <= 1:
            arrow.label = fallback_label(unique)
        else:
            pending[key].append(arrow)
            titles[key] = unique
    return pending, titles


def _apply_labels(
    pending: Mapping[str, Sequence[MergedArrow]],
    labels: Mapping[str, str],
    marker: Marker | None,
) -> None:
    for key, group in pending.items():
        for arrow in group:
            arrow.label = labels[key]
            if marker is not None and marker not in arrow.markers:
                arrow.markers.append(marker)
                arrow.markers.sort()


async def label_arrows(
    arrows: list[MergedArrow],
    *,
    titles_by_relation: Mapping[str, str],
    locked: Mapping[str, str],
    overrides: Mapping[str, str],
    llm: C4Llm,
    retries: RetryQueue,
) -> list[MergedArrow]:
    """Batch distinct uncached sets once per run. Drain retries before consuming.

    The returned list is mutated by delayed retry application. Fallback/trial
    markers identify labels the caller must not persist in the summary cache.
    """
    pending, titles = _prepare_labels(arrows, titles_by_relation, locked, overrides)
    if not pending:
        return arrows

    def apply(labels: Mapping[str, str], marker: Marker | None = None) -> None:
        _apply_labels(pending, labels, marker)

    def fallback() -> dict[str, str]:
        return {key: fallback_label(value) for key, value in titles.items()}

    if llm.trial:
        apply(fallback(), "trial")
        return arrows
    prompt = (
        load_c4_prompt("summaries")
        + "\nInput:\n"
        + json.dumps(
            {
                "arrows": [
                    {"key": key, "titles": titles[key]} for key in sorted(pending)
                ]
            },
            ensure_ascii=False,
        )
    )

    async def attempt() -> dict[str, str]:
        answer = await llm.call(
            "summaries", SummariesAnswer, prompt, provider="utility"
        )
        if set(answer.labels) != set(pending) or any(
            not value.strip() for value in answer.labels.values()
        ):
            raise AnswerRejectedError(
                "summaries: exactly one nonblank label per supplied key required"
            )
        return answer.labels

    def applied(labels: dict[str, str], failed: bool) -> None:
        apply(labels, "fallback" if failed else None)

    try:
        applied(await attempt(), False)
    except TransientStepError:
        retries.defer("summaries", attempt, fallback, applied)
    return arrows
