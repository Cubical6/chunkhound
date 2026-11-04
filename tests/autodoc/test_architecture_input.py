"""Consumer contracts: preserve producer claims and isolate damaged references."""

import json
from pathlib import Path
from typing import Any

import pytest

from chunkhound.autodoc.architecture.loader import ModelLoader
from chunkhound.autodoc.architecture.model import Status


def model_document() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "system": {"id": "system", "name": "System", "description": "Root"},
        "repositories": [
            {
                "id": "repo",
                "path": ".",
                "remote_url": "https://github.com/org/root.git",
                "commit": "a" * 40,
            }
        ],
        "sources": [
            {
                "id": "code",
                "repository": "repo",
                "path": "frontend/src/client.ts",
                "start_line": 2,
                "end_line": 8,
                "kind": "code",
            },
            {
                "id": "doc",
                "repository": "repo",
                "path": "README.md",
                "start_line": 1,
                "end_line": 3,
                "kind": "doc",
            },
        ],
        "elements": [
            {
                "id": "container",
                "kind": "container",
                "parent": "system",
                "name": "Frontend",
                "technology": "TS",
                "status": "found",
                "files": ["frontend/shared.ts", "frontend/src/client.ts"],
                "sources": ["code", "doc"],
            },
            {
                "id": "component",
                "kind": "component",
                "parent": "container",
                "name": "Client",
                "technology": "TS",
                "status": "found",
                "files": ["frontend/src/client.ts"],
                "sources": ["code"],
            },
            {
                "id": "planned",
                "kind": "component",
                "parent": "container",
                "name": "Planned UI",
                "technology": "",
                "status": "documented",
                "files": [],
                "sources": ["doc"],
            },
        ],
        "relations": [],
        "merged_labels": [],
        "topics": [
            {
                "file": "topic.md",
                "covers": [
                    {"element": "component", "files": ["frontend/src/client.ts"]}
                ],
            }
        ],
    }


def load_document(
    tmp_path: Path, document: dict[str, Any], warnings: list[str] | None = None
):
    index = tmp_path / "chosen_code_mapper_index.md"
    index.write_text("# A heading that is not the chosen stem\n", encoding="utf-8")
    (tmp_path / "chosen_c4_model.json").write_text(
        json.dumps(document), encoding="utf-8"
    )
    return ModelLoader.load(
        index_path=index, log_warning=warnings.append if warnings is not None else None
    )


@pytest.mark.parametrize("failure", ["missing", "json", "version", "shape", "encoding"])
def test_input_failures_warn_without_inventing_architecture(
    tmp_path: Path, failure: str
):
    index = tmp_path / "chosen_code_mapper_index.md"
    model_path = tmp_path / "chosen_c4_model.json"
    if failure == "json":
        model_path.write_text("{broken", encoding="utf-8")
    elif failure == "version":
        document = model_document()
        document["schema_version"] = 1
        model_path.write_text(json.dumps(document), encoding="utf-8")
    elif failure == "shape":
        model_path.write_text('{"schema_version": 2, "system": []}', encoding="utf-8")
    elif failure == "encoding":
        model_path.write_bytes(b"\xff")
    warnings: list[str] = []
    assert ModelLoader.load(index_path=index, log_warning=warnings.append) is None
    assert warnings
    assert str(model_path) in warnings[0]
    assert any(
        word in warnings[0].lower() for word in ("regenerate", "rerun", "re-run")
    )
    assert len(warnings[0]) > len(str(model_path))


def test_R1_R2_R6_R10_preserve_identity_status_and_zero_relations(tmp_path: Path):
    document = model_document()
    # Consumption is not reclassification, even when producer status differs
    # from what a consumer might infer from the source kind.
    document["elements"][1]["status"] = "documented"
    model = load_document(tmp_path, document)
    assert model is not None
    assert model.system.id == "system"
    assert [(element.id, element.parent_id) for element in model.elements] == [
        ("container", "system"),
        ("component", "container"),
        ("planned", "container"),
    ]
    assert model.elements[1].status == Status.DOCUMENTED
    assert model.elements[0].source_ids == ["code", "doc"]
    assert model.relations == []


