"""Regenerate the shipped C4 JSON schemas from their Pydantic contracts.

Run from the repository root: uv run python scripts/generate_c4_schemas.py
"""

import json
from pathlib import Path

from chunkhound.code_mapper.c4.model import C4Evidence, C4Model, MapLock


def main() -> None:
    schema_dir = (
        Path(__file__).resolve().parents[1] / "chunkhound/code_mapper/c4/schemas"
    )
    schema_dir.mkdir(parents=True, exist_ok=True)
    for name, model in (
        ("c4_model", C4Model),
        ("c4_evidence", C4Evidence),
        ("map_lock", MapLock),
    ):
        (schema_dir / f"{name}.schema.json").write_text(
            json.dumps(model.model_json_schema(by_alias=True), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
