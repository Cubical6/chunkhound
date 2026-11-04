"""C4 output: the content-addressed internal pair and the AutoDoc contract."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from chunkhound.code_mapper.c4.contract import Contract
from chunkhound.code_mapper.c4.model import C4Evidence, C4Model
from chunkhound.utils.text import safe_scope_label


def compute_run_id(model: C4Model, evidence: C4Evidence) -> str:
    """Hash both canonical documents, excluding their previous run identifiers."""
    model_data = model.model_dump(mode="json", by_alias=True)
    evidence_data = evidence.model_dump(mode="json", by_alias=True)
    del model_data["run"]["id"]
    del evidence_data["run_id"]

    def canonical(value: dict[str, Any]) -> bytes:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    return hashlib.sha256(
        canonical(model_data) + b"\n" + canonical(evidence_data)
    ).hexdigest()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    """Replace a JSON file on the same filesystem and remove failed-write debris."""
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_c4_pair(
    *, out_dir: Path, scope_label: str, model: C4Model, evidence: C4Evidence
) -> tuple[Path, Path]:
    """Assign one stable run id and publish evidence followed by its model."""
    run_id = compute_run_id(model, evidence)
    model.run.id = run_id
    evidence.run_id = run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_scope = safe_scope_label(scope_label)
    model_path = out_dir / f"{safe_scope}_c4_map_model.json"
    evidence_path = out_dir / f"{safe_scope}_c4_map_evidence.json"
    _write_json_atomic(evidence_path, evidence.model_dump(mode="json", by_alias=True))
    _write_json_atomic(model_path, model.model_dump(mode="json", by_alias=True))
    return model_path, evidence_path


def write_c4_contract(*, out_dir: Path, scope_label: str, contract: Contract) -> Path:
    """Publish the version 1 contract under the name AutoDoc selects."""
    path = out_dir / f"{safe_scope_label(scope_label)}_c4_model.json"
    _write_json_atomic(path, contract.to_dict())
    return path


def remove_old_c4_output(*, out_dir: Path, scope_label: str) -> None:
    """Remove the evidence file a run from before the map pair left behind."""
    path = out_dir / f"{safe_scope_label(scope_label)}_c4_evidence.json"
    path.unlink(missing_ok=True)
