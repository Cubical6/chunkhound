"""User-facing JSON loading, diagnostics and serialization contracts."""

import json
from pathlib import Path
from typing import cast

import pytest

from chunkhound.domain_model.identity import ground_fact_id
from chunkhound.domain_model.issues import ModelLoadError
from chunkhound.domain_model.loader import dump_model, load_model, parse_model

FIXTURE = Path(__file__).parent / "fixtures" / "contract_example.json"


@pytest.fixture
def data() -> dict:
    return cast(dict, json.loads(FIXTURE.read_text(encoding="utf-8")))


def issue_pairs(data: object) -> set[tuple[str, str]]:
    with pytest.raises(ModelLoadError) as error:
        parse_model(data)
    return {(issue.path, issue.code) for issue in error.value.issues}


def test_contract_round_trip_is_byte_stable() -> None:
    assert dump_model(load_model(FIXTURE)).encode("utf-8") == FIXTURE.read_bytes()


def test_loader_reports_all_issues_with_json_paths(data: dict) -> None:
    del data["concepts"][0]["term"]
    data["fact_types"][0]["templates"].append("Team <team> has user <member>.")
    data["fact_types"][0]["templates"][0] = None
    data["roles"][0]["surprise"] = True
    assert issue_pairs(data) == {
        ("concepts[0].term", "missing_field"),
        ("fact_types[0].templates[0]", "invalid_value"),
        ("roles[0].surprise", "unknown_field"),
    }


@pytest.mark.parametrize("version", [None, 0, 2, "1", True, 1.0])
def test_loader_rejects_unsupported_schema_version(data: dict, version: object) -> None:
    data["schema_version"] = version
    data["unexpected"] = True
    assert issue_pairs(data) == {("schema_version", "unsupported_schema_version")}


def test_loader_requires_schema_version(data: dict) -> None:
    del data["schema_version"]
    assert issue_pairs(data) == {("schema_version", "unsupported_schema_version")}
    assert issue_pairs([]) == {("schema_version", "unsupported_schema_version")}


def test_loader_rejects_element_without_source(data: dict) -> None:
    data["concepts"][0]["citations"] = []
    assert issue_pairs(data) == {("concepts[0]", "missing_source")}


def test_loader_rejects_confirmed_without_human_source(data: dict) -> None:
    source = data["fact_types"][0]["human_sources"][0]
    source.update(op="put", put_status="proposed")
    assert issue_pairs(data) == {
        ("fact_types[0].status", "confirmed_without_human_source")
    }
    source["put_status"] = "confirmed"
    parse_model(data)


@pytest.mark.parametrize("counterexample", [False, True])
def test_loader_rejects_confirmed_fact_type_without_ground_fact(
    data: dict, counterexample: bool
) -> None:
    if counterexample:
        fact = data["ground_facts"][0]
        fact["violates"] = [data["validation_rules"][0]["id"]]
        fact["id"] = ground_fact_id(fact["fact_type"], fact["values"], fact["violates"])
    else:
        data["ground_facts"] = []
    assert issue_pairs(data) == {
        ("fact_types[0].status", "confirmed_without_ground_fact")
    }


@pytest.mark.parametrize(
    "template",
    [
        "User <member> belongs to <unknown>.",
        "<member> <team> <member>",
    ],
)
def test_loader_rejects_template_role_mismatch(data: dict, template: str) -> None:
    data["fact_types"][0]["templates"].append(template)
    assert issue_pairs(data) == {
        ("fact_types[0].templates[1]", "template_role_mismatch")
    }


def test_templates_may_cover_a_subset_of_roles(data: dict) -> None:
    fact = data["fact_types"][0]
    role = data["roles"][0].copy()
    role.update(id="role:backend/team-membership/extra", name="extra")
    data["roles"].append(role)
    fact["roles"].append(role["id"])
    fact["templates"] = ["<member>", "<team>", "<extra>"]
    parse_model(data)


