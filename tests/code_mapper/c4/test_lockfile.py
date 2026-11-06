"""Per-scope lock persistence protects cached outcomes and manual overrides."""

import json
from pathlib import Path

import jsonschema
import pytest

from chunkhound.code_mapper.c4.lockfile import (
    LOCK_RELATIVE_PATH,
    LockfileError,
    read_scope_lock,
    write_scope_lock,
)
from chunkhound.code_mapper.c4.model import ScopeLock
from tests.code_mapper.c4.test_output_contract import shipped_schema


def sample_lock(base_sha: str = "abc") -> ScopeLock:
    return ScopeLock.model_validate(
        {
            "base_sha": base_sha,
            "system": "system:app",
            "containers": {"pyproject.toml": "container:app"},
            "direct_groups": {"container:app": ["container:app/."]},
            "transition": None,
            "components": {
                "component:api": {
                    "name": "API",
                    "description": None,
                    "container": "container:app",
                    "groups": ["container:app/src"],
                    "files": ["src/api.py"],
                }
            },
            "tombstones": {"component:old": "abc"},
            "relations": {
                "component:api->external:service": {
                    "title": "Calls",
                    "fingerprint": "123",
                }
            },
            "classifications": {
                "service": {
                    "value": "external",
                    "votes": ["external", None, "external"],
                    "markers": [],
                }
            },
            "documented": {
                "hashes": {"README.md": "123"},
                "elements": [],
                "relations": [],
            },
            "summaries": {"arrow:api-service": "Calls service"},
            "overrides": {},
        }
    )


def test_lock_is_byte_stable(tmp_path: Path) -> None:
    lock = sample_lock()
    path = write_scope_lock(tmp_path, "/", lock)
    first = path.read_bytes()
    assert path == tmp_path / LOCK_RELATIVE_PATH
    assert read_scope_lock(tmp_path, "/") == lock
    write_scope_lock(tmp_path, "/", lock)
    assert path.read_bytes() == first
    document = json.loads(first)
    assert (
        first.decode()
        == json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    )
    jsonschema.validate(document, shipped_schema("map_lock"))


def test_lock_keeps_direct_groups_without_components(tmp_path: Path) -> None:
    lock = sample_lock()
    lock.components = {}
    path = write_scope_lock(tmp_path, "/", lock)
    raw = json.loads(path.read_text())
    assert raw["version"] == 5
    assert raw["scopes"]["/"]["direct_groups"] == {"container:app": ["container:app/."]}
    assert not {"tree_spec", "group_membership"}.intersection(raw["scopes"]["/"])
    restored = read_scope_lock(tmp_path, "/")
    assert restored is not None
    assert restored.direct_groups == lock.direct_groups
    assert restored.components == {}
    jsonschema.validate(raw, shipped_schema("map_lock"))


@pytest.mark.parametrize(
    "content",
    [
        json.dumps(
            {
                "version": 3,
                "scopes": {"/": {"tree_spec": {}, "group_membership": {}}},
            }
        ),
        # Version 4 locked Dutch documentation outcomes and statuses.
        '{"version": 4, "scopes": {"/": {"tree_spec": {}}}}',
        '{"version": 99, "scopes": {}}',
        '{"scopes": {}}',
        "{}",
        "[]",
        "null",
        '"version"',
    ],
)
def test_older_lock_gives_clear_message(tmp_path: Path, content: str) -> None:
    path = tmp_path / LOCK_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(content)
    for attempt in (
        lambda: read_scope_lock(tmp_path, "/"),
        lambda: write_scope_lock(tmp_path, "/", sample_lock()),
    ):
        with pytest.raises(LockfileError) as raised:
            attempt()
        assert str(path) in str(raised.value)
        assert "older version" in str(raised.value)
        assert "delete" in str(raised.value).lower()
    assert path.read_text() == content


