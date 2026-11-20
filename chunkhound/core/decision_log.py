"""Process-wide, best-effort local JSONL decision logging.

Writes are synchronous and unbuffered between calls. No analytics uploader or
native extension is involved; callers must opt in through configuration.
"""

import json
import math
import os
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from loguru import logger

from chunkhound.version import __version__

_path: Path | None = None
_max_size_bytes: float = 50 * 1024 * 1024
_lock = Lock()
_trace: ContextVar[tuple[str, str | None] | None] = ContextVar(
    "decision_log_trace", default=None
)


def _debug_failure(action: str) -> None:
    # Even a failing logging sink must not interfere with the caller.
    try:
        logger.opt(exception=True).debug("Decision log {} failed", action)
    except Exception:
        pass


def configure(config: Any, target_dir: Path) -> None:
    """Replace process-wide settings; missing config sections disable logging.

    Paths must resolve inside the project's resolved .chunkhound directory.
    Relative paths start at the project root. Configuration never creates
    directories or opens the log; a refused path leaves logging disabled.
    """
    global _path, _max_size_bytes
    with _lock:
        _path = None
        try:
            settings = getattr(config, "decision_log", None)
            if settings is None or not settings.enabled:
                return
            path = (
                Path(settings.path).expanduser()
                if settings.path is not None
                else Path(".chunkhound/decisions.jsonl")
            )
            project_root = Path(target_dir).resolve()
            log_dir = (project_root / ".chunkhound").resolve()
            path = (path if path.is_absolute() else project_root / path).resolve()
            if path == log_dir or not path.is_relative_to(log_dir):
                logger.warning(
                    "Decision log disabled: path must be inside the project's "
                    "resolved .chunkhound directory (outside paths are refused)"
                )
                return
            _max_size_bytes = settings.max_size_mb * 1024 * 1024
            _path = path
        except Exception:
            _debug_failure("configuration")


def is_enabled() -> bool:
    """Whether a local decision log has been enabled for this process."""
    return _path is not None


@contextmanager
def trace() -> Iterator[str]:
    """Scope a fresh trace, preserving and restoring its parent context."""
    previous = _trace.get()
    trace_id = uuid4().hex
    token = _trace.set((trace_id, previous[0] if previous else None))
    try:
        yield trace_id
    finally:
        _trace.reset(token)


def single_hop_payload(
    *,
    query: str,
    page_size: int,
    path_filter: str | None,
    provider: str | None,
    model: str | None,
    strategy_reason: str,
    n_returned: int,
    elapsed_s: float,
) -> dict[str, Any]:
    """Shared single-hop record fields for indexed and commit-scoped search."""
    return {
        "query": query,
        "page_size": page_size,
        "has_path_filter": bool(path_filter),
        "provider": provider,
        "model": model,
        "strategy_reason": strategy_reason,
        "n_returned": n_returned,
        "elapsed_s": elapsed_s,
    }


def record_diff_searches(
    queries: list[str],
    results: list[tuple[list[dict[str, Any]], dict[str, Any]]],
    *,
    start_time: float,
    page_size: int,
    path_filter: str | None,
    embedding_manager: Any,
    provider: str | None,
    model: str | None,
) -> None:
    """Record each successful diff query without affecting its search outcome."""
    try:
        elapsed_s = time.perf_counter() - start_time
        embedding_provider = embedding_manager.get_provider(provider)
        for query, (rows, _) in zip(queries, results):
            payload = single_hop_payload(
                query=query,
                page_size=page_size,
                path_filter=path_filter,
                provider=provider or embedding_provider.name,
                model=model or embedding_provider.model,
                strategy_reason="diff",
                n_returned=len(rows),
                elapsed_s=elapsed_s,
            )
            payload["vector_source"] = "diff"
            with trace():
                record("single_hop_search", payload)
    except Exception:
        _debug_failure("record diff searches")


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _mkdir_private(path: Path) -> None:
    # mkdir(parents=True) uses default permissions for intermediate directories.
    try:
        path.mkdir(mode=0o700, exist_ok=True)
    except FileNotFoundError:
        _mkdir_private(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    # Keep the sidecar in place: locking the log inode would not survive rotation.
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "r+b") as stream:
        if sys.platform == "win32":
            import msvcrt

            # Windows permits locking a byte range beyond EOF.
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def record(event: str, payload: Mapping[str, Any]) -> None:
    """Append one event with authoritative Schema v1 common fields.

    Without an explicit trace scope, each record gets an independent trace ID.
    All serialization, directory, rotation and write failures are best-effort.
    """
    if not is_enabled():
        return
    try:
        with _lock:
            path = _path
            if path is None:
                return
            trace_id, parent_trace_id = _trace.get() or (uuid4().hex, None)
            data = {
                **payload,
                "schema_version": 1,
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "trace_id": trace_id,
                "parent_trace_id": parent_trace_id,
                "chunkhound_version": __version__,
            }
            line = json.dumps(_json_safe(data), default=str, allow_nan=False) + "\n"
            _mkdir_private(path.parent)
            with _file_lock(path.with_name(path.name + ".lock")):
                if path.exists() and path.stat().st_size > _max_size_bytes:
                    path.replace(path.with_name(path.name + ".1"))
                flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
                flags |= getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(path, flags, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as stream:
                    stream.write(line)
    except Exception:
        _debug_failure("write")
