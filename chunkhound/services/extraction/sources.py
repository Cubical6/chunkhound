"""Source versions: a selected project file identified by path and content hash."""

import hashlib
from dataclasses import dataclass
from pathlib import Path


class SourceError(ValueError):
    """A selected source cannot be read as required; never silently skipped."""


@dataclass(frozen=True)
class SourceVersion:
    path: str
    sha256: str
    lines: tuple[str, ...]


def read_source(project_root: Path, path: str, *, strict: bool) -> SourceVersion:
    """Read once; strict sources must be UTF-8, lenient ones drop undecodable bytes.

    Lines use ``str.splitlines()`` so line numbers match quote verification.
    """
    if Path(path).is_absolute():
        raise SourceError(f"Source path must be project-relative: {path}")
    root = project_root.resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise SourceError(f"Source is not a project file: {path}")
    content = resolved.read_bytes()
    try:
        text = content.decode("utf-8", errors="strict" if strict else "ignore")
    except UnicodeDecodeError as exc:
        raise SourceError(f"Source is not valid UTF-8: {path}") from exc
    return SourceVersion(
        path=Path(path).as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
        lines=tuple(text.splitlines()),
    )
