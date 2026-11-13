"""Filesystem-only selection and safe source reads for structure readers."""

import os
from collections.abc import Sequence
from pathlib import Path

from chunkhound.code_mapper.models import HydeConfig
from chunkhound.code_mapper.scope import collect_scope_files
from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.contract import Finding, RepositoryRef
from chunkhound.services.extraction.sources import (
    SourceError,
    SourceVersion,
    read_source,
)

MAX_SOURCE_BYTES = 10 * 1024 * 1024


def select_files(
    project_root: Path, patterns: Sequence[str], *, ignore_gitignore: bool = False
) -> tuple[str, ...]:
    return tuple(
        sorted(
            collect_scope_files(
                scope_path=project_root,
                project_root=project_root,
                hyde_cfg=HydeConfig(0, 0, 0, 1, 1),
                include_patterns=list(patterns),
                ignore_sources=[] if ignore_gitignore else None,
            )
        )
    )


def repository_paths(project_root: Path) -> tuple[str, ...]:
    """Include the root and nested repositories, including worktree .git files."""
    paths = {"."}
    for directory, dirs, files in os.walk(project_root, followlinks=False):
        if ".git" in dirs or ".git" in files:
            paths.add(Path(directory).relative_to(project_root).as_posix())
        dirs[:] = sorted(d for d in dirs if d not in {".git", "node_modules", "vendor"})
    return tuple(sorted(paths))


def read_file(
    project_root: Path,
    path: str,
    repository: RepositoryRef,
    findings: list[Finding],
) -> SourceVersion | None:
    reason = "unreadable_source"
    try:
        resolved = (project_root / path).resolve()
        if not resolved.is_relative_to(project_root.resolve()):
            raise SourceError("Source leaves the project")
        if resolved.stat().st_size > MAX_SOURCE_BYTES:
            reason = "source_too_large"
        else:
            return read_source(project_root, path, strict=False)
    except (OSError, SourceError):
        pass
    findings.append(
        Finding(
            kind="unresolved",
            subject=None,
            reason=reason,
            detail=path,
            citations=(
                Citation(
                    repository=repository.key,
                    path=path,
                    start_line=1,
                    end_line=1,
                    commit=repository.commit,
                ),
            ),
        )
    )
    return None