def test_role_missing_from_every_template_is_rejected(data: dict) -> None:
    data["fact_types"][0]["templates"] = ["<member>"]
    with pytest.raises(ModelLoadError) as error:
        parse_model(data)
    assert any(
        issue.path == "fact_types[0]"
        and issue.code == "template_role_mismatch"
        and "team" in issue.message
        for issue in error.value.issues
    )


@pytest.mark.parametrize(
    "field,value,path",
    [
        ("term", "organisation", "concepts[0].id"),
        ("repository", "other", "concepts[0].repository"),
    ],
)
def test_loader_rejects_id_that_does_not_match_key(
    data: dict, field: str, value: str, path: str
) -> None:
    data["concepts"][0][field] = value
    assert (path, "id_mismatch") in issue_pairs(data)


def test_loader_collects_independent_model_errors(data: dict) -> None:
    data["concepts"].append(dict(data["concepts"][0]))
    data["concepts"][1]["term"] = "!!!"
    data["roles"][0]["concept"] = "concept:backend/absent"
    data["roles"][1]["concept"] = "fact_type:backend/team-membership"
    data["exchange_rules"][0]["fact_types"] = ["not-an-id"]
    data["roles"][0]["citations"] = []
    data["concepts"][0]["citations"][0]["start_line"] = 0
    pairs = issue_pairs(data)
    assert {
        ("concepts[2].id", "duplicate_id"),
        ("concepts[1].term", "empty_key"),
        ("roles[0].concept", "dangling_reference"),
        ("roles[1].concept", "invalid_reference"),
        ("exchange_rules[0].fact_types[0]", "invalid_reference"),
        ("roles[0].bindings[0].citation", "binding_citation_missing"),
        ("concepts[0].citations[0]", "invalid_line_range"),
    } <= pairs


def test_loader_rejects_inconsistent_role_membership(data: dict) -> None:
    data["fact_types"][0]["roles"].pop()
    assert ("roles[1].fact_type", "role_mismatch") in issue_pairs(data)


def test_loader_rejects_unknown_ground_fact_roles(data: dict) -> None:
    fact = data["ground_facts"][0]
    fact["values"]["unknown"] = "x"
    fact["id"] = ground_fact_id(fact["fact_type"], fact["values"])
    assert issue_pairs(data) == {("ground_facts[0].values.unknown", "unknown_role")}


@pytest.mark.parametrize(
    "rule_kind,roles,superset",
    [
        ("uniqueness", [], None),
        ("value", ["member", "team"], None),
        ("subset", ["member"], None),
        ("subset", ["member"], "fact_type:backend/team-membership"),
        ("other", ["member"], None),
    ],
)
def test_loader_rejects_malformed_validation_rules(
    data: dict, rule_kind: str, roles: list[str], superset: str | None
) -> None:
    rule = data["validation_rules"][0]
    rule.update(
        rule_kind=rule_kind,
        roles=["role:backend/team-membership/" + role for role in roles],
        superset_fact_type=superset,
        name=None,
    )
    assert ("validation_rules[0]", "rule_shape") in issue_pairs(data)


@pytest.mark.parametrize("kind", ["mandatory", "datatype"])
def test_loader_rejects_stored_derived_rules(data: dict, kind: str) -> None:
    data["validation_rules"][0]["rule_kind"] = kind
    assert issue_pairs(data) == {("validation_rules[0].rule_kind", "derived_rule_kind")}


def test_loader_accepts_derived_violation_references(data: dict) -> None:
    fact = data["ground_facts"][0]
    fact["violates"] = [
        "validation_rule:backend/team-membership/mandatory/member",
        "validation_rule:backend/team-membership/datatype/team",
    ]
    fact["id"] = ground_fact_id(fact["fact_type"], fact["values"], fact["violates"])
    data["fact_types"][0]["status"] = "proposed"
    parse_model(data)
    fact["violates"] = ["concept:backend/team"]
    assert ("ground_facts[0].violates[0]", "invalid_reference") in issue_pairs(data)
    fact["violates"] = ["validation_rule:backend/team-membership/mandatory/absent"]
    assert ("ground_facts[0].violates[0]", "dangling_reference") in issue_pairs(data)


