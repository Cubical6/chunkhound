"""Serialize the neutral model to the pinned LikeC4 DSL and native detail schema."""

import json
from pathlib import Path
from urllib.parse import quote

from chunkhound.autodoc.architecture.coverage import CoverageIndex
from chunkhound.autodoc.architecture.likec4_ids import LikeC4IdAllocator
from chunkhound.autodoc.architecture.model import (
    C4Model,
    Element,
    ElementKind,
    Relation,
    SoftwareSystem,
    Source,
    Status,
)
from chunkhound.autodoc.architecture.source_links import SourceLinkBuilder
from chunkhound.autodoc.architecture.views import (
    ViewSpec,
    component_view_id,
    focus_view_id,
    project_relations,
)

_KINDS = {
    "softwareSystem": "Software system",
    "container": "Container",
    "component": "Component",
    "person": "Person",
    "externalSystem": "External system",
}
_LEGEND = (
    "C4: Software system / Container / Component; Person / External system. "
    "Muted: documented. Solid: found; dotted: documented. "
    "Dashed aggregate: inspect individual relationship statuses."
)


def _text(value: str) -> str:
    # Langium strings accept basic escapes but not JSON's \\uXXXX escapes.
    return json.dumps(value, ensure_ascii=False)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _label(model: C4Model, source: str, target: str, relations: list[Relation]) -> str:
    titles = sorted({relation.title for relation in relations})
    if len(titles) == 1:
        return titles[0][:60]
    relation_ids = {relation.id for relation in relations}
    for label in model.merged_labels:
        if label.source_id != source or label.target_id != target:
            continue
        if set(label.relation_ids) != relation_ids:
            continue
        if not label.label.strip() or len(label.label) > 60:
            continue
        if "[...]" not in label.label:
            return label.label
    if len(titles) == 2:
        # Keep both titles represented even when the left one is very long.
        left = min(len(titles[0]), 28)
        right = min(len(titles[1]), 57 - left)
        left = min(len(titles[0]), 57 - right)
        return titles[0][:left] + " · " + titles[1][:right]
    suffix = f" +{len(titles) - 1} relations"
    return titles[0][: 60 - len(suffix)] + suffix


