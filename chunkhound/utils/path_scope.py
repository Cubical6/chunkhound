"""Fork-only diagnostics for match-anywhere MCP path filters."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from chunkhound.database_factory import DatabaseServices
from chunkhound.utils.path_filter import normalize_path_filter, path_matches_filter


class PathScope(NamedTuple):
    matching_files: int
    repositories: set[str]
    top_level_directories: list[str]


def _repositories(root: Path | None) -> frozenset[str]:
    """Discover repositories up to three directory levels on each request.

    Do not descend into discovered repositories (including vendor trees).
    The index root itself may be a repository with additional repos beneath it.
    """
    if root is None:
        return frozenset()
    repositories: set[str] = set()

    def visit(directory: Path, depth: int) -> None:
        try:
            if (directory / ".git").exists():
                repositories.add(directory.relative_to(root).as_posix())
                if depth:
                    return
            if depth >= 3:
                return
            children = list(directory.iterdir())
        except OSError:
            return
        for child in children:
            try:
                if child.name != ".git" and not child.is_symlink() and child.is_dir():
                    visit(child, depth + 1)
            except OSError:
                continue

    visit(root, 0)
    return frozenset(repositories)


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
            repository = file_path.rpartition("/")[0]
            while repository and repository not in repositories:
                repository = repository.rpartition("/")[0]
            if repository in repositories:
                matched_repositories.add(repository)
            elif "." in repositories:
                matched_repositories.add(".")
    return PathScope(matches, matched_repositories, sorted(directories))


def no_match_message(raw: str, scope: PathScope) -> str:
    directories = ", ".join(f"{name}/" for name in scope.top_level_directories[:50])
    remaining = len(scope.top_level_directories) - 50
    if remaining > 0:
        directories += f", … and {remaining} more"
    return (
        f"path '{raw}' matches no indexed file. Directory filters match a path "
        "segment anywhere; include more directory segments to narrow matches, "
        "but this does not anchor the path to the index root. "
        f"Top-level directories: {directories}"
    )


def scope_warning(raw: str, scope: PathScope) -> str | None:
    if len(scope.repositories) < 2:
        return None
    return (
        f"> **Warning:** path '{raw}' matches files in {len(scope.repositories)} "
        f"repositories ({', '.join(sorted(scope.repositories))}). "
        "Include the repository directory to narrow matches; this is not "
        "root-anchored and can also match nested paths in other repositories."
    )


def validate_path_scope(
    services: DatabaseServices,
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
    provider = services.provider
    get_scope_file_paths = getattr(provider, "get_scope_file_paths", None)
    if not callable(get_scope_file_paths):
        return None
    file_paths = get_scope_file_paths(None)
    # An empty or still-indexing database is not evidence of an invalid path.
    if not file_paths:
        return None
    scope = check_path_scope(
        normalized,
        file_paths,
        provider.get_base_directory(),
    )
    if not scope.matching_files and vector_source == "db":
        raise ValueError(no_match_message(raw, scope))
    return scope_warning(raw, scope)
