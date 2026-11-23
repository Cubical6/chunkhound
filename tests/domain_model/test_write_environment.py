"""Environment and provenance contracts for the public human-input service."""

import getpass
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from chunkhound.domain_model.human_input import (
    DomainInputRejected,
    DomainInputUnavailable,
    load_human_input,
    write_human_input,
)
from chunkhound.providers.database.duckdb_provider import DuckDBProvider
from chunkhound.utils.git_safe import run_git


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def db(tmp_path: Path, clean_environment: None) -> Iterator[DuckDBProvider]:
    provider = DuckDBProvider(tmp_path / "input.duckdb", base_directory=tmp_path)
    provider.connect()
    try:
        yield provider
    finally:
        provider.close()


def test_write_records_author_time_and_entry_point(
    db: DuckDBProvider, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    backend = project / "backend"
    backend.mkdir()
    for directory in (project, backend):
        assert run_git(["init"], cwd=directory).returncode == 0
    assert run_git(["config", "user.name", "A. Developer"], cwd=backend).returncode == 0
    assert (
        run_git(["config", "user.email", "dev@example.com"], cwd=backend).returncode
        == 0
    )

    request = {
        "operations": [
            {
                "op": "put",
                "element": {"kind": "concept", "repository": repo, "term": "User"},
            }
            for repo in (".", "backend", "services-backend")
        ]
    }
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    result = write_human_input(
        request, provider=db, project_root=project, entry_point="mcp"
    )
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = db.load_domain_input()
    assert len(result.records) == len(rows) == 3
    assert len({row["recorded_at"] for row in rows}) == 1
    for row in rows:
        assert row["entry_point"] == "mcp"
        assert before <= row["recorded_at"] <= after
        if row["element_id"] == "concept:backend/user":
            assert (row["author_name"], row["author_email"]) == (
                "A. Developer",
                "dev@example.com",
            )
        else:
            assert (row["author_name"], row["author_email"]) == (
                getpass.getuser(),
                None,
            )
    assert len(load_human_input(db).model.concepts) == 3

    # A found name with no email remains a Git identity, not an OS fallback.
    assert run_git(["config", "--unset", "user.email"], cwd=backend).returncode == 0
    write_human_input(
        {"operations": [{"op": "confirm", "id": "concept:backend/user"}]},
        provider=db,
        project_root=project,
        entry_point="cli",
    )
    last = db.load_domain_input()[-1]
    assert (last["author_name"], last["author_email"], last["entry_point"]) == (
        "A. Developer",
        None,
        "cli",
    )
    previous = db.load_domain_input()
    dry_run = write_human_input(
        request, provider=db, project_root=project, entry_point="cli", dry_run=True
    )
    assert dry_run.dry_run and not dry_run.records
    assert db.load_domain_input() == previous
    with pytest.raises(DomainInputRejected):
        write_human_input(
            {"operations": []}, provider=db, project_root=project, entry_point="cli"
        )
    assert db.load_domain_input() == previous


def test_human_input_rejected_on_lancedb(
    tmp_path: Path, clean_environment: None
) -> None:
    pytest.importorskip("lancedb")
    from chunkhound.providers.database.lancedb_provider import LanceDBProvider

    provider = LanceDBProvider(tmp_path / "input.lancedb", base_directory=tmp_path)
    provider.connect()
    try:
        before = sorted(provider.execute_query("SELECT * FROM files"))
        with pytest.raises(DomainInputUnavailable) as error:
            write_human_input(
                {
                    "operations": [
                        {"op": "put", "element": {"kind": "concept", "term": "User"}}
                    ]
                },
                provider=provider,
                project_root=tmp_path,
                entry_point="cli",
            )
        assert [(issue.path, issue.code) for issue in error.value.issues] == [
            ("", "backend_not_supported")
        ]
        with pytest.raises(DomainInputUnavailable) as read_error:
            load_human_input(provider)
        assert read_error.value.issues[0].code == "backend_not_supported"
        assert sorted(provider.execute_query("SELECT * FROM files")) == before
    finally:
        provider.close()


def test_write_while_database_busy_reports_retry(
    db: DuckDBProvider, tmp_path: Path
) -> None:
    db.set_rust_pipeline_in_progress(True)
    try:
        db.release_for_rust_pipeline()
        with pytest.raises(DomainInputUnavailable) as error:
            write_human_input(
                {
                    "operations": [
                        {"op": "put", "element": {"kind": "concept", "term": "User"}}
                    ]
                },
                provider=db,
                project_root=tmp_path,
                entry_point="cli",
            )
        assert [(issue.path, issue.code) for issue in error.value.issues] == [
            ("", "database_busy")
        ]
        message = error.value.issues[0].message.lower()
        assert "nothing was written" in message
        assert "retry in a few seconds" in message
        with pytest.raises(DomainInputUnavailable) as read_error:
            load_human_input(db)
        assert read_error.value.issues[0].code == "database_busy"
    finally:
        db.set_rust_pipeline_in_progress(False)
        db.connect()
    assert db.load_domain_input() == []


def test_human_input_from_payload_version_1_loads(db: DuckDBProvider) -> None:
    row = {
        "batch_id": "00000000-0000-0000-0000-000000000001",
        "op": "put",
        "element_id": "concept:root/user",
        "payload": (
            '{"kind":"concept","repository":".","term":"User",'
            '"status":"confirmed","plural":null,"definition":null,"synonyms":[]}'
        ),
        "payload_version": 1,
        "author_name": "A. Developer",
        "author_email": "dev@example.com",
        "entry_point": "cli",
        "recorded_at": datetime(2026, 11, 13, 12, 0, 0),
    }
    records = db.append_domain_input([row])
    stored = db.load_domain_input()
    view = load_human_input(db)
    (concept,) = view.model.concepts
    assert (concept.id, concept.term, concept.status) == (
        "concept:root/user",
        "User",
        "confirmed",
    )
    (source,) = concept.human_sources
    assert (
        source.record,
        source.author_name,
        source.author_email,
        source.entry_point,
    ) == (records[0], "A. Developer", "dev@example.com", "cli")
    assert source.recorded_at == "2026-11-13T12:00:00Z"
    assert db.load_domain_input() == stored

    # Unknown future payloads fail clearly and never migrate stored history.
    db.append_domain_input([{**row, "payload_version": 2}])
    future_stored = db.load_domain_input()
    with pytest.raises(ValueError, match="written by a newer ChunkHound"):
        load_human_input(db)
    assert db.load_domain_input() == future_stored
