"""Finite C4 projections with explicit nodes and directed relationship predicates."""

from dataclasses import dataclass
from enum import Enum

from chunkhound.autodoc.architecture.coverage import CoverageIndex
from chunkhound.autodoc.architecture.likec4_ids import LikeC4IdAllocator
from chunkhound.autodoc.architecture.model import C4Model, ElementKind, Relation
from chunkhound.autodoc.models import DocsitePage


class ViewLevel(str, Enum):
    SYSTEM_CONTEXT = "context"
    CONTAINER = "container"
    COMPONENT = "component"
    FOCUS = "focus"
    TOPIC = "topic"


@dataclass
class ViewSpec:
    view_id: str
    level: ViewLevel
    scope_element_id: str | None
    include_rules: list[str]
    title: str = ""
    # None selects all model relationships; [] deliberately selects none.
    relation_ids: list[str] | None = None


def focus_view_id(element_id: str) -> str:
    return "focus_" + element_id.encode("utf-8").hex()


def component_view_id(container_id: str) -> str:
    return "components_" + container_id.encode("utf-8").hex()


def _contains(parents: dict[str, str | None], ancestor: str, descendant: str) -> bool:
    parent = parents[descendant]
    while parent is not None:
        if parent == ancestor:
            return True
        parent = parents[parent]
    return False


def project_relations(
    model: C4Model, visible: set[str], relation_ids: list[str] | None = None
) -> dict[tuple[str, str], list[Relation]]:
    """Map endpoints to their deepest visible ancestor, keeping every relationship."""
    parents = {element.id: element.parent_id for element in model.elements}
    parents[model.system.id] = None

    def project(element_id: str) -> str | None:
        current: str | None = element_id
        while current is not None and current not in visible:
            current = parents[current]
        return current

    pairs: dict[tuple[str, str], list[Relation]] = {}
    selected = set(relation_ids) if relation_ids is not None else None
    for relation in model.relations:
        if selected is not None and relation.id not in selected:
            continue
        source, target = project(relation.source_id), project(relation.target_id)
        if source is None or target is None or source == target:
            continue
        # Native LikeC4 omits edges within the same parent/child hierarchy.
        if _contains(parents, source, target) or _contains(parents, target, source):
            continue
        pairs.setdefault((source, target), []).append(relation)
    return pairs


def _rules(
    model: C4Model,
    ids: LikeC4IdAllocator,
    visible: set[str],
    targets: set[str] | None = None,
) -> list[str]:
    rules = ["include " + ids.fqn(element_id) for element_id in sorted(visible)]
    for source, target in sorted(project_relations(model, visible)):
        # Node includes implicitly add edges. Explicitly remove neighbor-to-neighbor
        # edges so focus/topic views show only relationships incident to a target.
        action = (
            "include" if targets is None or {source, target} & targets else "exclude"
        )
        rules.append(f"{action} {ids.fqn(source)} -> {ids.fqn(target)}")
    return rules


def _neighbors(model: C4Model, targets: set[str]) -> set[str]:
    neighbors = set(targets)
    for relation in model.relations:
        if relation.source_id in targets:
            neighbors.add(relation.target_id)
        if relation.target_id in targets:
            neighbors.add(relation.source_id)
    return neighbors


def _incident_relations(model: C4Model, targets: set[str]) -> list[str]:
    return [
        relation.id
        for relation in model.relations
        if relation.source_id in targets or relation.target_id in targets
    ]


def _container_nodes(model: C4Model, containers: set[str]) -> set[str]:
    outside = {e.id for e in model.elements if e.parent_id is None}
    internal = {model.system.id} | {e.id for e in model.elements if e.parent_id}
    return containers | {model.system.id} | (_neighbors(model, internal) & outside)


def _component_nodes(model: C4Model, targets: set[str]) -> set[str]:
    # Components in other containers are collapsed to their container.
    projected = {
        e.id: e.parent_id
        for e in model.elements
        if e.kind == ElementKind.COMPONENT
        and e.id not in targets
        and e.parent_id is not None
    }
    return {projected.get(node, node) for node in _neighbors(model, targets)}


def build_views(
    *,
    model: C4Model,
    coverage: CoverageIndex,
    pages: list[DocsitePage],
    ids: LikeC4IdAllocator,
) -> list[ViewSpec]:
    system = model.system.id
    elements = {element.id: element for element in model.elements}
    containers = {e.id for e in model.elements if e.kind == ElementKind.CONTAINER}
    outside = {e.id for e in model.elements if e.parent_id is None}
    views = [
        ViewSpec(
            "index",
            ViewLevel.SYSTEM_CONTEXT,
            None,
            _rules(model, ids, {system} | outside),
            model.system.name,
        ),
    ]
    container_visible = _container_nodes(model, containers)
    views.append(
        ViewSpec(
            "containers",
            ViewLevel.CONTAINER,
            system,
            _rules(model, ids, container_visible),
            model.system.name + " — Containers",
        )
    )

    for container in sorted(containers):
        children = {e.id for e in model.elements if e.parent_id == container}
        targets = children | {container}
        visible = _component_nodes(model, targets)
        views.append(
            ViewSpec(
                component_view_id(container),
                ViewLevel.COMPONENT,
                container,
                _rules(model, ids, visible, targets),
                elements[container].name + " — Components",
                _incident_relations(model, targets),
            )
        )

    for element_id in sorted({system} | set(elements)):
        name = model.system.name if element_id == system else elements[element_id].name
        rules = _rules(model, ids, _neighbors(model, {element_id}), {element_id})
        views.append(
            ViewSpec(
                focus_view_id(element_id),
                ViewLevel.FOCUS,
                element_id,
                rules,
                name + " — Focus",
                _incident_relations(model, {element_id}),
            )
        )
    for page in pages:
        direct = set(coverage.direct_elements_for(page))
        if direct:
            rules = _rules(model, ids, _neighbors(model, direct), direct)
            views.append(
                ViewSpec(
                    "topic_" + page.slug,
                    ViewLevel.TOPIC,
                    None,
                    rules,
                    page.title,
                    _incident_relations(model, direct),
                )
            )
    return views
