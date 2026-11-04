"""Stable per-scope cache persistence without overwriting handwritten overrides."""

import json
from pathlib import Path
from typing import Any

from chunkhound.code_mapper.c4.model import SCHEMA_VERSION, MapLock, ScopeLock
from chunkhound.code_mapper.c4.writer import _write_json_atomic

LOCK_RELATIVE_PATH = Path(".chunkhound/map.lock.json")


class LockfileError(RuntimeError):
    """An existing lockfile cannot be safely read or updated."""


def _read_lock(path: Path) -> tuple[MapLock, dict[str, Any]]:
    """Validate the whole lock while keeping manual sections in their original shape."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Before validation: an old lock's fields would only give a schema error.
        if not isinstance(raw, dict) or raw.get("version") != SCHEMA_VERSION:
            raise LockfileError(
                f"C4 lockfile {path} is from an older version of ChunkHound "
                f"(expected lock version {SCHEMA_VERSION}). "
                "Delete it and run `chunkhound map` again."
            )
        lock = MapLock.model_validate(raw)
    except (OSError, ValueError) as exc:
        raise LockfileError(f"Cannot read C4 lockfile {path}: {exc}") from exc
    return lock, raw


def read_scope_lock(target_dir: Path, scope_label: str) -> ScopeLock | None:
    """Read a scope, distinguishing a missing lock/scope from a corrupt lock."""
    path = target_dir / LOCK_RELATIVE_PATH
    try:
        lock, _ = _read_lock(path)
    except LockfileError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return None
        raise
    return lock.scopes.get(scope_label)


def write_scope_lock(target_dir: Path, scope_label: str, lock: ScopeLock) -> Path:
    """Replace one scope; all on-disk scopes and manual overrides take precedence."""
    path = target_dir / LOCK_RELATIVE_PATH
    try:
        _, document = _read_lock(path)
    except LockfileError as exc:
        if not isinstance(exc.__cause__, FileNotFoundError):
            raise
        document = {"version": SCHEMA_VERSION, "scopes": {}}
    scope = lock.model_dump(mode="json", by_alias=True)
    scopes = document["scopes"]
    if scope_label in scopes:
        scope["overrides"] = scopes[scope_label]["overrides"]
    scopes[scope_label] = scope
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_json_atomic(path, document)
    except OSError as exc:
        raise LockfileError(f"Cannot write C4 lockfile {path}: {exc}") from exc
    return path
