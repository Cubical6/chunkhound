"""Contracts for lazy, atomic, and durable human-input storage."""

import shutil
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

from chunkhound.providers.database.duckdb_provider import DuckDBProvider
from tests.contracts.mock_embed import MockEmbeddingProvider
from tests.contracts.pipeline_harness import index_with_python


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setattr(
        "chunkhound.providers.database.serial_executor.COMPACT_SAMPLE_INTERVAL", 0
    )


@pytest.fixture
def file_backed_db(tmp_path: Path, clean_environment: None) -> Iterator[DuckDBProvider]:
    db = DuckDBProvider(tmp_path / "input.duckdb", base_directory=tmp_path)
    db.connect()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
async def populated_db(
    tmp_path: Path, clean_environment: None
) -> AsyncIterator[DuckDBProvider]:
    root = tmp_path / "project"
    root.mkdir()
    (root / "example.py").write_text(
        "def example():\n    return 42\n", encoding="utf-8"
    )
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    result = await index_with_python(
        root, db_dir, skip_embeddings=False, embedding_provider=MockEmbeddingProvider()
    )
    assert not result.errors
    assert result.chunks_written > 0
    assert result.embeddings_generated > 0
    db = DuckDBProvider(db_dir / "chunks.db", base_directory=root)
    db.connect()
    try:
        yield db
    finally:
        db.close()


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "batch_id": "00000000-0000-4000-8000-000000000001",
            "op": "put",
            "element_id": "concept:root:team",
            "payload": '{"kind":"concept","name":"team","status":"proposed"}',
            "payload_version": 1,
            "author_name": "A. Developer",
            "author_email": "dev@example.com",
            "entry_point": "cli",
            "recorded_at": datetime(2026, 11, 13, 12, 0, 0),
        },
        {
            "batch_id": "00000000-0000-4000-8000-000000000001",
            "op": "confirm",
            "element_id": "concept:root:team",
            "payload": None,
            "payload_version": 1,
            "author_name": "A. Developer",
            "author_email": None,
            "entry_point": "mcp",
            "recorded_at": datetime(2026, 11, 13, 12, 0, 0),
        },
    ]


def _domain_tables(db: DuckDBProvider) -> list[dict[str, Any]]:
    return db.execute_query(
        "SELECT table_name, sql FROM duckdb_tables() "
        "WHERE starts_with(table_name, 'domain_') ORDER BY table_name"
    )


def test_database_without_domain_input_is_unchanged(
    populated_db: DuckDBProvider,
) -> None:
    db = populated_db
    assert db.supports_domain_input
    assert db.load_domain_input() == []
    assert db.append_domain_input([]) == []
    assert _domain_tables(db) == []
    before = db.get_stats()
    db.compact_database()
    assert db.load_domain_input() == []
    assert _domain_tables(db) == []
    assert db.get_stats() == before


def test_human_input_survives_python_compaction(populated_db: DuckDBProvider) -> None:
    db = populated_db
    assert db.append_domain_input(_rows()) == [1, 2]
    # Future domain tables and columns must survive without provider knowledge.
    db.execute_query("ALTER TABLE domain_input ADD COLUMN future_field VARCHAR")
    db.execute_query(
        'CREATE TABLE "domain_extra""notes" ('
        "id BIGINT PRIMARY KEY, note VARCHAR NOT NULL DEFAULT 'pending', "
        "CHECK (length(note) > 0))"
    )
    db.execute_query('INSERT INTO "domain_extra""notes" (id) VALUES (1), (2)')
    db.execute_query("CREATE TABLE domainXunowned (id BIGINT)")
    before = db.load_domain_input()
    ddl_before = _domain_tables(db)
    stats_before = db.get_stats()

    db.compact_database()

    assert db.load_domain_input() == before
    assert _domain_tables(db) == ddl_before
    assert db.get_stats() == stats_before
    assert db.execute_query('SELECT * FROM "domain_extra""notes" ORDER BY id') == [
        {"id": 1, "note": "pending"},
        {"id": 2, "note": "pending"},
    ]
    with pytest.raises(duckdb.ConstraintException):
        db.execute_query('INSERT INTO "domain_extra""notes" VALUES (3, NULL)')
    assert not db.execute_query(
        "SELECT table_name FROM duckdb_tables() WHERE table_name = 'domainXunowned'"
    )
    assert db.append_domain_input(_rows()) == [3, 4]
    assert [row["seq"] for row in db.load_domain_input()] == [1, 2, 3, 4]


def test_human_input_survives_wal_removal(
    file_backed_db: DuckDBProvider, tmp_path: Path
) -> None:
    db = file_backed_db
    db.append_domain_input(_rows())
    expected = db.load_domain_input()
    copy_path = tmp_path / "without-wal.duckdb"
    # Copy while the original connection is still open: close() must not be
    # what makes these records durable. Deliberately do not copy the WAL.
    shutil.copyfile(db.db_path, copy_path)
    assert not Path(f"{copy_path}.wal").exists()
    copy = DuckDBProvider(copy_path, base_directory=tmp_path)
    copy.connect()
    try:
        assert copy.load_domain_input() == expected
    finally:
        copy.close()


def test_append_batches_are_atomic_and_ordered(file_backed_db: DuckDBProvider) -> None:
    db = file_backed_db
    rows = _rows()
    assert db.append_domain_input(rows) == [1, 2]
    expected = [{"seq": seq, **row} for seq, row in enumerate(rows, start=1)]
    assert db.load_domain_input() == expected

    invalid_rows = _rows()
    invalid_rows[1]["payload_version"] = None
    with pytest.raises(duckdb.ConstraintException):
        db.append_domain_input(invalid_rows)
    assert db.load_domain_input() == expected

    assert db.append_domain_input(rows) == [3, 4]
    assert db.load_domain_input() == expected + [
        {"seq": seq, **row} for seq, row in enumerate(rows, start=3)
    ]
