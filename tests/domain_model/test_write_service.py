"""Human-input write/read contracts against a real temporary DuckDB provider."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from chunkhound.domain_model.human_input import (
    Author,
    DomainInputRejected,
    WriteRequest,
    apply_write,
    load_human_input,
)
from chunkhound.domain_model.identity import ground_fact_id
from chunkhound.domain_model.issues import Issue
from chunkhound.domain_model.loader import parse_model
from chunkhound.domain_model.model import ExchangeRule
from chunkhound.providers.database.duckdb_provider import DuckDBProvider

AUTHOR = Author(name="A. Developer", email="dev@example.com")
FACT_TYPE = "fact_type:backend/user-skill"
VALID_FACT = "ground_fact:backend/user-skill/4d435d18ce2b"
COUNTEREXAMPLE = "ground_fact:backend/user-skill/64420c4e0416"
RULE = "validation_rule:backend/user-skill/uniqueness/skill+user"
FIXTURE = Path(__file__).parent / "fixtures" / "write_request_example.json"


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def db(tmp_path: Path, clean_environment: None) -> Iterator[DuckDBProvider]:
    provider = DuckDBProvider(tmp_path / "input.duckdb", base_directory=tmp_path)
    provider.connect()
    try:
        yield provider
    finally:
        provider.close()


@pytest.fixture
def example() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def put(**body: Any) -> dict[str, Any]:
    return {"op": "put", "element": body}


def write(db: DuckDBProvider, operations: list[dict[str, Any]], **kwargs: Any):
    return apply_write(
        {"operations": operations},
        provider=db,
        author=AUTHOR,
        entry_point="cli",
        **kwargs,
    )


def rejected(db: DuckDBProvider, operations: list[dict[str, Any]]) -> tuple[Issue, ...]:
    before = db.load_domain_input()
    with pytest.raises(DomainInputRejected) as error:
        write(db, operations)
    assert db.load_domain_input() == before
    return error.value.issues


def domain_tables(db: DuckDBProvider) -> list[dict[str, Any]]:
    return db.execute_query(
        "SELECT table_name FROM duckdb_tables() "
        "WHERE starts_with(table_name, 'domain_')"
    )


def test_write_rejects_invalid_request_with_paths_and_writes_nothing(
    db: DuckDBProvider,
) -> None:
    issues = rejected(
        db,
        [
            put(
                kind="fact_type",
                repository="backend",
                name="ticket assignment",
                templates=["Ticket <ticket> is assigned to <agent>."],
                roles=[{"name": "ticket"}, {"name": "assignee"}],
                status="confirmed",
            )
        ],
    )
    assert issues == (
        Issue(
            "operations[0].element.templates[0]",
            "template_role_mismatch",
            "placeholder <agent> matches no role; roles are: ticket, assignee",
        ),
        Issue(
            "operations[0].element.templates[0]",
            "template_role_mismatch",
            "role 'assignee' does not appear in this template",
        ),
        Issue(
            "operations[0].element.status",
            "confirmed_without_ground_fact",
            "fact_type:backend/ticket-assignment would be confirmed without a valid "
            "ground fact; add a ground_fact put for it in the same request",
        ),
    )
    assert domain_tables(db) == []
    shape_issues = rejected(
        db,
        [
            put(kind="concept"),
            put(kind="fact_type", name="assignment", templates=["<agent>"], roles=[{}]),
        ],
    )
    assert {(issue.path, issue.code) for issue in shape_issues} == {
        ("operations[0].element.term", "missing_field"),
        ("operations[1].element.roles[0].name", "missing_field"),
    }
    issues = rejected(
        db,
        [
            put(kind="concept", term="!!!"),
            put(
                kind="fact_type",
                name="assignment",
                templates=["<agent>"],
                roles=[{"name": "agent"}, {"name": "Agent!"}],
            ),
            put(kind="ground_fact", fact_type="concept:root/team", values={}),
        ],
    )
    assert {(issue.path, issue.code) for issue in issues} >= {
        ("operations[0].element.term", "empty_key"),
        ("operations[1].element.roles[1].name", "duplicate_id"),
        ("operations[2].element.fact_type", "invalid_reference"),
    }
    assert domain_tables(db) == []


@pytest.mark.parametrize(
    "field",
    [
        "author",
        "author_name",
        "author_email",
        "entry_point",
        "recorded_at",
    ],
)
@pytest.mark.parametrize("level", ["request", "operation", "element", "role"])
def test_write_rejects_author_fields(
    db: DuckDBProvider, field: str, level: str
) -> None:
    request: dict[str, Any] = {
        "operations": [
            put(
                kind="fact_type",
                name="assignment",
                templates=["<agent>"],
                roles=[{"name": "agent"}],
            )
        ]
    }
    operation = request["operations"][0]
    target = {
        "request": request,
        "operation": operation,
        "element": operation["element"],
        "role": operation["element"]["roles"][0],
    }[level]
    target[field] = "untrusted"
    with pytest.raises(DomainInputRejected) as error:
        apply_write(request, provider=db, author=AUTHOR, entry_point="cli")
    prefix = {
        "request": "",
        "operation": "operations[0].",
        "element": "operations[0].element.",
        "role": "operations[0].element.roles[0].",
    }[level]
    assert error.value.issues == (
        Issue(
            prefix + field,
            "unknown_field",
            "ChunkHound fills this field itself; callers cannot supply it",
        ),
    )
    assert db.load_domain_input() == []
    assert domain_tables(db) == []


def test_write_confirm_requires_valid_ground_fact(
    db: DuckDBProvider,
    example: dict[str, Any],
) -> None:
    operations = example["operations"]
    # No examples, or a counterexample alone, cannot confirm a fact type.
    for invalid in [operations[:3], [*operations[:3], operations[4]]]:
        assert "confirmed_without_ground_fact" in {
            issue.code for issue in rejected(db, invalid)
        }
    operations[1]["element"]["status"] = "proposed"
    write(db, operations)
    result = write(db, [{"op": "confirm", "id": FACT_TYPE}])
    assert [(e.kind, e.status) for e in result.elements] == [
        ("fact_type", "confirmed"),
        ("role", "confirmed"),
        ("role", "confirmed"),
    ]
    issues = rejected(db, [{"op": "delete", "id": VALID_FACT}])
    assert issues == (
        Issue(
            "operations[0].id",
            "confirmed_without_ground_fact",
            f"{FACT_TYPE} would be confirmed without a valid ground fact; "
            "add a ground_fact put for it in the same request",
        ),
    )
    # End-state validation permits deleting the example while unconfirming its type.
    write(
        db, [{"op": "delete", "id": VALID_FACT}, {"op": "unconfirm", "id": FACT_TYPE}]
    )
    assert not load_human_input(db).model.fact_types[0].status == "confirmed"
    assert "confirmed_without_ground_fact" in {
        issue.code for issue in rejected(db, [{"op": "confirm", "id": FACT_TYPE}])
    }


def test_write_dry_run_writes_nothing(
    db: DuckDBProvider, example: dict[str, Any]
) -> None:
    result = apply_write(
        WriteRequest.model_validate(example),
        provider=db,
        author=AUTHOR,
        entry_point="mcp",
        dry_run=True,
    )
    assert result.dry_run
    assert result.records == ()
    assert [e.model_dump() for e in result.elements] == [
        {"id": "concept:backend/skill", "kind": "concept", "status": "proposed"},
        {"id": FACT_TYPE, "kind": "fact_type", "status": "confirmed"},
        {"id": "role:backend/user-skill/user", "kind": "role", "status": "confirmed"},
        {"id": "role:backend/user-skill/skill", "kind": "role", "status": "confirmed"},
        {"id": RULE, "kind": "validation_rule", "status": "proposed"},
        {"id": VALID_FACT, "kind": "ground_fact", "status": "proposed"},
        {"id": COUNTEREXAMPLE, "kind": "ground_fact", "status": "proposed"},
    ]
    assert result.warnings == (
        Issue(
            "operations[1].element.roles[0].concept",
            "unresolved_reference",
            "concept:backend/user is not in the human input; it may be a found "
            "element. Section 6 checks it on the full model.",
        ),
    )
    assert load_human_input(db).model.concepts == ()
    assert db.load_domain_input() == []
    assert domain_tables(db) == []
    encoded = result.model_dump(mode="json")
    assert encoded["records"] == []
    assert encoded["warnings"][0]["code"] == "unresolved_reference"


def test_list_input_replays_puts_confirms_and_deletes(
    db: DuckDBProvider,
    example: dict[str, Any],
) -> None:
    result = write(db, example["operations"])
    assert result.records == (1, 2, 3, 4, 5)
    rows = db.load_domain_input()
    assert len({row["batch_id"] for row in rows}) == 1
    assert all(row["batch_id"] == result.batch_id for row in rows)
    assert all(row["payload_version"] == 1 for row in rows)
    assert rows[1]["element_id"] == FACT_TYPE
    assert json.loads(rows[1]["payload"])["kind"] == "fact_type"
    view = load_human_input(db)
    assert view.judgements == ()
    assert {r.status for r in view.model.roles} == {"confirmed"}
    assert [s.record for s in view.model.roles[0].human_sources] == [2]
    assert view.model.validation_rules[0].roles == (
        "role:backend/user-skill/user",
        "role:backend/user-skill/skill",
    )
    assert all(not e.is_realized for e in (*view.model.concepts, *view.model.roles))
    role_id = "role:backend/user-skill/user"
    write(
        db,
        [
            {"op": "unconfirm", "id": role_id},
            {"op": "confirm", "id": "concept:backend/found"},
            {"op": "unconfirm", "id": FACT_TYPE},
        ],
    )
    view = load_human_input(db)
    user = next(r for r in view.model.roles if r.id == role_id)
    assert [s.record for s in user.human_sources] == [2, 6, 8]
    assert user.status == "proposed"
    assert view.judgements[0].id == "concept:backend/found"
    assert view.judgements[0].confirmed
    assert view.judgements[0].human_sources[0].record == 7
    write(db, [{"op": "confirm", "id": FACT_TYPE}, {"op": "unconfirm", "id": role_id}])
    view = load_human_input(db)
    assert [(r.name, r.status) for r in view.model.roles] == [
        ("skill", "confirmed"),
        ("user", "proposed"),
    ]
    write(
        db,
        [put(kind="concept", repository="backend", term="skill", definition="Revised")],
    )
    view = load_human_input(db)
    assert view.model.concepts[0].definition == "Revised"
    assert [s.record for s in view.model.concepts[0].human_sources] == [1, 11]
    assert view.model.concepts[0].synonyms == ()
    # Remove referrers and then their targets in any order in a single request.
    write(
        db,
        [
            {"op": "delete", "id": FACT_TYPE},
            {"op": "delete", "id": VALID_FACT},
            {"op": "delete", "id": COUNTEREXAMPLE},
            {"op": "delete", "id": RULE},
            {"op": "delete", "id": "concept:backend/skill"},
        ],
    )
    view = load_human_input(db)
    assert (
        not view.model.fact_types and not view.model.roles and not view.model.concepts
    )
    write(db, [put(kind="concept", repository="backend", term="skill")])
    assert [s.record for s in load_human_input(db).model.concepts[0].human_sources] == [
        17
    ]
    # All serialized collections are sorted and human sources are usable contract data.
    assert load_human_input(db).model_dump(mode="json")["judgements"][0]["confirmed"]


def test_write_checks_references_on_end_state(db: DuckDBProvider) -> None:
    result = write(
        db,
        [
            put(
                kind="fact_type",
                name="team",
                templates=["<team>"],
                roles=[{"name": "team", "concept": "concept:root/team"}],
            ),
            put(kind="concept", term="team"),
        ],
    )
    assert result.warnings == ()
    assert rejected(db, [{"op": "delete", "id": "concept:root/team"}]) == (
        Issue(
            "operations[0].id",
            "still_referenced",
            "concept:root/team is still referenced by "
            "fact_type:root/team, role:root/team/team",
        ),
    )
    write(
        db,
        [
            {"op": "delete", "id": "concept:root/team"},
            {"op": "delete", "id": "fact_type:root/team"},
        ],
    )
    assert not load_human_input(db).model.roles


@pytest.mark.parametrize(
    "operation,code",
    [
        ({"op": "unconfirm", "id": "concept:root/unknown"}, "unknown_element"),
        ({"op": "delete", "id": "concept:root/unknown"}, "unknown_element"),
        ({"op": "confirm", "id": "not-an-id"}, "invalid_reference"),
    ],
)
def test_write_rejects_unknown_targets(
    db: DuckDBProvider, operation: dict, code: str
) -> None:
    assert {(i.path, i.code) for i in rejected(db, [operation])} == {
        ("operations[0].id", code),
    }


def test_judgements_and_no_change_warnings(db: DuckDBProvider) -> None:
    target = "concept:root/found"
    write(db, [{"op": "confirm", "id": target}])
    assert rejected(db, [{"op": "delete", "id": target}])[0].code == "unknown_element"
    result = write(
        db,
        [
            {"op": "confirm", "id": target},
            {"op": "unconfirm", "id": target},
            {"op": "unconfirm", "id": target},
        ],
    )
    assert [(w.path, w.code) for w in result.warnings] == [
        ("operations[0].id", "no_change"),
        ("operations[2].id", "no_change"),
    ]
    view = load_human_input(db)
    assert not view.model.concepts
    assert not view.judgements[0].confirmed
    assert [s.op for s in view.judgements[0].human_sources] == [
        "confirm",
        "confirm",
        "unconfirm",
        "unconfirm",
    ]


@pytest.mark.parametrize(
    "body,code,suffix",
    [
        (
            {"kind": "concept", "status": "extracted", "term": "team"},
            "invalid_value",
            "status",
        ),
        (
            {"kind": "concept", "id": "concept:root/team", "term": "team"},
            "unknown_field",
            "id",
        ),
        ({"kind": "concept"}, "missing_field", "term"),
        ({"kind": "role", "name": "team"}, "invalid_value", ""),
        (
            {
                "kind": "validation_rule",
                "fact_type": "fact_type:root/team",
                "rule_kind": "mandatory",
            },
            "derived_rule_kind",
            "rule_kind",
        ),
        (
            {
                "kind": "ground_fact",
                "fact_type": "fact_type:root/team",
                "values": {"str": []},
            },
            "invalid_value",
            "values.str",
        ),
    ],
)
def test_write_shape_issues_have_json_paths(
    db: DuckDBProvider,
    body: dict,
    code: str,
    suffix: str,
) -> None:
    path = "operations[0].element" + ("." + suffix if suffix else "")
    assert [
        (i.path, i.code) for i in rejected(db, [{"op": "put", "element": body}])
    ] == [(path, code)]


@pytest.mark.parametrize(
    "count,code", [(0, "invalid_value"), (501, "too_many_operations")]
)
def test_write_request_operation_limits(
    db: DuckDBProvider, count: int, code: str
) -> None:
    issues = rejected(db, [{"op": "confirm", "id": "concept:root/found"}] * count)
    assert [(i.path, i.code) for i in issues] == [("operations", code)]


def test_duplicate_put_ids_are_rejected(db: DuckDBProvider) -> None:
    issues = rejected(
        db, [put(kind="concept", term="café"), put(kind="concept", term="cafe")]
    )
    assert [(i.path, i.code) for i in issues] == [
        ("operations[1].element", "duplicate_id")
    ]


@pytest.mark.parametrize("field", ["roles", "superset_roles", "values"])
def test_write_rejects_unknown_role_names_on_end_state(
    db: DuckDBProvider, field: str
) -> None:
    body = dict(
        kind="validation_rule",
        fact_type="fact_type:root/team",
        rule_kind="subset",
        roles=["team"],
        superset_roles=["team"],
        superset_fact_type="fact_type:root/team",
    )
    if field == "values":
        body = dict(
            kind="ground_fact", fact_type="fact_type:root/team", values={"unknown": "x"}
        )
    else:
        body[field] = ["unknown"]
    issues = rejected(
        db,
        [
            put(**body),
            put(
                kind="fact_type",
                name="team",
                templates=["<team>"],
                roles=[{"name": "team"}],
            ),
        ],
    )
    suffix = "values.unknown" if field == "values" else field + "[0]"
    assert [(i.path, i.code) for i in issues] == [
        ("operations[0].element." + suffix, "unknown_role"),
    ]


@pytest.mark.parametrize(
    "rule_kind,roles",
    [("uniqueness", []), ("value", ["a", "b"]), ("subset", []), ("other", [])],
)
def test_write_uses_loader_rule_shape_contract(
    db: DuckDBProvider, rule_kind: str, roles: list
) -> None:
    issues = rejected(
        db,
        [
            put(
                kind="validation_rule",
                fact_type="fact_type:root/team",
                rule_kind=rule_kind,
                roles=roles,
            )
        ],
    )
    assert [(i.path, i.code) for i in issues] == [
        ("operations[0].element", "rule_shape")
    ]


def test_full_human_model_uses_contract_types_and_sources(db: DuckDBProvider) -> None:
    write(
        db,
        [
            put(kind="concept", term="team"),
            put(
                kind="fact_type",
                name="team",
                templates=["<team>"],
                roles=[
                    {"name": "team", "concept": "concept:root/team", "mandatory": True}
                ],
            ),
            put(
                kind="ground_fact", fact_type="fact_type:root/team", values={"team": 1}
            ),
            put(
                kind="validation_rule",
                fact_type="fact_type:root/team",
                rule_kind="value",
                roles=["team"],
                allowed_values=["1"],
            ),
            put(
                kind="derivation_rule",
                name="derive team",
                statement="Derive a team.",
                derives=["fact_type:root/team"],
                uses=["concept:root/team"],
            ),
            put(
                kind="exchange_rule",
                name="add team",
                statement="Add a team.",
                operations=["add"],
                fact_types=["fact_type:root/team"],
            ),
            put(
                kind="event_rule",
                name="team added",
                statement="A team is added.",
                event="A request arrives.",
                starts=["exchange_rule:root/add-team"],
            ),
            {"op": "confirm", "id": "fact_type:root/team"},
        ],
    )
    model = load_human_input(db).model
    assert parse_model(model.model_dump(mode="json")) == model
    assert model.ground_facts[0].id == ground_fact_id(
        "fact_type:root/team", {"team": 1}
    )
    assert all(s.recorded_at.endswith("Z") for s in model.roles[0].human_sources)
    assert [s.record for s in model.roles[0].human_sources] == [2, 8]


def test_replacing_fact_type_updates_inline_roles_and_preserves_sources(
    db: DuckDBProvider,
) -> None:
    write(
        db,
        [
            put(
                kind="fact_type",
                name="team",
                templates=["<old>"],
                roles=[{"name": "old"}],
            )
        ],
    )
    write(
        db,
        [
            put(
                kind="fact_type",
                name="team",
                templates=["<new>"],
                roles=[{"name": "new"}],
            )
        ],
    )
    view = load_human_input(db)
    assert [r.name for r in view.model.roles] == ["new"]
    assert [s.record for s in view.model.roles[0].human_sources] == [1, 2]
    write(db, [{"op": "delete", "id": "fact_type:root/team"}])
    write(
        db,
        [
            put(
                kind="fact_type",
                name="team",
                templates=["<old>"],
                roles=[{"name": "old"}],
            )
        ],
    )
    assert [s.record for s in load_human_input(db).model.roles[0].human_sources] == [4]


def test_write_rejects_superset_names_without_a_fact_type(db: DuckDBProvider) -> None:
    issues = rejected(
        db,
        [
            put(
                kind="validation_rule",
                fact_type="fact_type:root/team",
                rule_kind="uniqueness",
                roles=["team"],
                superset_roles=["team"],
            )
        ],
    )
    assert [(i.path, i.code) for i in issues] == [
        ("operations[0].element", "rule_shape"),
    ]


def test_confirmation_cannot_hide_a_deleted_referenced_put(db: DuckDBProvider) -> None:
    write(
        db,
        [
            put(kind="concept", term="team"),
            put(
                kind="fact_type",
                name="team",
                templates=["<team>"],
                roles=[{"name": "team", "concept": "concept:root/team"}],
            ),
        ],
    )
    issues = rejected(
        db,
        [
            {"op": "delete", "id": "concept:root/team"},
            {"op": "confirm", "id": "concept:root/team"},
        ],
    )
    assert [(i.path, i.code) for i in issues] == [
        ("operations[0].id", "still_referenced"),
    ]
    # Parent operations after an inline-role delete must reject, not crash replay.
    issues = rejected(
        db,
        [
            {"op": "delete", "id": "role:root/team/team"},
            {"op": "unconfirm", "id": "fact_type:root/team"},
        ],
    )
    assert [(i.path, i.code) for i in issues] == [
        ("operations[0].id", "still_referenced"),
    ]


def test_changes_to_existing_references_report_a_submitted_path(
    db: DuckDBProvider,
) -> None:
    write(
        db,
        [
            put(
                kind="fact_type",
                name="team",
                templates=["<team>"],
                roles=[{"name": "team"}],
            ),
            put(
                kind="ground_fact", fact_type="fact_type:root/team", values={"team": 1}
            ),
        ],
    )
    issues = rejected(
        db,
        [
            put(
                kind="fact_type",
                name="team",
                templates=["<renamed>"],
                roles=[{"name": "renamed"}],
            )
        ],
    )
    assert [(i.path, i.code) for i in issues] == [
        ("operations[0].element", "unknown_role"),
    ]


def test_write_defaults_follow_the_request_contract(db: DuckDBProvider) -> None:
    issues = rejected(
        db,
        [
            put(kind="exchange_rule", name="omitted", statement="Exchange a fact."),
            put(
                kind="exchange_rule",
                name="empty",
                statement="Exchange a fact.",
                operations=[],
            ),
        ],
    )
    assert [(issue.path, issue.code) for issue in issues] == [
        ("operations[0].element.operations", "missing_field"),
        ("operations[1].element.operations", "invalid_value"),
    ]
    assert domain_tables(db) == []
    write(
        db,
        [
            put(
                kind="exchange_rule",
                name="exchange",
                statement="Exchange a fact.",
                operations=["add"],
            ),
            put(kind="event_rule", name="event", statement="Start an exchange."),
        ],
    )
    model = load_human_input(db).model
    exchange = model.exchange_rules[0]
    assert exchange.operations == ("add",)
    assert ExchangeRule.model_validate(exchange.model_dump()) == exchange
    assert model.event_rules[0].event == ""
    assert exchange.repository == "root"
