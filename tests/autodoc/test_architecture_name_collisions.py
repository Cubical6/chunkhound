"""Nested element names must not shadow root references in the pinned LikeC4 fork."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from chunkhound.autodoc.architecture.coverage import CoverageIndex
from chunkhound.autodoc.architecture.likec4_ids import LikeC4IdAllocator
from chunkhound.autodoc.architecture.likec4_writer import LikeC4Writer
from chunkhound.autodoc.architecture.model import (
    C4Model,
    Element,
    ElementKind,
    Relation,
    SoftwareSystem,
    Status,
)
from chunkhound.autodoc.architecture.source_links import SourceLinkBuilder
from chunkhound.autodoc.architecture.views import (
    build_views,
    component_view_id,
    focus_view_id,
)

_ARCHIVE = (
    Path(__file__).parents[2]
    / "chunkhound/autodoc/assets/vendor/likec4/likec4-1.60.0-chunkhound.2.tgz"
)
_NETWORK_FAILURE = re.compile(
    r"\b(ENOTFOUND|EAI_AGAIN|ETIMEDOUT|ECONNREFUSED|ECONNRESET|"
    r"ENETUNREACH|EHOSTUNREACH)\b"
)

requires_fork = pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("npm") is None,
    reason="node and npm required",
)


def _system(name: str) -> SoftwareSystem:
    return SoftwareSystem("system", name, f"{name} description")


def _element(
    element_id: str, kind: ElementKind, parent_id: str | None, name: str
) -> Element:
    status = Status.FOUND if parent_id else Status.DOCUMENTED
    return Element(
        element_id, kind, parent_id, name, f"{name} description", "", status, [], []
    )


def _container(element_id: str, name: str) -> Element:
    return _element(element_id, ElementKind.CONTAINER, "system", name)


def _component(element_id: str, parent_id: str, name: str) -> Element:
    return _element(element_id, ElementKind.COMPONENT, parent_id, name)


def _relation(relation_id: str, source_id: str, target_id: str, title: str) -> Relation:
    return Relation(
        relation_id, source_id, target_id, title, "", Status.FOUND, []
    )


def test_child_named_like_a_root_element_gets_a_different_id() -> None:
    model = C4Model(
        1,
        _system("Shop"),
        elements=[
            _element("person", ElementKind.PERSON, None, "Reader"),
            _element("external", ElementKind.EXTERNAL_SYSTEM, None, "Provider"),
            _container("main", "Shop"),
            _container("next", "Shop 2"),
            _component("inner-external", "main", "Provider"),
            _component("inner-person", "next", "Reader"),
        ],
    )

    ids = LikeC4IdAllocator(model)

    assert {
        element_id: ids.fqn(element_id)
        for element_id in (
            "system",
            "person",
            "external",
            "main",
            "next",
            "inner-external",
            "inner-person",
        )
    } == {
        "system": "shop",
        "person": "reader",
        "external": "provider",
        # A suffix must not take the natural name of a sibling.
        "main": "shop.shop-3",
        "next": "shop.shop-2",
        "inner-external": "shop.shop-3.provider-2",
        "inner-person": "shop.shop-2.reader-2",
    }


def test_ids_without_a_root_collision_stay_the_same(tmp_path: Path) -> None:
    model = C4Model(
        1,
        _system("Our System"),
        elements=[
            _element("person", ElementKind.PERSON, None, "Reader"),
            _element("external", ElementKind.EXTERNAL_SYSTEM, None, "Provider"),
            _container("app", "App"),
            _container("db", "Db"),
            # A component named like its container does not shadow a root reference.
            _component("app-component", "app", "App"),
            _component("api-1", "app", "API"),
            _component("api-2", "app", "API"),
            _component("api-3", "db", "API"),
            _component("keyword", "app", "Model"),
        ],
    )

    ids = LikeC4IdAllocator(model)
    views = build_views(
        model=model, coverage=CoverageIndex(model, [], tmp_path), pages=[], ids=ids
    )

    assert {element.id: ids.fqn(element.id) for element in model.elements} == {
        "person": "reader",
        "external": "provider",
        "app": "our-system.app",
        "db": "our-system.db",
        "app-component": "our-system.app.app",
        "api-1": "our-system.app.api",
        "api-2": "our-system.app.api-2",
        "api-3": "our-system.db.api",
        "keyword": "our-system.app.e-model",
    }
    assert {view.view_id for view in views} >= {
        "index",
        "containers",
        "components_617070",
        "focus_6170692d31",
    }


@pytest.fixture(scope="module")
def likec4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The executable of the vendored fork, installed like a generated site does."""
    npm = shutil.which("npm")
    assert npm is not None
    root = tmp_path_factory.mktemp("likec4-fork")
    (root / "package.json").write_text('{"private": true}\n', encoding="utf-8")
    try:
        result = subprocess.run(
            [
                npm,
                "install",
                "--no-audit",
                "--no-fund",
                # Retries stall an offline run for minutes before it can skip.
                "--fetch-retries=0",
                str(_ARCHIVE),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("npm install of the likec4 archive timed out")
    network_failure = _NETWORK_FAILURE.search(result.stderr)
    if result.returncode != 0 and network_failure:
        pytest.skip(f"npm has no network: {network_failure.group(1)}")
    assert result.returncode == 0, result.stdout + result.stderr
    executable = shutil.which("likec4", path=str(root / "node_modules/.bin"))
    assert executable is not None
    return Path(executable)


def _write_model(model: C4Model, out_dir: Path) -> None:
    coverage = CoverageIndex(model, [], out_dir)
    ids = LikeC4IdAllocator(model)
    views = build_views(model=model, coverage=coverage, pages=[], ids=ids)
    LikeC4Writer(
        coverage=coverage, ids=ids, source_links=SourceLinkBuilder(model)
    ).write(model, views, out_dir)


def _run(likec4: Path, *args: str, cwd: Path) -> None:
    result = subprocess.run(
        [str(likec4), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _validated_views(likec4: Path, model: C4Model, tmp_path: Path) -> dict:
    """Validate and build the writer's output and return its exported views."""
    source = tmp_path / "source"
    _write_model(model, source)
    _run(likec4, "validate", str(source), cwd=tmp_path)
    _run(likec4, "build", "-o", str(tmp_path / "site"), str(source), cwd=tmp_path)
    assert (tmp_path / "site/index.html").is_file()
    exported = tmp_path / "likec4.json"
    _run(
        likec4,
        "export",
        "json",
        "--skip-layout",
        "-o",
        str(exported),
        str(source),
        cwd=tmp_path,
    )
    return json.loads(exported.read_text(encoding="utf-8"))["views"]


def _graph(view: dict) -> tuple[set[str], set[tuple[str, str, str]]]:
    return (
        {node["id"] for node in view["nodes"]},
        {(edge["source"], edge["target"], edge["label"]) for edge in view["edges"]},
    )


@requires_fork
@pytest.mark.slow
@pytest.mark.timeout(600)
@pytest.mark.xdist_group(name="likec4_fork")
def test_system_and_container_with_the_same_name_validate_and_build(
    likec4: Path, tmp_path: Path
) -> None:
    model = C4Model(
        1,
        _system("ChunkHound"),
        elements=[
            _container("main", "ChunkHound"),
            _container("site", "Site"),
            _component("indexer", "main", "Indexer"),
            _component("search", "main", "Search"),
            _component("page", "site", "Site"),
        ],
        relations=[
            _relation("queries", "search", "indexer", "queries"),
            _relation("calls", "page", "search", "calls"),
        ],
    )

    views = _validated_views(likec4, model, tmp_path)

    assert _graph(views["containers"]) == (
        {"chunkhound", "chunkhound.chunkhound-2", "chunkhound.site"},
        {("chunkhound.site", "chunkhound.chunkhound-2", "calls")},
    )
    assert _graph(views[component_view_id("main")]) == (
        {
            "chunkhound.chunkhound-2",
            "chunkhound.chunkhound-2.indexer",
            "chunkhound.chunkhound-2.search",
            "chunkhound.site",
        },
        {
            (
                "chunkhound.chunkhound-2.search",
                "chunkhound.chunkhound-2.indexer",
                "queries",
            ),
            ("chunkhound.site", "chunkhound.chunkhound-2.search", "calls"),
        },
    )


@requires_fork
@pytest.mark.slow
@pytest.mark.timeout(600)
@pytest.mark.xdist_group(name="likec4_fork")
def test_child_named_like_external_or_person_keeps_views_correct(
    likec4: Path, tmp_path: Path
) -> None:
    model = C4Model(
        1,
        _system("Shop"),
        elements=[
            _element("person", ElementKind.PERSON, None, "Reader"),
            _element("external", ElementKind.EXTERNAL_SYSTEM, None, "Provider"),
            _container("web", "Web"),
            _component("api", "web", "Api"),
            _component("inner-external", "web", "Provider"),
            _component("inner-person", "web", "Reader"),
        ],
        relations=[
            _relation("calls", "api", "external", "calls external"),
            _relation("uses", "person", "api", "uses"),
            _relation("delegates", "api", "inner-external", "calls inner"),
            _relation("reads", "inner-person", "api", "reads"),
        ],
    )

    views = _validated_views(likec4, model, tmp_path)

    assert _graph(views["containers"]) == (
        {"shop", "shop.web", "provider", "reader"},
        {
            ("shop.web", "provider", "calls external"),
            ("reader", "shop.web", "uses"),
        },
    )
    assert _graph(views[component_view_id("web")]) == (
        {
            "shop.web",
            "shop.web.api",
            "shop.web.provider-2",
            "shop.web.reader-2",
            "provider",
            "reader",
        },
        {
            ("shop.web.api", "provider", "calls external"),
            ("reader", "shop.web.api", "uses"),
            ("shop.web.api", "shop.web.provider-2", "calls inner"),
            ("shop.web.reader-2", "shop.web.api", "reads"),
        },
    )
    # `shop` is the native compound frame around the included component.
    assert _graph(views[focus_view_id("external")]) == (
        {"shop", "shop.web.api", "provider"},
        {("shop.web.api", "provider", "calls external")},
    )
