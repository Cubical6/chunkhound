"""Deterministic migration ordering shared by storage readers."""

import re
from pathlib import PurePosixPath


def natural_order(path: str) -> tuple[str, tuple[tuple[int, int | str], ...], str]:
    """Sort directories lexically, then filename digit runs numerically."""
    source = PurePosixPath(path)
    parts = tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in re.split(r"(\d+)", source.name)
    )
    return str(source.parent), parts, source.name
