"""Extreme file dates must not poison incremental mtime refreshes."""

import os
from pathlib import Path

import pytest

from chunkhound.core.models import File
from chunkhound.core.types.common import Language
from chunkhound.providers.database.duckdb_provider import DuckDBProvider
from chunkhound.services.rust_incremental_precheck import classify_files
from chunkhound.utils.hashing import compute_file_hash


@pytest.mark.parametrize("mtime", [-1e13, 1e13])
def test_extreme_mtime_does_not_poison_unchanged_file_refresh(
    tmp_path: Path, mtime: float
):
    extreme = tmp_path / "extreme.py"
    normal = tmp_path / "normal.py"
    files = [extreme, normal]
    for path in files:
        path.write_text("value = 1\n")
    ns = int(mtime) * 1_000_000_000
    try:
        os.utime(extreme, ns=(ns, ns))
    except (OSError, OverflowError, ValueError) as exc:
        pytest.skip(f"filesystem cannot set extreme mtime: {exc}")
    if extreme.stat().st_mtime != mtime:
        pytest.skip("filesystem does not retain the requested extreme mtime")

    db = DuckDBProvider(tmp_path / "index.duckdb", base_directory=tmp_path)
    db.connect()
    try:
        # Seed ordinary dates, then refresh both files together after their
        # dates change without any content change (as in a fresh checkout).
        for path in files:
            db.insert_file(
                File(
                    path=path.name,
                    mtime=1000.0,
                    size_bytes=path.stat().st_size,
                    language=Language.PYTHON,
                    content_hash=compute_file_hash(path),
                )
            )
        os.utime(normal, ns=(2_000_000_000_000, 2_000_000_000_000))

        def rows():
            return db.execute_query(
                "SELECT path, EXTRACT(EPOCH FROM modified_time::TIMESTAMPTZ) "
                "AS mtime, size, content_hash FROM files",
                [],
            )

        first = classify_files(rows(), files, tmp_path, 0.01)
        assert not first.changed
        assert first.skipped_by_hash == 2
        assert db.refresh_file_mtimes(first.refresh) == 2
        stored = {row["path"]: row["mtime"] for row in rows()}
        assert stored[normal.name] == normal.stat().st_mtime
        assert stored[extreme.name] == (9e12 if mtime > 0 else -9e12)

        second = classify_files(rows(), files, tmp_path, 0.01)
        assert not second.changed
        assert second.skipped_by_hash == 0
        assert not second.refresh
    finally:
        db.disconnect()
