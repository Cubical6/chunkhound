"""Fork-only diagnostics for match-anywhere MCP path filters."""

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple, cast

from chunkhound.interfaces.database_provider import (
    DatabaseProvider,
    ScopeAggregationProvider,
)
from chunkhound.utils.path_filter import normalize_path_filter, path_matches_filter


class PathScope(NamedTuple):
    matching_files: int
    repositories: set[str]
    top_level_directories: list[str]


@lru_cache(maxsize=128)
def _repositories(root: Path | None) -> frozenset[str]:
    if root is None:
        return frozenset()
    try:
        return frozenset(
            child.name
            for child in root.iterdir()
            if child.is_dir() and (child / ".git").exists()
        )
    except OSError:
        return frozenset()


def check_path_scope(
    normalized_filter: str, file_paths: Iterable[str], root: Path | None
) -> PathScope:
    """Count matching indexed files without changing path-filter semantics."""
    repositories = _repositories(root)
    matches = 0
    matched_repositories: set[str] = set()
    directories: set[str] = set()
    for file_path in file_paths:
        file_path = file_path.replace("\\", "/").lstrip("/")
        first, separator, _ = file_path.partition("/")
        if separator:
            directories.add(first)
        if path_matches_filter(file_path, normalized_filter):
            matches += 1
            if separator and first in repositories:
                matched_repositories.add(first)
    return PathScope(matches, matched_repositories, sorted(directories))


def no_match_message(raw: str, scope: PathScope) -> str:
    directories = ", ".join(f"{name}/" for name in scope.top_level_directories[:50])
    remaining = len(scope.top_level_directories) - 50
    if remaining > 0:
        directories += f", … and {remaining} more"
    return (
        f"path '{raw}' matches no indexed file. Directory filters match a path "
        "segment anywhere; start with a top-level directory to restrict scope. "
        f"Top-level directories: {directories}"
    )


def scope_warning(raw: str, scope: PathScope) -> str | None:
    if len(scope.repositories) < 2:
        return None
    return (
        f"Warning: path '{raw}' matches files in {len(scope.repositories)} "
        f"repositories ({', '.join(sorted(scope.repositories))}). "
        "Start the path with one repository directory to restrict scope."
    )


def validate_path_scope(
    provider: DatabaseProvider,
    raw: str | None,
    vector_source: str,
    commit_range: str | None = None,
) -> str | None:
    """Raise the usual invalid-argument error or return a scope warning."""
    # Without commit input the tools search the DB, despite the diff default.
    if vector_source == "diff" and commit_range is None:
        vector_source = "db"
    if not raw or vector_source == "diff":
        return None
    normalized = normalize_path_filter(raw)
    if normalized is None:
        return None
    scope = check_path_scope(
        normalized,
        cast(ScopeAggregationProvider, provider).get_scope_file_paths(None),
        provider.get_base_directory(),
    )
    if not scope.matching_files and vector_source == "db":
        raise ValueError(no_match_message(raw, scope))
    return scope_warning(raw, scope)