def test_dangling_references_remove_only_dependent_content(tmp_path: Path):
    document = model_document()
    document["sources"].append(
        {
            "id": "bad-source",
            "repository": "unknown-repo",
            "path": "x",
            "start_line": 1,
            "end_line": 1,
            "kind": "code",
        }
    )
    document["elements"][0]["sources"].append("unknown-source")
    document["elements"].extend(
        [
            {**document["elements"][0], "id": "orphan", "parent": "unknown-parent"},
            {**document["elements"][1], "id": "orphan-child", "parent": "orphan"},
            {**document["elements"][0], "id": "unsupported", "sources": ["bad-source"]},
        ]
    )
    relation = {
        "id": "valid",
        "source": "component",
        "target": "system",
        "title": "Uses",
        "technology": "",
        "status": "documented",
        "sources": ["doc", "unknown-source"],
    }
    document["relations"] = [
        relation,
        {**relation, "id": "dangling", "target": "orphan-child"},
        {**relation, "id": "no-evidence", "sources": ["bad-source"]},
    ]
    document["merged_labels"] = [
        {
            "source": "component",
            "target": "system",
            "relations": ["valid", "dangling"],
            "label": "Do not retain partial override",
        }
    ]
    document["topics"][0]["covers"].append(
        {"element": "orphan-child", "files": ["frontend/src/client.ts"]}
    )
    warnings: list[str] = []
    model = load_document(tmp_path, document, warnings)
    assert model is not None
    assert {element.id for element in model.elements} == {
        "container",
        "component",
        "planned",
    }
    assert [source.id for source in model.sources] == ["code", "doc"]
    assert [relation.id for relation in model.relations] == ["valid"]
    assert model.relations[0].source_ids == ["doc"]
    assert model.merged_labels == []
    assert [cover.element_id for cover in model.topics[0].covers] == ["component"]
    for unknown in (
        "unknown-repo",
        "unknown-source",
        "unknown-parent",
        "orphan-child",
        "bad-source",
        "dangling",
    ):
        assert any(unknown in warning for warning in warnings)


@pytest.mark.parametrize("bad_label", ["x" * 61, "... [...]", "", None])
def test_unusable_merged_label_does_not_remove_relations(
    tmp_path: Path, bad_label: str | None
):
    document = model_document()
    relation = {
        "id": "first",
        "source": "component",
        "target": "system",
        "title": "Uses",
        "technology": "",
        "status": "found",
        "sources": ["code"],
    }
    document["relations"] = [relation, {**relation, "id": "second", "title": "Sends"}]
    document["merged_labels"] = [
        {
            "source": "component",
            "target": "system",
            "relations": ["first", "second"],
            "label": bad_label,
        }
    ]
    warnings: list[str] = []
    model = load_document(tmp_path, document, warnings)
    assert model is not None
    assert len(model.relations) == 2
    assert model.merged_labels == []
    assert warnings


@pytest.mark.parametrize("malformed_row", [None, "not an object", []])
def test_malformed_merged_label_rows_preserve_valid_architecture(
    tmp_path: Path, malformed_row: object
):
    document = model_document()
    relation = {
        "id": "code-link",
        "source": "component",
        "target": "system",
        "title": "Sends events",
        "technology": "HTTP",
        "status": "found",
        "sources": ["code", "doc"],
    }
    document["relations"] = [
        relation,
        {
            **relation,
            "id": "doc-link",
            "title": "Reads status",
            "status": "documented",
            "sources": ["doc"],
        },
    ]
    document["merged_labels"] = [
        malformed_row,
        {
            "source": "container",
            "target": "system",
            "relations": ["code-link", "doc-link"],
            "label": "Exchanges status and events",
        },
        malformed_row,
    ]
    warnings: list[str] = []
    model = load_document(tmp_path, document, warnings)
    assert model is not None
    assert model.system.id == "system"
    assert [element.id for element in model.elements] == [
        "container",
        "component",
        "planned",
    ]
    assert [source.id for source in model.sources] == ["code", "doc"]
    assert len(warnings) == 2
    assert [(r.id, r.status.value, r.source_ids) for r in model.relations] == [
        ("code-link", "found", ["code", "doc"]),
        ("doc-link", "documented", ["doc"]),
    ]
    assert [
        (label.source_id, label.target_id, label.relation_ids, label.label)
        for label in model.merged_labels
    ] == [
        (
            "container",
            "system",
            ["code-link", "doc-link"],
            "Exchanges status and events",
        )
    ]