def test_lock_sections_are_independent_per_scope(tmp_path: Path) -> None:
    assert read_scope_lock(tmp_path, "/") is None
    root = sample_lock()
    child = sample_lock("child")
    path = write_scope_lock(tmp_path, "/", root)
    write_scope_lock(tmp_path, "src", child)
    child_json = json.loads(path.read_text())["scopes"]["src"]
    write_scope_lock(tmp_path, "/", sample_lock("updated"))
    assert read_scope_lock(tmp_path, "src") == child
    assert json.loads(path.read_text())["scopes"]["src"] == child_json
    assert read_scope_lock(tmp_path, "/").base_sha == "updated"
    assert read_scope_lock(tmp_path, "missing") is None


def lockfile_with_overrides(overrides: dict[str, object]) -> str:
    scope = sample_lock().model_dump(mode="json", by_alias=True)
    scope["overrides"] = overrides
    return json.dumps({"version": 5, "scopes": {"/": scope}})


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        '{"version": 1, "scopes": {"/": {}}}',
        '{"version": 99, "scopes": {}}',
        '{"version": 5, "scopes": {"/": {}}}',
        '{"version": 5, "scopes": {"/": {"tree_spec": {}}}}',
        lockfile_with_overrides({"drop": "external:httpx"}),
        lockfile_with_overrides({"merge": {"external:google": 1}}),
        lockfile_with_overrides({"keep_apart": "external:google"}),
        lockfile_with_overrides({"keep_apart": [["external:google"]]}),
        lockfile_with_overrides({"keep_apart": [["a", "b", "c"]]}),
        lockfile_with_overrides({"keep_apart": [["external:google", 1]]}),
    ],
)
def test_corrupt_lockfile_is_reported_not_overwritten(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / LOCK_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(content)
    with pytest.raises(LockfileError, match="map.lock.json"):
        read_scope_lock(tmp_path, "/")
    with pytest.raises(LockfileError, match="map.lock.json"):
        write_scope_lock(tmp_path, "/", sample_lock())
    assert path.read_text() == content


def test_override_section_is_never_rewritten(tmp_path: Path) -> None:
    path = write_scope_lock(tmp_path, "/", sample_lock())
    document = json.loads(path.read_text())
    manual = {
        "names": {"component:api": "Public API"},
        "labels": {"arrow:api-service": "Manual label"},
        "drop": ["external:httpx"],
        "merge": {"external:google": "external:gemini"},
        "keep_apart": [["external:google", "external:google-gemini"]],
    }
    document["scopes"]["/"]["overrides"] = manual
    path.write_text(json.dumps(document))
    lock = sample_lock("new")
    lock.overrides.names = {"component:api": "Must not replace manual edit"}
    write_scope_lock(tmp_path, "/", lock)
    assert json.loads(path.read_text())["scopes"]["/"]["overrides"] == manual
    assert read_scope_lock(tmp_path, "/").overrides.names == manual["names"]
    assert read_scope_lock(tmp_path, "/").overrides.drop == ["external:httpx"]
    assert read_scope_lock(tmp_path, "/").overrides.merge == {
        "external:google": "external:gemini"
    }
    assert read_scope_lock(tmp_path, "/").base_sha == "new"
    assert read_scope_lock(tmp_path, "/").overrides.keep_apart == [
        ("external:google", "external:google-gemini")
    ]


def test_initial_scope_can_supply_overrides(tmp_path: Path) -> None:
    lock = sample_lock()
    lock.overrides.classifications = {"service": "external"}
    write_scope_lock(tmp_path, "/", lock)
    assert read_scope_lock(tmp_path, "/").overrides == lock.overrides


def test_v5_lock_without_keep_apart_is_readable(tmp_path: Path) -> None:
    path = tmp_path / LOCK_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    content = lockfile_with_overrides(
        {
            "drop": ["external:httpx"],
            "merge": {"external:google": "external:gemini"},
        }
    )
    path.write_text(content)
    restored = read_scope_lock(tmp_path, "/")
    assert restored is not None
    assert restored.overrides.keep_apart == []
    assert restored.overrides.drop == ["external:httpx"]
    assert restored.overrides.merge == {"external:google": "external:gemini"}
    write_scope_lock(tmp_path, "/", sample_lock("updated"))
    manual = json.loads(path.read_text())["scopes"]["/"]["overrides"]
    assert manual == json.loads(content)["scopes"]["/"]["overrides"]
