"""Disposable, crash-safe store of validated bundle outcomes.

One JSON file per bundle; no shared index. Correctness never depends on this
store: every reused part is rechecked by the application against the current
source. Unreadable or foreign entries are cache misses, never fatal.
"""

import hashlib
import json
import os
import time
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from loguru import logger

from chunkhound.services.extraction.fragments import FragmentIdentity

FORMAT_VERSION = 1
NOTATION_VERSION = 1
PRUNE_UNUSED_DAYS = 30
PRUNE_TMP_DAYS = 1
_DAY = 86_400


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    model: str
    reasoning_effort: str | None = None
    base_url: str | None = None


def bundle_key_parts(
    *,
    goal: str,
    goal_version: str,
    provider: ProviderIdentity,
    max_completion_tokens: int,
    members: Sequence[FragmentIdentity],
) -> dict[str, Any]:
    return {
        "format": FORMAT_VERSION,
        "notation": NOTATION_VERSION,
        "goal": goal,
        "goal_version": goal_version,
        "provider": asdict(provider),
        "max_completion_tokens": max_completion_tokens,
        "members": [asdict(member) for member in members],
    }


def key_from_parts(parts: dict[str, Any]) -> str:
    canonical = json.dumps(
        parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StoredBundle:
    key: str
    key_parts: dict[str, Any]
    members: tuple[FragmentIdentity, ...]
    # Position within the bundle -> validated part as JSON. Invalid members of
    # a partially valid bundle are absent.
    parts: dict[int, dict[str, Any]]


class ExtractionStore:
    def __init__(self, root: Path, goal: str, *, read_only: bool) -> None:
        self.directory = root / goal
        self.read_only = read_only

    def candidates(self) -> Iterator[StoredBundle]:
        if not self.directory.is_dir():
            return
        for path in sorted(self.directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                key_parts = data["key_parts"]
                if data.get("format") != FORMAT_VERSION or not isinstance(
                    key_parts, dict
                ):
                    raise ValueError("unknown format")
                key = key_from_parts(key_parts)
                if path.stem != key or data.get("key") != key:
                    raise ValueError("key does not match its parts")
                members = tuple(
                    FragmentIdentity(**member) for member in key_parts["members"]
                )
                parts = {
                    int(position): dict(part)
                    for position, part in data["parts"].items()
                }
                if any(not 0 <= position < len(members) for position in parts):
                    raise ValueError("part outside the bundle")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning(f"Skipping extraction cache entry {path.name}: {exc}")
                continue
            yield StoredBundle(key, key_parts, members, parts)

    def put(self, bundle: StoredBundle) -> None:
        if self.read_only or not bundle.parts:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": FORMAT_VERSION,
            "key": bundle.key,
            "key_parts": bundle.key_parts,
            "parts": {str(position): part for position, part in bundle.parts.items()},
        }
        _write_json_durable(self.directory / f"{bundle.key}.json", payload)

    def touch(self, key: str) -> None:
        if self.read_only:
            return
        try:
            os.utime(self.directory / f"{key}.json")
        except OSError as exc:
            logger.debug(f"Cannot mark extraction cache entry as used: {exc}")

    def prune(self, now: float | None = None) -> None:
        if self.read_only or not self.directory.is_dir():
            return
        current = time.time() if now is None else now
        for pattern, days in (
            ("*.json", PRUNE_UNUSED_DAYS),
            (".*.tmp", PRUNE_TMP_DAYS),
        ):
            for path in self.directory.glob(pattern):
                try:
                    if path.stat().st_mtime < current - days * _DAY:
                        path.unlink()
                except OSError as exc:
                    logger.debug(f"Cannot prune extraction cache entry: {exc}")


def _write_json_durable(path: Path, value: dict[str, Any]) -> None:
    """Temporary file, flush, fsync, then atomic replace in the same directory."""
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, sort_keys=True, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