@pytest.mark.parametrize("content", [b"not json", b"\xff", b'{"schema_version":'])
def test_load_model_reports_invalid_json(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "model.json"
    path.write_bytes(content)
    with pytest.raises(ModelLoadError) as error:
        load_model(path)
    assert error.value.issues[0].code == "invalid_json"


def test_load_model_reports_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(ModelLoadError) as error:
        load_model(tmp_path / "absent.json")
    assert error.value.issues[0].code == "invalid_json"


def test_dump_is_deterministic_without_reordering_positional_fields(data: dict) -> None:
    expected = dump_model(parse_model(data))
    for key, value in data.items():
        if key != "schema_version":
            value.reverse()
    fact = data["ground_facts"][0]
    fact["values"] = dict(reversed(list(fact["values"].items())))
    assert dump_model(parse_model(data)) == expected
    data["fact_types"][0]["templates"].append("Team <team> has user <member>.")
    data["fact_types"][0]["roles"].reverse()
    data["concepts"][0]["definition"] = "categorieën"
    dumped = dump_model(parse_model(data))
    loaded = json.loads(dumped)
    assert loaded["fact_types"][0]["roles"] == data["fact_types"][0]["roles"]
    assert loaded["fact_types"][0]["templates"] == data["fact_types"][0]["templates"]
    assert "categorieën" in dumped
    assert dumped.endswith("\n")


def test_loader_rejects_subset_without_roles(data: dict) -> None:
    data["validation_rules"][0].update(
        rule_kind="subset",
        roles=[],
        superset_roles=[],
        superset_fact_type="fact_type:backend/team-membership",
    )
    assert issue_pairs(data) == {("validation_rules[0]", "rule_shape")}


def test_loader_reports_union_value_error_once_at_json_key(data: dict) -> None:
    data["ground_facts"][0]["values"] = {"member": [1, 2], "str": [3, 4]}
    with pytest.raises(ModelLoadError) as error:
        parse_model(data)
    assert [(issue.path, issue.code) for issue in error.value.issues] == [
        ("ground_facts[0].values.member", "invalid_value"),
        ("ground_facts[0].values.str", "invalid_value"),
    ]


def test_loader_checks_rule_reference_kinds_and_targets(data: dict) -> None:
    source_fields = {
        key: data["exchange_rules"][0][key]
        for key in ("repository", "status", "citations", "human_sources")
    }
    data["derivation_rules"] = [
        {
            **source_fields,
            "id": "derivation_rule:backend/member-count",
            "name": "member count",
            "statement": "Derive the member count.",
            "derives": ["fact_type:backend/team-membership"],
            "uses": ["role:backend/team-membership/member"],
        }
    ]
    data["event_rules"] = [
        {
            **source_fields,
            "id": "event_rule:backend/team-created",
            "name": "team created",
            "statement": "Add the first member when a team is created.",
            "event": "A team is created.",
            "starts": [
                "exchange_rule:backend/add-team-member",
                "derivation_rule:backend/member-count",
            ],
        }
    ]
    parse_model(data)
    assert dump_model(
        parse_model(json.loads(dump_model(parse_model(data))))
    ) == dump_model(parse_model(data))
    data["derivation_rules"][0]["derives"] = ["concept:backend/team"]
    data["derivation_rules"][0]["uses"] = ["role:backend/team-membership/absent"]
    data["event_rules"][0]["starts"] = ["fact_type:backend/team-membership"]
    data["validation_rules"][0].update(
        rule_kind="subset",
        superset_fact_type="fact_type:backend/absent",
        superset_roles=["role:backend/absent/member"],
    )
    assert {
        ("derivation_rules[0].derives[0]", "invalid_reference"),
        ("derivation_rules[0].uses[0]", "dangling_reference"),
        ("event_rules[0].starts[0]", "invalid_reference"),
        ("validation_rules[0].superset_fact_type", "dangling_reference"),
        ("validation_rules[0].superset_roles[0]", "dangling_reference"),
    } <= issue_pairs(data)
