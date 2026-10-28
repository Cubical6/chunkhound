"""Renderer-facing C4 JSON and interrupted-write contracts."""

import hashlib
import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest

from chunkhound.code_mapper.c4.model import (
    C4Evidence,
    C4Model,
    C4PairMismatchError,
    MapLock,
    load_c4_pair,
)
from chunkhound.code_mapper.c4.writer import compute_run_id, write_c4_pair


def sample_pair() -> tuple[C4Model, C4Evidence]:
    model = C4Model.model_validate(
        {
            "run": {
                "id": "",
                "kind": "full",
                "schema_version": 1,
                "head_sha": "abc",
                "scope": "/",
                "fallback_count": 0,
                "renames": False,
            },
            "elements": [
                {
                    "id": id_,
                    "kind": kind,
                    "name": name,
                    "description": None,
                    "status": "found",
                    "parent": parent,
                    "markers": [],
                    "coverage": {"status": "none", "topics": []},
                }
                for id_, kind, name, parent in [
                    ("systeem:app", "system", "App", None),
                    ("container:app", "container", "App runtime", "systeem:app"),
                    ("component:api", "component", "API", "container:app"),
                    ("component:data", "component", "Données", "container:app"),
                ]
            ],
            "relations": [
                {
                    "id": "component:api->component:data",
                    "from": "component:api",
                    "to": "component:data",
                    "title": "Reads data",
                    "status": "found",
                    "reference_counts": {"import": 1},
                    "markers": [],
                }
            ],
            "merged": [
                {
                    "id": "merged:api-data",
                    "from": "component:api",
                    "to": "component:data",
                    "view": "container:app",
                    "label": "Reads data",
                    "underlying": ["component:api->component:data"],
                    "markers": [],
                }
            ],
            "history": [
                {
                    "from_id": "component:api",
                    "to_id": "component:api",
                    "kind": "continuation",
                }
            ],
        }
    )
    evidence = C4Evidence.model_validate(
        {
            "schema_version": 1,
            "run_id": "",
            "references": [
                {
                    "relation": "component:api->component:data",
                    "from": "src/api.py",
                    "line": 1,
                    "to": "src/data.py",
                    "kind": "import",
                    "status": "counts",
                }
            ],
            "citations": [
                {
                    "target": "component:api",
                    "file": "src/api.py",
                    "start_line": 1,
                    "end_line": 5,
                    "source": "code",
                    "verified": True,
                }
            ],
            "element_files": {
                "component:api": ["src/api.py"],
                "component:data": ["src/data.py"],
            },
        }
    )
    return model, evidence


def shipped_schema(name: str) -> dict:
    return json.loads(
        files("chunkhound.code_mapper.c4")
        .joinpath("schemas", f"{name}.schema.json")
        .read_text()
    )


def test_output_validates_against_schema(tmp_path: Path) -> None:
    model, evidence = sample_pair()
    model_path, evidence_path = write_c4_pair(
        out_dir=tmp_path, scope_label="", model=model, evidence=evidence
    )
    assert model_path.name == "root_c4_model.json"
    assert evidence_path.name == "root_c4_evidence.json"
    for path, name in [(model_path, "c4_model"), (evidence_path, "c4_evidence")]:
        jsonschema.validate(json.loads(path.read_text()), shipped_schema(name))
    loaded_model, loaded_evidence = load_c4_pair(model_path, evidence_path)
    assert loaded_model == model
    assert loaded_evidence == evidence
    assert loaded_model.run.id == loaded_evidence.run_id
    model_json = json.loads(model_path.read_text())
    evidence_json = json.loads(evidence_path.read_text())
    assert model_json["relations"][0]["from"] == "component:api"
    assert model_json["merged"][0]["to"] == "component:data"
    assert evidence_json["references"][0]["from"] == "src/api.py"
    evidence_json["run_id"] = "0" * 64
    evidence_path.write_text(json.dumps(evidence_json))
    with pytest.raises(C4PairMismatchError, match="chunkhound map"):
        load_c4_pair(model_path, evidence_path)


@pytest.mark.parametrize(
    "name,model_type",
    [("c4_model", C4Model), ("c4_evidence", C4Evidence), ("map_lock", MapLock)],
)
def test_shipped_schema_matches_model(name: str, model_type: type) -> None:
    assert shipped_schema(name) == model_type.model_json_schema(by_alias=True)


@pytest.mark.parametrize("scope,expected", [("/", "_"), ("a/b", "a_b")])
def test_scope_filenames_match_markdown_convention(
    tmp_path: Path, scope: str, expected: str
) -> None:
    model, evidence = sample_pair()
    paths = write_c4_pair(
        out_dir=tmp_path, scope_label=scope, model=model, evidence=evidence
    )
    assert [path.name for path in paths] == [
        f"{expected}_c4_model.json",
        f"{expected}_c4_evidence.json",
    ]


def test_run_id_covers_both_documents_without_previous_ids(tmp_path: Path) -> None:
    model, evidence = sample_pair()
    model_data = model.model_dump(by_alias=True)
    evidence_data = evidence.model_dump(by_alias=True)
    del model_data["run"]["id"]
    del evidence_data["run_id"]

    def canonical(value: dict) -> bytes:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()

    expected = hashlib.sha256(
        canonical(model_data) + b"\n" + canonical(evidence_data)
    ).hexdigest()
    assert compute_run_id(model, evidence) == expected
    paths = write_c4_pair(
        out_dir=tmp_path, scope_label="", model=model, evidence=evidence
    )
    original = [path.read_bytes() for path in paths]
    model.run.id = "stale model"
    evidence.run_id = "stale evidence"
    write_c4_pair(out_dir=tmp_path, scope_label="", model=model, evidence=evidence)
    assert [path.read_bytes() for path in paths] == original
    assert model.run.id == evidence.run_id == expected
    evidence.references[0].line = 2
    assert compute_run_id(model, evidence) != expected
    evidence.references[0].line = 1
    model.elements[0].name = "Changed"
    assert compute_run_id(model, evidence) != expected


def test_interrupted_pair_is_rejected_and_can_be_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    model, evidence = sample_pair()
    paths = write_c4_pair(
        out_dir=tmp_path, scope_label="", model=model, evidence=evidence
    )
    model.elements[0].name = "Changed"
    replace = os.replace

    def interrupt_model(source: str, destination: Path) -> None:
        if destination == paths[0]:
            raise OSError("interrupted")
        replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", interrupt_model)
        with pytest.raises(OSError, match="interrupted"):
            write_c4_pair(
                out_dir=tmp_path, scope_label="", model=model, evidence=evidence
            )
    with pytest.raises(C4PairMismatchError):
        load_c4_pair(*paths)
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        path.name for path in paths
    )
    write_c4_pair(out_dir=tmp_path, scope_label="", model=model, evidence=evidence)
    assert load_c4_pair(*paths) == (model, evidence)
