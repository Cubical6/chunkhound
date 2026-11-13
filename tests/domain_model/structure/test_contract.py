"""Public output identities, round trips, and reference integrity."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.contract import (
    Anchor,
    DivergentClaim,
    Finding,
    Handler,
    Hint,
    RepositoryRef,
    anchor_id,
    dump_structure,
    parse_structure,
)
from chunkhound.domain_model.structure.extract import build_structure

COMMIT = "1" * 40


def test_structure_round_trips(tmp_path: Path) -> None:
    repo = RepositoryRef(key="root", path=".", commit=COMMIT, dirty=False)
    extraction = build_structure(tmp_path, (repo,))
    citation = Citation(
        repository="root",
        path="routes.php",
        start_line=1,
        end_line=1,
        commit=COMMIT,
    )
    identifier = anchor_id("root", "http", "POST", "/teams")
    hint = Hint(
        kind="operation",
        name=None,
        value="add",
        values=(),
        fact_type=None,
        role=None,
        citation=citation,
    )
    anchor = Anchor(
        id=identifier,
        repository="root",
        kind="http",
        method="POST",
        path="/teams",
        handler=Handler(symbol="TeamController@store", citation=None),
        source="laravel_routes",
        citations=(citation,),
        hints=(hint,),
    )
    finding = Finding(
        kind="unresolved",
        subject=identifier,
        reason="handler_not_found",
        detail=None,
        citations=(citation,),
    )
    extraction = extraction.model_copy(
        update={"anchors": (anchor,), "findings": (finding,)}
    )
    assert parse_structure(dump_structure(extraction)) == extraction
    assert dump_structure(extraction).endswith("\n")
    for field in ("subject", "role", "fact_type", "claim"):
        data = json.loads(dump_structure(extraction))
        if field == "subject":
            data["findings"][0][field] = "anchor:root/missing"
        elif field == "claim":
            data["divergent_claims"] = [
                DivergentClaim(
                    subject="role:root/team/unknown",
                    property="mandatory",
                    value=True,
                    source="eloquent",
                    citation=citation,
                ).model_dump(mode="json")
            ]
        else:
            data["anchors"][0]["hints"][0][field] = "role:root/team/unknown"
        with pytest.raises(ValueError, match="Unknown structure reference"):
            parse_structure(data)
    data = json.loads(dump_structure(extraction))
    data["model"]["unknown"] = []
    with pytest.raises(ValidationError):
        parse_structure(data)


def test_anchor_id_distinguishes_paths_that_slug_alike() -> None:
    first = anchor_id("root", "http", "GET", "/a/b")
    assert first != anchor_id("root", "http", "GET", "/a-b")
    assert first == anchor_id("root", "http", "GET", "/a/b")


def test_serialization_sorts_non_positional_collections(tmp_path: Path) -> None:
    repos = tuple(
        RepositoryRef(key=key, path=key, commit=COMMIT, dirty=False)
        for key in ("z", "a")
    )
    extraction = build_structure(tmp_path, repos)
    assert dump_structure(extraction) == dump_structure(
        extraction.model_copy(update={"repositories": tuple(reversed(repos))})
    )
