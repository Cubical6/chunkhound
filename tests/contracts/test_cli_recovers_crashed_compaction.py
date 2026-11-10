"""CLI commands must recover a crashed swap before rejecting or opening the DB."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.contracts.pipeline_harness import chunk_ids_for_path, index_with_rust
from tests.contracts.test_diff_recovers_crashed_compaction import (
    FIXTURE_DIR,
    _simulate_crashed_phase1_compaction,
)

pytestmark = pytest.mark.xdist_group(name="native_ext_fs_mutation")


def _run_cli(project: Path, db_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "chunkhound.api.cli.main", *args, "--db", str(db_dir)],
        cwd=project,
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("CHUNKHOUND_")},
            "CHUNKHOUND_USE_RUST": "1",
            "CHUNKHOUND_NO_RICH": "1",
        },
        capture_output=True,
        text=True,
        timeout=90,
    )


@pytest.fixture
def crashed_db(tmp_path: Path) -> tuple[Path, Path, dict[str, list[int]]]:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_DIR, project)
    db_dir = tmp_path / "db"
    # Write twice so a fresh DB cannot accidentally reproduce the original ids.
    for _ in range(2):
        index_with_rust(project, db_dir, skip_embeddings=True)
    ids = {p.name: chunk_ids_for_path(db_dir, p.name) for p in project.iterdir()}
    assert ids["main.py"]
    _simulate_crashed_phase1_compaction(db_dir)
    (db_dir / "chunks.db.compact").write_bytes(b"incomplete copy")
    (db_dir / "chunks.db.compact.wal").write_bytes(b"incomplete WAL")
    return project, db_dir, ids


def _assert_recovered(db_dir: Path) -> None:
    assert (db_dir / "chunks.db").is_file()
    for suffix in (".old", ".swap_intent", ".compact", ".compact.wal"):
        assert not (db_dir / f"chunks.db{suffix}").exists()


def test_cli_search_returns_existing_results_after_crashed_compaction(crashed_db):
    project, db_dir, _ = crashed_db
    result = _run_cli(project, db_dir, "search", "calculate_tax", ".", "--regex")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "main.py" in result.stdout
    assert "calculate_tax" in result.stdout
    _assert_recovered(db_dir)
    assert "Recover" in result.stderr


def test_cli_index_preserves_unchanged_chunk_ids_after_crashed_compaction(crashed_db):
    project, db_dir, ids_before = crashed_db
    result = _run_cli(project, db_dir, "index", ".", "--no-embeddings")
    assert result.returncode == 0, result.stdout + result.stderr
    _assert_recovered(db_dir)
    assert {
        path: chunk_ids_for_path(db_dir, path) for path in ids_before
    } == ids_before
    assert "Recover" in result.stderr
