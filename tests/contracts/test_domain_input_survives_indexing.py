"""Human input survives native compaction and non-incremental indexing."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from chunkhound.providers.database.duckdb_provider import DuckDBProvider
from tests.contracts.pipeline_harness import index_with_rust


@pytest.fixture(autouse=True)
def isolated_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    # Only the native indexing run should trigger compaction in these tests.
    monkeypatch.setattr(
        "chunkhound.providers.database.serial_executor.COMPACT_SAMPLE_INTERVAL", 0
    )


@pytest.fixture
def indexed_input(tmp_path: Path) -> tuple[Path, Path, list[dict[str, Any]]]:
    root = tmp_path / "project"
    root.mkdir()
    (root / "example.py").write_text(
        "def example():\n    return 42\n", encoding="utf-8"
    )
    db_dir = tmp_path / "db"
    result = index_with_rust(root, db_dir)
    assert not result.errors
    assert result.chunks_written > 0
    assert result.embeddings_generated > 0

    db = DuckDBProvider(db_dir / "chunks.db", base_directory=root)
    db.connect()
    try:
        assert db.load_domain_input() == []
        assert not db.execute_query(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE starts_with(table_name, 'domain_')"
        )
        common = {
            "batch_id": "00000000-0000-4000-8000-000000000001",
            "element_id": "concept:root:team",
            "payload_version": 1,
            "author_name": "A. Developer",
            "author_email": "dev@example.com",
            "entry_point": "cli",
            "recorded_at": datetime(2026, 11, 13, 12, 0, 0),
        }
        assert db.append_domain_input(
            [
                {
                    **common,
                    "op": "put",
                    "payload": '{"kind":"concept","name":"team","status":"proposed"}',
                },
                {**common, "op": "confirm", "payload": None},
            ]
        ) == [1, 2]
        expected = db.load_domain_input()
    finally:
        db.close()
    return root, db_dir, expected


def _assert_input_unchanged(
    root: Path, db_dir: Path, expected: list[dict[str, Any]]
) -> None:
    db = DuckDBProvider(db_dir / "chunks.db", base_directory=root)
    db.connect()
    try:
        assert db.load_domain_input() == expected
    finally:
        db.close()


def test_human_input_survives_rust_compaction(
    indexed_input: tuple[Path, Path, list[dict[str, Any]]],
) -> None:
    root, db_dir, expected = indexed_input
    phases: list[str] = []

    def progress_callback(phase: str, current: int, total: int) -> None:
        phases.append(phase)

    result = index_with_rust(
        root,
        db_dir,
        incremental=True,
        compaction_threshold=0.0,
        compaction_min_size_mb=0,
        progress_callback=progress_callback,
    )

    assert not result.errors
    assert "write-compact" in phases
    assert result.chunk_tuples
    assert result.embedding_tuples
    _assert_input_unchanged(root, db_dir, expected)


def test_human_input_survives_force_reindex(
    indexed_input: tuple[Path, Path, list[dict[str, Any]]],
) -> None:
    root, db_dir, expected = indexed_input

    result = index_with_rust(root, db_dir, incremental=False)

    assert not result.errors
    assert result.chunks_written > 0
    assert result.embeddings_generated > 0
    _assert_input_unchanged(root, db_dir, expected)
