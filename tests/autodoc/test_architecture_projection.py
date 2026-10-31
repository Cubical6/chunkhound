"""Published map/search data preserves identity and final topic navigation."""

import json
from pathlib import Path

from chunkhound.autodoc.architecture.coverage import CoverageIndex
from chunkhound.autodoc.architecture.likec4_ids import LikeC4IdAllocator
from chunkhound.autodoc.architecture.model import (
    C4Model,
    CoveredElement,
    Element,
    ElementKind,
    Relation,
    SoftwareSystem,
    Status,
    TopicCoverage,
)
from chunkhound.autodoc.architecture.site_data import (
    build_search_records,
    build_site_data,
)
from chunkhound.autodoc.architecture.views import build_views
from chunkhound.autodoc.models import DocsitePage


def test_site_records_use_final_urls_and_exclude_relations(tmp_path: Path) -> None:
    """Rolled-up parents must not become topic targets or relation search hits."""
    page = DocsitePage(
        1, "Final title", "final-topic-2", "", "", str(tmp_path / "old.md")
    )
    uncovered = DocsitePage(2, "No coverage", "uncovered", "", "")
    model = C4Model(
        1,
        SoftwareSystem("system", "Our system", "System description"),
        elements=[
            Element(
                "container",
                ElementKind.CONTAINER,
                "system",
                "App",
                "Runs app",
                "",
                Status.AANGETROFFEN,
                [],
                [],
            ),
            Element(
                "component",
                ElementKind.COMPONENT,
                "container",
                "API",
                "Serves API",
                "",
                Status.AANGETROFFEN,
                ["api.py"],
                [],
            ),
            Element(
                "person",
                ElementKind.PERSON,
                None,
                "Reader",
                "Reads docs",
                "",
                Status.GEDOCUMENTEERD,
                [],
                [],
            ),
            Element(
                "external",
                ElementKind.EXTERNAL_SYSTEM,
                None,
                "Provider",
                "External service",
                "",
                Status.GEDOCUMENTEERD,
                [],
                [],
            ),
        ],
        relations=[
            Relation(
                "relation",
                "component",
                "external",
                "Calls provider",
                "",
                Status.AANGETROFFEN,
                [],
            )
        ],
        topics=[TopicCoverage("old.md", [CoveredElement("component", ["api.py"])])],
    )
    pages = [page, uncovered]
    coverage = CoverageIndex(model, pages, tmp_path)
    ids = LikeC4IdAllocator(model)
    views = build_views(model=model, coverage=coverage, pages=pages, ids=ids)
    data = json.loads(
        json.dumps(
            build_site_data(
                model=model, coverage=coverage, views=views, ids=ids, pages=pages
            )
        )
    )
    records = build_search_records(model=model, data=data)

    assert data["schemaVersion"] == 1
    assert data["enabled"] is True
    assert data["contextView"] == "index"
    assert set(data["elements"]) == {
        "system",
        "container",
        "component",
        "person",
        "external",
    }
    assert data["elements"]["system"]["status"] is None
    assert data["elements"]["component"] == {
        "name": "API",
        "kind": "component",
        "description": "Serves API",
        "status": "aangetroffen",
        "focusView": "focus_636f6d706f6e656e74",
        "defaultView": None,
    }
    assert data["elements"]["system"]["defaultView"] == "containers"
    assert (
        data["elements"]["container"]["defaultView"] == "components_636f6e7461696e6572"
    )
    assert data["topics"][page.slug] == {
        "directElementIds": ["component"],
        "view": "topic_final-topic-2",
    }
    assert data["topics"][uncovered.slug] == {"directElementIds": [], "view": None}
    assert data["elements"]["component"]["focusView"] in data["views"]
    assert data["views"]["topic_final-topic-2"] == {
        "title": "Final title",
        "level": "topic",
        "elementId": None,
    }
    assert {r["url"] for r in records} == {
        "/architecture/?view=focus_636f6e7461696e6572",
        "/architecture/?view=focus_636f6d706f6e656e74",
        "/architecture/?view=focus_706572736f6e",
        "/architecture/?view=focus_65787465726e616c",
    }
    assert {r["title"] for r in records} == {"App", "API", "Reader", "Provider"}
    api = next(r for r in records if r["title"] == "API")
    assert api["description"] == "Serves API"
    assert "component" in api["body"]
    assert "aangetroffen" in api["body"]


def test_disabled_site_data_has_no_partial_map() -> None:
    assert build_site_data(model=None, coverage=None, views=[], ids=None, pages=[]) == {
        "schemaVersion": 1,
        "enabled": False,
        "contextView": "index",
        "views": {},
        "elements": {},
        "topics": {},
    }
