"""Every reader fixture obeys the same pure, cited, deterministic contract."""

import shutil
from pathlib import Path

import pytest

from chunkhound.domain_model.identity import repository_key
from chunkhound.domain_model.loader import COLLECTIONS, parse_model
from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    dump_structure,
    parse_structure,
)
from chunkhound.domain_model.structure.extract import build_structure
from chunkhound.domain_model.structure.files import repository_paths

FIXTURES = Path(__file__).parent / "fixtures"
COMMIT = "1111111111111111111111111111111111111111"


@pytest.mark.parametrize(
    "fixture", sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())
)
def test_fixture_is_valid_cited_deterministic_and_read_only(
    fixture: str, tmp_path: Path
) -> None:
    project = tmp_path / fixture
    shutil.copytree(FIXTURES / fixture, project)
    for path in sorted(project.rglob("dot-gitignore")):
        path.rename(path.with_name(".gitignore"))

    def snapshot() -> dict[str, bytes | None]:
        return {
            p.relative_to(project).as_posix(): p.read_bytes() if p.is_file() else None
            for p in project.rglob("*")
        }

    before = snapshot()
    repositories = tuple(
        RepositoryRef(key=repository_key(p), path=p, commit=COMMIT, dirty=False)
        for p in repository_paths(project)
    )
    first = build_structure(project, repositories)
    second = build_structure(project, repositories)
    dumped = dump_structure(first)
    assert dumped == dump_structure(second)
    assert str(tmp_path) not in dumped
    assert snapshot() == before
    assert dump_structure(parse_structure(dumped)) == dumped
    assert parse_model(first.model.model_dump(mode="json")) == first.model
    for collection in COLLECTIONS:
        for element in getattr(first.model, collection):
            assert element.status == "extracted"
            assert element.citations
            assert not element.human_sources

    def verify_citations(value: object) -> None:
        if isinstance(value, dict):
            if {
                "repository",
                "path",
                "start_line",
                "end_line",
                "commit",
            } <= value.keys():
                path = project / value["path"]
                assert not Path(value["path"]).is_absolute()
                assert (
                    1
                    <= value["start_line"]
                    <= value["end_line"]
                    <= len(path.read_text().splitlines())
                )
                assert value["commit"] == COMMIT
                assert value["repository"] in {r.key for r in repositories}
            for child in value.values():
                verify_citations(child)
        elif isinstance(value, list):
            for child in value:
                verify_citations(child)

    verify_citations(first.model_dump(mode="json"))
