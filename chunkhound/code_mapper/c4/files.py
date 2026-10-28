"""Collect the same indexing scope as HyDE, without sampling its files."""

from pathlib import Path

from chunkhound.code_mapper.models import HydeConfig
from chunkhound.code_mapper.scope import collect_scope_files
from chunkhound.core.config.config import Config
from chunkhound.core.config.indexing_config import IndexingConfig


def list_scope_files(
    *, scope_path: Path, project_root: Path, config: Config | None
) -> list[str]:
    """Return project-relative paths, honoring indexing includes and ignores."""
    indexing = config.indexing if config is not None else IndexingConfig()
    return sorted(
        collect_scope_files(
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
    )
