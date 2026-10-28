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
            "system": "systeem:app",
            "containers": {"pyproject.toml": "container:app"},
            "tree_spec": {"app": {"groups": ["src"]}},
            "group_membership": {
                "container:app": {"src/api.py": "1", "settings.py": "2"}
            },
            "direct_groups": {"container:app": ["container:app/2"]},
            "transition": None,
            "components": {
                "component:api": {
                    "name": "API",
                    "description": None,
                    "container": "container:app",
                    "groups": ["src"],
                    "files": ["src/api.py"],
                }
            },
            "tombstones": {"component:old": "abc"},
            "relations": {
                "component:api->extern:service": {
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


def test_lock_keeps_membership_for_groups_without_components(tmp_path: Path) -> None:
    lock = sample_lock()
    lock.components = {}
    path = write_scope_lock(tmp_path, "/", lock)
    raw = json.loads(path.read_text())
    assert raw["scopes"]["/"]["group_membership"] == {
        "container:app": {"src/api.py": "1", "settings.py": "2"}
    }
    restored = read_scope_lock(tmp_path, "/")
    assert restored is not None
    assert restored.group_membership == lock.group_membership
    assert restored.components == {}
    jsonschema.validate(raw, shipped_schema("map_lock"))


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


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        '{"version": 1, "scopes": {"/": {}}}',
        '{"version": 99, "scopes": {}}',
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
    }
    document["scopes"]["/"]["overrides"] = manual
    path.write_text(json.dumps(document))
    lock = sample_lock("new")
    lock.overrides.names = {"component:api": "Must not replace manual edit"}
    write_scope_lock(tmp_path, "/", lock)
    assert json.loads(path.read_text())["scopes"]["/"]["overrides"] == manual
    assert read_scope_lock(tmp_path, "/").overrides.names == manual["names"]
    assert read_scope_lock(tmp_path, "/").base_sha == "new"


def test_initial_scope_can_supply_overrides(tmp_path: Path) -> None:
    lock = sample_lock()
    lock.overrides.classifications = {"service": "external"}
    write_scope_lock(tmp_path, "/", lock)
    assert read_scope_lock(tmp_path, "/").overrides == lock.overrides
