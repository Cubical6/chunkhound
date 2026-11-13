"""Fixture copies and fixed repository identities for Git-free reader tests."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from chunkhound.domain_model.identity import repository_key
from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure
from chunkhound.domain_model.structure.files import repository_paths

COMMIT = "1111111111111111111111111111111111111111"


def run_fixture(source: Path, destination: Path) -> StructureExtraction:
    shutil.copytree(source, destination)
    for path in sorted(destination.rglob("dot-gitignore")):
        path.rename(path.with_name(".gitignore"))
    repositories = tuple(
        RepositoryRef(key=repository_key(path), path=path, commit=COMMIT, dirty=False)
        for path in repository_paths(destination)
    )
    return build_structure(destination, repositories, None)


@pytest.fixture
def extract_fixture(tmp_path: Path) -> Callable[[str], StructureExtraction]:
    def extract(name: str) -> StructureExtraction:
        return run_fixture(Path(__file__).parent / "fixtures" / name, tmp_path / name)

    return extract


@pytest.fixture
def isolated_git(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path_factory.mktemp("git-home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "A. Developer")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "dev@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "A. Developer")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "dev@example.com")
