"""Collect the same indexing scope as HyDE, without sampling its files."""

from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from re import Pattern

from chunkhound.code_mapper.models import HydeConfig
from chunkhound.code_mapper.scope import collect_scope_files
from chunkhound.core.config.c4_config import C4Config
from chunkhound.core.config.config import Config
from chunkhound.core.config.indexing_config import IndexingConfig
from chunkhound.utils.file_patterns import compile_pattern
from chunkhound.utils.text import safe_scope_label

_TEST_DIRECTORIES = frozenset(
    {"tests", "test", "__tests__", "fixtures", "__fixtures__", "testdata"}
)
_TEST_FILE_NAMES = ("test_*", "*_test.*", "*.test.*", "*.spec.*", "conftest.py")


@dataclass(frozen=True)
class ScopeSelection:
    files: list[str]
    excluded_as_test_code: int
    excluded_by_pattern: int


def c4_settings(config: Config | None) -> C4Config:
    return config.c4 if config is not None else C4Config()


def compile_excludes(settings: C4Config) -> list[Pattern[str]]:
    cache: dict[str, Pattern[str]] = {}
    return [compile_pattern(pattern, cache) for pattern in settings.exclude]


def matches_exclude(file: str, excludes: list[Pattern[str]]) -> bool:
    return any(pattern.match(file) for pattern in excludes)


def in_test_directory(file: str, scope: PurePosixPath) -> bool:
    """Only path segments below the scope count, so a scope in tests/ still works."""
    path = PurePosixPath(file)
    below = path.relative_to(scope) if path.is_relative_to(scope) else path
    return not _TEST_DIRECTORIES.isdisjoint(below.parent.parts)


def _is_test_code(file: str, scope: PurePosixPath) -> bool:
    name = PurePosixPath(file).name
    return in_test_directory(file, scope) or any(
        fnmatchcase(name, pattern) for pattern in _TEST_FILE_NAMES
    )


def own_output_matcher(
    project_root: Path, own_output: tuple[Path, str] | None
) -> Callable[[str], bool]:
    """Match files directly in the output directory, named as this scope's output."""
    if own_output is None:
        return lambda file: False
    root = project_root.resolve()
    out_dir = own_output[0].resolve()
    label = safe_scope_label(own_output[1])
    hyde_names = {
        f"{kind}_{mode}_{label}.md"
        for kind in ("hyde_plan", "hyde_scope_prompt")
        for mode in ("arch", "ops")
    }

    def matches(file: str) -> bool:
        path = root / file
        return path.parent == out_dir and (
            path.name.startswith(f"{label}_") or path.name in hyde_names
        )

    return matches


def select_scope_files(
    *,
    scope_path: Path,
    project_root: Path,
    config: Config | None,
    own_output: tuple[Path, str] | None = None,
) -> ScopeSelection:
    """Apply the C4 source rules after indexing includes and ignores.

    ``own_output`` is the output directory and scope label of this run: without
    it, a run with ``--out`` inside the project reads its previous output.
    """
    indexing = config.indexing if config is not None else IndexingConfig()
    collected = collect_scope_files(
        scope_path=scope_path,
        project_root=project_root,
        hyde_cfg=HydeConfig(
            max_scope_files=0,
            max_snippet_files=0,
            max_snippet_chars=0,
            max_completion_tokens=1,
            max_snippet_tokens=1,
        ),
        include_patterns=list(indexing.include),
        indexing_excludes=indexing.get_effective_config_excludes(),
        ignore_sources=indexing.resolve_ignore_sources(),
        gitignore_backend=indexing.gitignore_backend,
        workspace_root_only_gitignore=indexing.workspace_gitignore_nonrepo,
    )
    settings = c4_settings(config)
    scope = PurePosixPath(scope_path.relative_to(project_root).as_posix())
    excludes = compile_excludes(settings)
    is_own_output = own_output_matcher(project_root, own_output)

    files: list[str] = []
    test_code = pattern = 0
    for file in collected:
        if settings.exclude_test_code and _is_test_code(file, scope):
            test_code += 1
        elif matches_exclude(file, excludes):
            pattern += 1
        elif not is_own_output(file):
            files.append(file)
    return ScopeSelection(sorted(files), test_code, pattern)


def list_scope_files(
    *,
    scope_path: Path,
    project_root: Path,
    config: Config | None,
    own_output: tuple[Path, str] | None = None,
) -> list[str]:
    """Return project-relative paths, honoring indexing includes and ignores."""
    return select_scope_files(
        scope_path=scope_path,
        project_root=project_root,
        config=config,
        own_output=own_output,
    ).files
