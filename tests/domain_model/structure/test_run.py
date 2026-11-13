"""Extraction and CLI contracts, with actual files and isolated Git repositories."""

import json
import subprocess
from pathlib import Path

import pytest

from chunkhound.domain_model.loader import parse_model
from chunkhound.domain_model.structure import extract as extraction_module
from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    dump_structure,
    parse_structure,
)
from chunkhound.domain_model.structure.extract import (
    ReadContext,
    StructureExtractionError,
    build_structure,
    extract_structure,
)
from chunkhound.domain_model.structure.files import MAX_SOURCE_BYTES, select_files

COMMIT = "1" * 40
ROOT = Path(__file__).resolve().parents[3]


def git(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def repository(project: Path, *, commit: bool = True) -> None:
    project.mkdir(parents=True, exist_ok=True)
    git(project, "init", "-q")
    if commit:
        git(project, "commit", "--allow-empty", "-qm", "Initial example")


def cli(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--no-sync", "chunkhound", "domain", str(project), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_empty_project_gives_empty_extraction(tmp_path: Path) -> None:
    repo = RepositoryRef(key="root", path=".", commit=COMMIT, dirty=False)
    result = build_structure(tmp_path, (repo,))
    assert parse_structure(dump_structure(result)) == result
    assert parse_model(result.model.model_dump(mode="json")) == result.model
    assert result.repositories == (repo,)
    assert result.model.concepts == result.anchors == result.findings == ()
    assert list(tmp_path.iterdir()) == []


def test_repository_without_commit_stops_the_run(
    tmp_path: Path, isolated_git: None
) -> None:
    repository(tmp_path, commit=False)
    with pytest.raises(StructureExtractionError) as error:
        extract_structure(tmp_path)
    assert error.value.code == "repository_without_commit"
    result = cli(tmp_path, "--extract-structure")
    assert result.returncode == 2
    assert "repository_without_commit" in result.stderr
    assert not result.stdout


def test_repository_key_collision_stops_the_run(
    tmp_path: Path, isolated_git: None
) -> None:
    repository(tmp_path)
    repository(tmp_path / "a_b")
    repository(tmp_path / "a-b")
    with pytest.raises(StructureExtractionError) as error:
        extract_structure(tmp_path)
    assert error.value.code == "repository_key_collision"


def test_nested_repository_has_its_own_commit(
    tmp_path: Path, isolated_git: None
) -> None:
    repository(tmp_path)
    repository(tmp_path / "backend")
    result = extract_structure(tmp_path)
    repos = {repo.key: repo for repo in result.repositories}
    assert repos["root"].commit == git(tmp_path, "rev-parse", "HEAD")
    assert repos["backend"].commit == git(tmp_path / "backend", "rev-parse", "HEAD")
    assert repos["backend"].path == "backend"
    assert not any(repo.dirty for repo in result.repositories)


def test_cli_extract_structure_prints_json(tmp_path: Path, isolated_git: None) -> None:
    repository(tmp_path)
    result = cli(tmp_path, "--extract-structure")
    assert result.returncode == 0, result.stderr
    assert len(parse_structure(json.loads(result.stdout)).repositories) == 1
    assert not (tmp_path / ".chunkhound").exists()
    assert cli(tmp_path, "--extract-structure").stdout == result.stdout


def test_cli_without_mode_still_reports_not_available(tmp_path: Path) -> None:
    result = cli(tmp_path)
    assert result.returncode == 2
    assert "extraction is not available yet" in result.stderr
    assert not (tmp_path / ".chunkhound").exists()


class SourceReader:
    name = "example"
    patterns = ("*.sql",)

    def read(self, ctx: ReadContext) -> None:
        for path in ctx.paths:
            ctx.read(path)


def test_file_selection_respects_gitignore_unless_requested(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("vendor/\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "schema.sql").write_text("SELECT 1;\n")
    (tmp_path / "own.sql").write_text("SELECT 1;\n")
    assert select_files(tmp_path, ("*.sql",)) == ("own.sql",)
    assert select_files(tmp_path, ("*.sql",), ignore_gitignore=True) == (
        "own.sql",
        "vendor/schema.sql",
    )


def test_unreadable_file_does_not_stop_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "large.sql").write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
    (tmp_path / "gone.sql").write_text("SELECT 1;\n")
    (tmp_path / "ok.sql").write_text("SELECT 1;\n")
    seen = []

    class Reader(SourceReader):
        def read(self, ctx: ReadContext) -> None:
            (tmp_path / "gone.sql").unlink()
            for path in ctx.paths:
                source = ctx.read(path)
                if source:
                    seen.append(source.path)

    monkeypatch.setattr(extraction_module, "READERS", [Reader()])
    repo = RepositoryRef(key="root", path=".", commit=COMMIT, dirty=False)
    result = build_structure(tmp_path, (repo,))
    assert {finding.reason for finding in result.findings} == {
        "source_too_large",
        "unreadable_source",
    }
    assert seen == ["ok.sql"]


def test_failed_reader_does_not_stop_other_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "schema.sql").write_text("SELECT 1;\n")
    seen = []

    class FailedReader(SourceReader):
        def read(self, ctx: ReadContext) -> None:
            raise ValueError("Cannot interpret this source")

    class NextReader(SourceReader):
        def read(self, ctx: ReadContext) -> None:
            seen.extend(ctx.paths)

    monkeypatch.setattr(extraction_module, "READERS", [FailedReader(), NextReader()])
    repo = RepositoryRef(key="root", path=".", commit=COMMIT, dirty=False)
    result = build_structure(tmp_path, (repo,))
    assert seen == ["schema.sql"]
    assert result.findings[0].reason == "unreadable_source"


def test_only_read_files_make_repository_dirty(
    tmp_path: Path, isolated_git: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path)
    (tmp_path / "schema.sql").write_text("SELECT 1;\n")
    git(tmp_path, "add", "schema.sql")
    git(tmp_path, "commit", "-qm", "Add example schema")
    (tmp_path / "unread.txt").write_text("untracked\n")
    monkeypatch.setattr(extraction_module, "READERS", [SourceReader()])
    assert not extract_structure(tmp_path).repositories[0].dirty
    (tmp_path / "untracked.sql").write_text("SELECT 1;\n")
    assert extract_structure(tmp_path).repositories[0].dirty
    (tmp_path / "untracked.sql").unlink()
    (tmp_path / "schema.sql").write_text("SELECT 2;\n")
    assert extract_structure(tmp_path).repositories[0].dirty


def test_read_ignored_files_leave_repository_clean(
    tmp_path: Path, isolated_git: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path)
    (tmp_path / ".gitignore").write_text("vendor/\n")
    (tmp_path / "schema.sql").write_text("SELECT 1;\n")
    git(tmp_path, "add", ".gitignore", "schema.sql")
    git(tmp_path, "commit", "-qm", "Add example schema and ignore rules")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "schema.sql").write_text("SELECT 2;\n")
    seen = []

    class VendorReader(SourceReader):
        def read(self, ctx: ReadContext) -> None:
            seen.append(ctx.read("vendor/schema.sql"))

    monkeypatch.setattr(extraction_module, "READERS", [VendorReader()])
    result = extract_structure(tmp_path)
    assert len(seen) == 1 and seen[0] is not None
    assert not result.repositories[0].dirty


def test_vendor_checkout_sources_belong_to_declared_root_repository(
    tmp_path: Path, isolated_git: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path)
    (tmp_path / ".gitignore").write_text("vendor/\n")
    (tmp_path / "schema.sql").write_text("SELECT 1;\n")
    git(tmp_path, "add", ".gitignore", "schema.sql")
    git(tmp_path, "commit", "-qm", "Add example schema and ignore rules")
    package = tmp_path / "vendor" / "acme" / "pkg"
    repository(package)
    (package / "x.php").write_text("<?php // Example source\n")
    seen = []

    class VendorReader(SourceReader):
        def read(self, ctx: ReadContext) -> None:
            path = "vendor/acme/pkg/x.php"
            source = ctx.read(path)
            if source is not None:
                seen.append((source.path, ctx.repository_of(path).key))

    monkeypatch.setattr(extraction_module, "READERS", [VendorReader()])
    result = extract_structure(tmp_path)
    assert [(repo.key, repo.path) for repo in result.repositories] == [("root", ".")]
    assert seen == [("vendor/acme/pkg/x.php", "root")]
    assert not result.findings
    assert not result.repositories[0].dirty


@pytest.mark.parametrize("failure", ["exception", "nonzero"])
def test_unavailable_git_status_marks_repository_dirty(
    tmp_path: Path,
    isolated_git: None,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    from chunkhound.utils.git_safe import GitCommandError, run_git

    repository(tmp_path)
    (tmp_path / "schema.sql").write_text("SELECT 1;\n")
    git(tmp_path, "add", "schema.sql")
    git(tmp_path, "commit", "-qm", "Add example schema")

    def git_with_failed_status(
        args: list[str], cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        if args[0] == "status":
            if failure == "exception":
                raise GitCommandError("git command timeout")
            return subprocess.CompletedProcess(
                args, 1, stdout="", stderr="status failed"
            )
        return run_git(args, cwd)

    monkeypatch.setattr(extraction_module, "run_git", git_with_failed_status)
    monkeypatch.setattr(extraction_module, "READERS", [SourceReader()])
    assert extract_structure(tmp_path).repositories[0].dirty
