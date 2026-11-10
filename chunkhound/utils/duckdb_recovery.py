"""Recover native DuckDB compaction swaps before preflight or connection opens."""

import os
import sys
from pathlib import Path

from loguru import logger

import chunkhound_native


def recover_duckdb_compaction(db_path: Path | str, *, read_only: bool = False) -> None:
    """Run Rust's filesystem-only recovery without creating or opening a DB.

    Read-only observers must leave every swap artifact untouched. Recovery
    errors propagate: opening a fresh DB after a failed recovery risks data loss.
    """
    if read_only or str(db_path) == ":memory:":
        return
    if chunkhound_native.recover_compaction_swap(str(db_path)):
        message = (
            f"Recovered DuckDB database from interrupted compaction swap: {db_path}"
        )
        if os.environ.get("CHUNKHOUND_MCP_MODE") == "1":
            # MCP disables loguru sinks; diagnostics must still reach stderr.
            sys.stderr.write(message + "\n")
        else:
            logger.warning(message)
