"""Process-wide, best-effort local JSONL decision logging.

Writes are synchronous and unbuffered between calls. No analytics uploader or
native extension is involved; callers must opt in through configuration.
"""

import json
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

    Relative paths are resolved against the same project root as the default.
    Configuration never creates directories or opens the log.
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
            _max_size_bytes = settings.max_size_mb * 1024 * 1024
            _path = path if path.is_absolute() else Path(target_dir) / path
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
            line = json.dumps(data, default=str) + "\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > _max_size_bytes:
                path.replace(path.with_name(path.name + ".1"))
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line)
    except Exception:
        _debug_failure("write")
