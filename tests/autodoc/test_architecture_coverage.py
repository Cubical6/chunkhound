"""Coverage must never cross repositories or turn rolled-up links into targets."""

import json
from pathlib import Path

from chunkhound.autodoc.architecture.coverage import CoverageIndex
from chunkhound.autodoc.architecture.loader import ModelLoader
from chunkhound.autodoc.index_loader import find_index_file
from chunkhound.autodoc.models import DocsitePage
from tests.autodoc.test_architecture_input import load_document, model_document


def page_for(
    tmp_path: Path,
    filename: str = "topic.md",
    slug: str = "final-topic",
    title: str = "Final title",
) -> DocsitePage:
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Topic\n", encoding="utf-8")
    return DocsitePage(1, title, slug, "", "Topic", str(path))


def test_R5_selected_index_and_repository_paths_do_not_cross_bind(tmp_path: Path):
    document = model_document()
    model = load_document(tmp_path, document)
    assert model is not None
    # An earlier alphabetic scope must not win a second independent lookup.
    other_path = tmp_path / "aaa_c4_model.json"
    other = model_document()
    other["system"]["id"] = "other-system"
    other["elements"][0]["parent"] = "other-system"
    other_path.write_text(json.dumps(other), encoding="utf-8")
    (tmp_path / "aaa_code_mapper_index.md").write_text(
        "# Different scope\n", encoding="utf-8"
    )
    chosen = find_index_file(tmp_path, patterns=["chosen_code_mapper_index.md"])
    selected = ModelLoader.load(index_path=chosen)
    assert selected is not None
    assert selected.system.id == "system"
    front = page_for(tmp_path)
    backend = page_for(tmp_path, "nested/backend.md", "backend")
    document["topics"].append(
        {
            "file": "nested/backend.md",
            "covers": [{"element": "component", "files": ["backend/src/client.ts"]}],
        }
    )
    selected = load_document(tmp_path, document)
    assert selected is not None
    coverage = CoverageIndex(selected, [front, backend], tmp_path)
    assert coverage.direct_elements_for(front) == ["component"]
    assert coverage.direct_elements_for(backend) == []
    assert [(p.slug, files) for p, files in coverage.topics_for("component")] == [
        ("final-topic", frozenset({"frontend/src/client.ts"}))
    ]


def test_R5_direct_targets_differ_from_rolled_up_topics(tmp_path: Path):
    document = model_document()
    document["topics"][0]["covers"] = [
        {
            "element": "component",
            "files": ["frontend/./src/client.ts", "frontend/src/client.ts"],
        },
        {
            "element": "container",
            "files": ["frontend/shared.ts", "frontend/src/client.ts"],
        },
        {"element": "component", "files": ["frontend/src/client.ts"]},
        {"element": "planned", "files": ["README.md"]},
    ]
    model = load_document(tmp_path, document)
    assert model is not None
    page = page_for(tmp_path)
    uncovered_page = page_for(tmp_path, "uncovered.md", "uncovered")
    coverage = CoverageIndex(model, [page, uncovered_page], tmp_path)
    assert coverage.direct_elements_for(page) == ["component", "container"]
    assert [(p.slug, len(files)) for p, files in coverage.topics_for("system")] == [
        ("final-topic", 2)
    ]
    assert coverage.direct_elements_for(uncovered_page) == []
    assert coverage.topics_for("planned") == []
    assert coverage.topics_for("unknown") == []


def test_coverage_sorts_by_union_weight_then_title_and_slug(tmp_path: Path):
    document = model_document()
    document["topics"] = [
        {
            "file": "a.md",
            "covers": [{"element": "container", "files": ["frontend/shared.ts"]}],
        },
        {
            "file": "b.md",
            "covers": [
                {
                    "element": "container",
                    "files": ["frontend/shared.ts", "frontend/src/client.ts"],
                }
            ],
        },
        {
            "file": "c.md",
            "covers": [{"element": "component", "files": ["frontend/src/client.ts"]}],
        },
        {
            "file": "d.md",
            "covers": [{"element": "component", "files": ["frontend/src/client.ts"]}],
        },
    ]
    model = load_document(tmp_path, document)
    assert model is not None
    pages = [
        page_for(tmp_path, "a.md", "z", "A"),
        page_for(tmp_path, "b.md", "big", "Z"),
        page_for(tmp_path, "c.md", "b", "A"),
        page_for(tmp_path, "d.md", "a", "A"),
    ]
    coverage = CoverageIndex(model, pages, tmp_path)
    assert [(p.slug, len(files)) for p, files in coverage.topics_for("system")] == [
        ("big", 2),
        ("a", 1),
        ("b", 1),
        ("z", 1),
    ]


def test_missing_page_and_unknown_cover_warn_without_broken_links(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    document = model_document()
    document["topics"] += [
        {
            "file": "missing.md",
            "covers": [{"element": "component", "files": ["frontend/src/client.ts"]}],
        },
        {
            "file": "topic.md",
            "covers": [
                {"element": "missing-element", "files": ["frontend/src/client.ts"]}
            ],
        },
    ]
    warnings: list[str] = []
    model = load_document(input_dir, document, warnings)
    assert model is not None
    page = page_for(input_dir)
    # Same basename outside input_dir is not the topic's original source.
    outside = page_for(tmp_path, "elsewhere/topic.md", "wrong")
    coverage = CoverageIndex(model, [outside, page], input_dir, warnings.append)
    assert [(p.slug, len(files)) for p, files in coverage.topics_for("system")] == [
        ("final-topic", 1)
    ]
    assert coverage.direct_elements_for(outside) == []
    assert any("missing.md" in warning for warning in warnings)
    assert any("missing-element" in warning for warning in warnings)
