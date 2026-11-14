"""Opt-in configuration for the local decision log."""

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class DecisionLogConfig(BaseModel):
    """Local JSONL logging; query text is stored verbatim and never uploaded."""

    enabled: bool = Field(default=False, description="Enable the local decision log")
    path: Path | None = Field(
        default=None,
        description="Log path (default: <projectroot>/.chunkhound/decisions.jsonl)",
    )
    max_size_mb: float = Field(
        default=50,
        gt=0,
        allow_inf_nan=False,
        description="Rotate above this size in MiB, keeping one generation",
    )

    @classmethod
    def load_from_env(cls) -> dict[str, Any]:
        """Load CHUNKHOUND_DECISION_LOG__* environment overrides."""
        config: dict[str, Any] = {}
        if enabled := os.getenv("CHUNKHOUND_DECISION_LOG__ENABLED"):
            config["enabled"] = enabled.lower() in ("true", "1", "yes")
        if path := os.getenv("CHUNKHOUND_DECISION_LOG__PATH"):
            config["path"] = path
        if max_size := os.getenv("CHUNKHOUND_DECISION_LOG__MAX_SIZE_MB"):
            try:
                config["max_size_mb"] = float(max_size)
            except ValueError:
                pass
        return config
