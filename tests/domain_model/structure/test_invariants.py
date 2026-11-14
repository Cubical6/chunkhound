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


@pytest.mark.parametrize("syntax", ["php", "xml", "graphql"])
def test_deep_syntax_preserves_recognized_facts(tmp_path: Path, syntax: str) -> None:
    depth = 1500
    if syntax == "php":
        path = tmp_path / "database/migrations/V1.php"
        text = (
            "<?php return new class { public function up() { $x = "
            + "(" * depth
            + "1"
            + ")" * depth
            + ";"
            + "Schema::create('notes', function ($table) { $table->id(); }); }};"
        )
    elif syntax == "graphql":
        path = tmp_path / "schema.graphql"
        text = (
            "type Note @unused(value: "
            + "[" * depth
            + "1"
            + "]" * depth
            + ") { id: ID! }"
        )
    else:
        path = tmp_path / "app/code/Acme/Notes/etc/db_schema.xml"
        path.parent.mkdir(parents=True)
        (path.parent.parent / "registration.php").write_text(
            "<?php ComponentRegistrar::register("
            "ComponentRegistrar::MODULE, 'Acme_Notes', __DIR__);"
        )
        (path.parent / "module.xml").write_text(
            '<config><module name="Acme_Notes"/></config>'
        )
        # XML's scanner limits open-tag storage; 500 short tags still produce
        # over 1000 AST levels (element/content), beyond Python recursion.
        depth = 500
        text = (
            "<schema>"
            + "<a>" * depth
            + "</a>" * depth
            + '<table name="notes"><column name="id" xsi:type="int"/>'
            + "</table></schema>"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    repo = RepositoryRef(key="root", path=".", commit=COMMIT, dirty=False)
    result = build_structure(tmp_path, (repo,))
    (fact,) = result.model.fact_types
    assert fact.name == ("Note" if syntax == "graphql" else "notes")
    assert not any(f.reason == "unreadable_source" for f in result.findings)
    assert parse_structure(dump_structure(result)) == result


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
