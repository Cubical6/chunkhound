from pathlib import Path

import pytest

from chunkhound.code_mapper.models import HydeConfig
from chunkhound.code_mapper.scope import collect_scope_files
from chunkhound.utils.git_safe import run_git


def test_collect_scope_files_respects_include_and_exclude(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace"
    scope_path = project_root / "scope"
    src_dir = scope_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    (src_dir / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    (src_dir / "secret.py").write_text("print('secret')\n", encoding="utf-8")
    (src_dir / "notes.xyz").write_text("not code\n", encoding="utf-8")

    hyde_cfg = HydeConfig(
        max_scope_files=1000,
        max_snippet_files=0,
        max_snippet_chars=0,
        max_completion_tokens=10,
        max_snippet_tokens=10,
    )

    file_paths = collect_scope_files(
        scope_path=scope_path,
        project_root=project_root,
        hyde_cfg=hyde_cfg,
        include_patterns=["**/*.py"],
        indexing_excludes=["scope/src/secret.py"],
        ignore_sources=["config"],
    )

    assert "scope/src/ok.py" in file_paths
    assert "scope/src/secret.py" not in file_paths
    assert "scope/src/notes.xyz" not in file_paths


def test_collect_scope_files_stops_at_max_scope_files(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace"
    scope_path = project_root / "scope"
    src_dir = scope_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    for i in range(10):
        (src_dir / f"f{i}.py").write_text("print('x')\n", encoding="utf-8")

    hyde_cfg = HydeConfig(
        max_scope_files=3,
        max_snippet_files=0,
        max_snippet_chars=0,
        max_completion_tokens=10,
        max_snippet_tokens=10,
    )

    file_paths = collect_scope_files(
        scope_path=scope_path,
        project_root=project_root,
        hyde_cfg=hyde_cfg,
        include_patterns=["**/*.py"],
        indexing_excludes=[],
        ignore_sources=["config"],
    )

    assert len(file_paths) == 3


@pytest.mark.parametrize("repository_kind", ["ordinary", "worktree", "workspace"])
@pytest.mark.parametrize("gitignore_enabled", [True, False])
@pytest.mark.parametrize("max_scope_files", [0, 200])
def test_map_scope_honors_local_git_excludes(
    tmp_path: Path, repository_kind: str, gitignore_enabled: bool, max_scope_files: int
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    run_git(["init", "-q"], cwd=repository).check_returncode()
    project_root = repository
    if repository_kind == "worktree":
        (repository / "seed.txt").write_text("seed\n")
        run_git(["add", "seed.txt"], cwd=repository).check_returncode()
        run_git(
            [
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "seed",
            ],
            cwd=repository,
        ).check_returncode()
        project_root = tmp_path / "linked"
        run_git(
            ["worktree", "add", "-qb", "linked", str(project_root)], cwd=repository
        ).check_returncode()
        repository = project_root
    elif repository_kind == "workspace":
        project_root = tmp_path

    metadata = run_git(["rev-parse", "--git-path", "info/exclude"], cwd=repository)
    metadata.check_returncode()
    exclude = Path(metadata.stdout.strip())
    if not exclude.is_absolute():
        exclude = repository / exclude
    exclude.write_text("/local.py\n/restored.py\n/reopened/*\n/pruned/\n")
    (repository / ".gitignore").write_text(
        "!/restored.py\n/reopened/*\n!/reopened/keep.py\n"
        "!/pruned/keep.py\n/blocked.py\n"
    )
    candidates = {
        "source.py",
        "local.py",
        "restored.py",
        "blocked.py",
        "config-only.py",
        "reopened/keep.py",
        "reopened/drop.py",
        "pruned/keep.py",
    }
    for relative in candidates:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n")
    git_visible = {
        relative
        for relative in candidates
        if run_git(
            ["check-ignore", "--no-index", "-q", relative], cwd=repository
        ).returncode
        == 1
    }
    assert git_visible == {
        "source.py",
        "restored.py",
        "reopened/keep.py",
        "config-only.py",
    }
    prefix = "repository/" if repository_kind == "workspace" else ""
    hyde_cfg = HydeConfig.from_env()
    hyde_cfg.max_scope_files = max_scope_files
    selected = collect_scope_files(
        scope_path=project_root,
        project_root=project_root,
        hyde_cfg=hyde_cfg,
        include_patterns=["**/*.py"],
        indexing_excludes=["**/.git/**", "**/config-only.py"],
        ignore_sources=["gitignore"] if gitignore_enabled else [],
    )
    expected = git_visible if gitignore_enabled else candidates
    assert set(selected) == {
        prefix + relative for relative in expected if relative != "config-only.py"
    }


def test_map_scope_keeps_nested_repository_ignore_boundaries(tmp_path: Path) -> None:
    for root in (tmp_path, tmp_path / "nested"):
        root.mkdir(exist_ok=True)
        run_git(["init", "-q"], cwd=root).check_returncode()
        for relative in ("source.py", "parent-only.py", "nested-only.py"):
            (root / relative).write_text("value = 1\n")
    (tmp_path / ".git/info/exclude").write_text("parent-only.py\nnested-only.py\n")
    (tmp_path / ".gitignore").write_text("/nested/gitignore-only.py\n")
    (tmp_path / "nested/.git/info/exclude").write_text("/nested-only.py\n")
    (tmp_path / "nested/gitignore-only.py").write_text("value = 1\n")
    selected = collect_scope_files(
        scope_path=tmp_path,
        project_root=tmp_path,
        hyde_cfg=HydeConfig.from_env(),
        include_patterns=["**/*.py"],
        indexing_excludes=["**/.git/**"],
        ignore_sources=["gitignore"],
    )
    assert set(selected) == {
        "source.py",
        "nested/source.py",
        "nested/parent-only.py",
        "nested/gitignore-only.py",
    }
