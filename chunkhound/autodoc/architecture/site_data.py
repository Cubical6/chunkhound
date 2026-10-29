"""JSON publication boundary shared by map navigation and the site search index."""

from typing import TypedDict
from urllib.parse import urlencode

from chunkhound.autodoc.architecture.coverage import CoverageIndex
from chunkhound.autodoc.architecture.likec4_ids import LikeC4IdAllocator
from chunkhound.autodoc.architecture.model import C4Model, ElementKind
from chunkhound.autodoc.architecture.views import (
    ViewSpec,
    component_view_id,
    focus_view_id,
)
from chunkhound.autodoc.models import DocsitePage


class ViewData(TypedDict):
    title: str
    level: str
    elementId: str | None


class ElementData(TypedDict):
    name: str
    kind: str
    description: str
    status: str | None
    focusView: str
    defaultView: str | None


class TopicData(TypedDict):
    view: str | None
    directElementIds: list[str]


class ArchitectureData(TypedDict):
    schemaVersion: int
    enabled: bool
    contextView: str
    views: dict[str, ViewData]
    elements: dict[str, ElementData]
    topics: dict[str, TopicData]


def build_site_data(
    *,
    model: C4Model | None,
    coverage: CoverageIndex | None,
    views: list[ViewSpec],
    ids: LikeC4IdAllocator | None,
    pages: list[DocsitePage],
) -> ArchitectureData:
    data: ArchitectureData = {
        "schemaVersion": 1,
        "enabled": False,
        "contextView": "index",
        "views": {},
        "elements": {},
        "topics": {},
    }
    if model is None or coverage is None or ids is None:
        return data
    data["enabled"] = True
    data["views"] = {
        view.view_id: {
            "title": view.title,
            "level": view.level.value,
            "elementId": view.scope_element_id,
        }
        for view in views
    }
    system = model.system
    data["elements"][system.id] = {
        "name": system.name,
        "kind": "softwareSystem",
        "description": system.description,
        "status": None,
        "focusView": focus_view_id(system.id),
        "defaultView": "containers",
    }
    for element in model.elements:
        data["elements"][element.id] = {
            "name": element.name,
            "kind": element.kind.value,
            "description": element.description,
            "status": element.status.value,
            "focusView": focus_view_id(element.id),
            "defaultView": component_view_id(element.id)
            if element.kind == ElementKind.CONTAINER
            else None,
        }
    for page in pages:
        direct = coverage.direct_elements_for(page)
        data["topics"][page.slug] = {
            "view": "topic_" + page.slug if direct else None,
            "directElementIds": direct,
        }
    return data


def build_search_records(
    *, model: C4Model, data: ArchitectureData
) -> list[dict[str, str]]:
    records = []
    for element in model.elements:
        published = data["elements"][element.id]
        records.append(
            {
                "title": published["name"],
                "slug": published["focusView"],
                "description": published["description"],
                "body": " ".join(
                    (
                        published["name"],
                        published["kind"],
                        published["description"],
                        published["status"] or "",
                    )
                ),
                "url": "/architecture/?" + urlencode({"view": published["focusView"]}),
            }
        )
    return records