class LikeC4Writer:
    def __init__(
        self,
        *,
        coverage: CoverageIndex,
        ids: LikeC4IdAllocator,
        source_links: SourceLinkBuilder,
    ) -> None:
        self._coverage = coverage
        self._ids = ids
        self._source_links = source_links

    def write(self, model: C4Model, views: list[ViewSpec], out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "specification.c4").write_text(
            self._specification(), encoding="utf-8"
        )
        (out_dir / "model.c4").write_text(self._model(model), encoding="utf-8")
        (out_dir / "views.c4").write_text(self._views(model, views), encoding="utf-8")

    def _specification(self) -> str:
        lines = ["specification {", "  tag documented"]
        for kind, title in _KINDS.items():
            shape = (
                "person"
                if kind == "person"
                else "component"
                if kind == "component"
                else "rectangle"
            )
            lines.extend(
                [
                    f"  element {kind} {{",
                    f"    notation {_text(title)}",
                    f"    style {{ shape {shape} }}",
                    "  }",
                ]
            )
        return "\n".join(lines + ["}", ""])

    def _sources(
        self, source_ids: list[str], sources: dict[str, Source]
    ) -> list[dict[str, object]]:
        return [
            {
                "kind": sources[source_id].kind.value,
                "path": sources[source_id].path,
                "startLine": sources[source_id].start_line,
                "endLine": sources[source_id].end_line,
                "url": self._source_links.link(sources[source_id]),
            }
            for source_id in source_ids
        ]

    def _metadata(self, neutral_id: str, detail: dict[str, object]) -> list[str]:
        sources = detail["sources"]
        assert isinstance(sources, list)
        topics = detail.get("topics", [])
        assert isinstance(topics, list)
        lines = [
            "metadata {",
            f"  chunkhound_id {_text(neutral_id)}",
            f"  chunkhound_detail {_text(_json({'version': 1, **detail}))}",
        ]
        readable = "\n".join(
            f"{source['kind']}: {source['path']}:"
            f"{source['startLine']}-{source['endLine']}"
            for source in sources
        )
        lines.append(f"  sources {_text(readable)}")
        lines.append(f"  topics {_text(_json(topics))}")
        lines.append("}")
        for source in sources:
            if source["url"] is not None:
                lines.append(f"link {source['url']} {_text(str(source['path']))}")
        for topic in topics:
            lines.append(f"link {topic['url']} {_text(str(topic['title']))}")
        return lines

    def _element_detail(
        self, element: SoftwareSystem | Element, sources: dict[str, Source]
    ) -> dict[str, object]:
        default_view: str | None
        if isinstance(element, SoftwareSystem):
            kind, status, element_sources, default_view = (
                "softwareSystem",
                None,
                [],
                "containers",
            )
        else:
            kind = element.kind.value
            status = element.status.value
            element_sources = self._sources(element.source_ids, sources)
            default_view = (
                component_view_id(element.id)
                if element.kind == ElementKind.CONTAINER
                else None
            )
        return {
            "kind": kind,
            "status": status,
            "sources": element_sources,
            "topics": [
                {
                    "title": page.title,
                    "url": f"/topics/{quote(page.slug, safe='')}/",
                    "weight": len(files),
                }
                for page, files in self._coverage.topics_for(element.id)
            ],
            "focusView": focus_view_id(element.id),
            "defaultView": default_view,
        }

    def _model(self, model: C4Model) -> str:
        sources = {source.id: source for source in model.sources}
        children: dict[str | None, list[SoftwareSystem | Element]] = {
            None: [model.system]
        }
        for element in model.elements:
            children.setdefault(element.parent_id, []).append(element)
        lines = ["model {"]

        def emit(element: SoftwareSystem | Element, indent: str) -> None:
            detail = self._element_detail(element, sources)
            documented = detail["status"] == Status.DOCUMENTED.value
            lines.append(
                f"{indent}{self._ids.allocate(element)} = "
                f"{detail['kind']} {_text(element.name)} {{"
            )
            props = ["#documented"] if documented else []
            props.append(f"description {_text(element.description)}")
            if isinstance(element, Element) and element.technology:
                props.append(f"technology {_text(element.technology)}")
            if documented:
                props.append("style { color muted }")
            props.extend(self._metadata(element.id, detail))
            lines.extend(indent + "  " + prop for prop in props)
            for child in sorted(children.get(element.id, []), key=lambda item: item.id):
                emit(child, indent + "  ")
            lines.append(indent + "}")

        for root in sorted(children[None], key=lambda item: item.id):
            emit(root, "  ")
        elements: dict[str, SoftwareSystem | Element] = {model.system.id: model.system}
        elements.update((element.id, element) for element in model.elements)
        for relation in model.relations:
            endpoints = {
                key: {
                    "id": element_id,
                    "fqn": self._ids.fqn(element_id),
                    "title": elements[element_id].name,
                }
                for key, element_id in (
                    ("source", relation.source_id),
                    ("target", relation.target_id),
                )
            }
            detail: dict[str, object] = {
                "status": relation.status.value,
                "sources": self._sources(relation.source_ids, sources),
                **endpoints,
            }
            lines.append(
                f"  {self._ids.fqn(relation.source_id)} -> "
                f"{self._ids.fqn(relation.target_id)} {_text(relation.title)} {{"
            )
            props = [f"technology {_text(relation.technology)}"]
            line = "dotted" if relation.status == Status.DOCUMENTED else "solid"
            props.append(f"style {{ line {line} }}")
            props.extend(self._metadata(relation.id, detail))
            lines.extend("    " + prop for prop in props)
            lines.append("  }")
        return "\n".join(lines + ["}", ""])

    def _edge_override(
        self, model: C4Model, source: str, target: str, relations: list[Relation]
    ) -> str:
        statuses = {relation.status for relation in relations}
        line = "dotted" if Status.DOCUMENTED in statuses else "solid"
        notation = next(iter(statuses)).value
        if len(statuses) > 1:
            line = "dashed"
            notation = "Individual statuses in details"
        title = _text(_label(model, source, target, relations))
        return f"with {{ title {title} line {line} notation {_text(notation)} }}"

    def _edge_expression(
        self, source: str, target: str, relations: list[Relation], visible: set[str]
    ) -> str:
        source_fqn, target_fqn = self._ids.fqn(source), self._ids.fqn(target)
        expanded_source = any(
            self._ids.fqn(node).startswith(source_fqn + ".") for node in visible
        )
        if expanded_source and all(
            relation.source_id == source and relation.target_id == target
            for relation in relations
        ):
            # The native exact-pair matcher expands parent boundaries to leaves.
            # A finite ID-filtered outgoing predicate retains a direct boundary edge.
            return source_fqn + " -> *"
        expanded_target = any(
            self._ids.fqn(node).startswith(target_fqn + ".") for node in visible
        )
        if expanded_target and all(
            relation.source_id == source and relation.target_id == target
            for relation in relations
        ):
            return "* -> " + target_fqn
        return source_fqn + " -> " + target_fqn

    def _view_rules(
        self, model: C4Model, view: ViewSpec, by_fqn: dict[str, str]
    ) -> list[str]:
        visible = {
            by_fqn[rule.removeprefix("include ")]
            for rule in view.include_rules
            if rule.removeprefix("include ") in by_fqn
        }
        lines = []
        documented = {
            element.id: _KINDS[element.kind.value] + " — documented"
            for element in model.elements
            if element.status == Status.DOCUMENTED
        }
        for element_id in sorted(visible):
            rule = "include " + self._ids.fqn(element_id)
            if element_id in documented:
                rule += f" with {{ notation {_text(documented[element_id])} }}"
            lines.append("    " + rule)
        # Includes also expose implicit ancestor edges. Clear finite neutral IDs,
        # including parent-boundary relations, before adding the selected IDs.
        for relation in model.relations:
            lines.append(
                f"    exclude {self._ids.fqn(relation.source_id)} -> * where "
                f"metadata.chunkhound_id = {_text(relation.id)}"
            )
        pairs = project_relations(model, visible, view.relation_ids)
        for (source, target), relations in pairs.items():
            expression = self._edge_expression(source, target, relations, visible)
            predicate = " or ".join(
                f"metadata.chunkhound_id = {_text(relation.id)}"
                for relation in relations
            )
            override = self._edge_override(model, source, target, relations)
            lines.append(f"    include {expression} where {predicate} {override}")
        return lines

    def _views(self, model: C4Model, views: list[ViewSpec]) -> str:
        by_fqn = {self._ids.fqn(e.id): e.id for e in model.elements}
        by_fqn[self._ids.fqn(model.system.id)] = model.system.id
        lines = ["views {"]
        for view in views:
            scoped = view.level.value in ("container", "component")
            scope = (
                " of " + self._ids.fqn(view.scope_element_id)
                if scoped and view.scope_element_id
                else ""
            )
            lines.extend(
                [
                    f"  view {view.view_id}{scope} {{",
                    f"    title {_text(view.title or view.view_id)}",
                    f"    description {_text(_LEGEND)}",
                ]
            )
            lines.extend(self._view_rules(model, view, by_fqn))
            lines.append("  }")
        return "\n".join(lines + ["}", ""])
