"""Mtime bounds matching src/pipeline/differ.rs; both sides must agree."""

MIN_MTIME_EPOCH_SECONDS = -9_000_000_000_000.0
MAX_MTIME_EPOCH_SECONDS = 9_000_000_000_000.0


def clamp_mtime(seconds: float) -> float:
    """Keep epoch seconds within the shared, DuckDB-safe mtime range."""
    return max(MIN_MTIME_EPOCH_SECONDS, min(seconds, MAX_MTIME_EPOCH_SECONDS))
