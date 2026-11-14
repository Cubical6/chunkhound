"""Public identity and realization contracts for CogNIAM elements."""

import pytest
from pydantic import ValidationError

from chunkhound.domain_model.identity import (
    EmptyKeyError,
    InvalidReferenceError,
    concept_id,
    datatype_rule_id,
    derivation_rule_id,
    event_rule_id,
    exchange_rule_id,
    fact_type_id,
    ground_fact_hash,
    ground_fact_id,
    key_segment,
    mandatory_rule_id,
    parse_id,
    repository_key,
    role_id,
    validation_rule_id,
)
from chunkhound.domain_model.issues import Issue, ModelLoadError
from chunkhound.domain_model.model import (
    Citation,
    Concept,
    DerivationRule,
    DomainModel,
    EventRule,
    ExchangeRule,
    FactType,
    GroundFact,
    Role,
    ValidationRule,
)


def test_element_ids_are_stable_and_ascii() -> None:
    fact_type = fact_type_id("backend", "Team membership")
    values = {"member": "42", "team": "7"}
    examples = [
        (concept_id("backend", "User"), "concept:backend/user"),
        (fact_type, "fact_type:backend/team-membership"),
        (role_id(fact_type, "Member"), "role:backend/team-membership/member"),
        (
            validation_rule_id(fact_type, "uniqueness", ("team", "member")),
            "validation_rule:backend/team-membership/uniqueness/member+team",
        ),
        (
            validation_rule_id(fact_type, "subset", ("team", "member")),
            "validation_rule:backend/team-membership/subset/member+team",
        ),
        (
            validation_rule_id(fact_type, "value", ("member",)),
            "validation_rule:backend/team-membership/value/member",
        ),
        (
            validation_rule_id(fact_type, "other", name="One lead per team"),
            "validation_rule:backend/team-membership/other/one-lead-per-team",
        ),
        (
            mandatory_rule_id(fact_type, "member"),
            "validation_rule:backend/team-membership/mandatory/member",
        ),
        (
            datatype_rule_id(fact_type, "member"),
            "validation_rule:backend/team-membership/datatype/member",
        ),
        (
            derivation_rule_id("backend", "Team size"),
            "derivation_rule:backend/team-size",
        ),
        (
            exchange_rule_id("backend", "Add team member"),
            "exchange_rule:backend/add-team-member",
        ),
        (event_rule_id("backend", "Team joined"), "event_rule:backend/team-joined"),
        (
            ground_fact_id(fact_type, values),
            "ground_fact:backend/team-membership/d0480d33ce24",
        ),
        (concept_id(".", "categorieën"), "concept:root/categorieen"),
        (
            validation_rule_id(
                fact_type_id("backend", "Role assignment"),
                "uniqueness",
                ("user", "role"),
            ),
            "validation_rule:backend/role-assignment/uniqueness/role+user",
        ),
        (
            mandatory_rule_id(fact_type_id("backend", "Role assignment"), "user"),
            "validation_rule:backend/role-assignment/mandatory/user",
        ),
    ]
    for actual, expected in examples:
        assert actual == expected
        assert actual.isascii()
        kind, repository, segments = parse_id(actual)
        assert f"{kind}:{repository}/{'/'.join(segments)}" == actual
    assert ground_fact_hash(values) == "d0480d33ce24"
    assert repository_key("services/backend") == "services-backend"
    assert repository_key(".") == "root"
    for text in ("categorieën", "Équipe / Backend", "Already-a-key"):
        assert key_segment(key_segment(text)) == key_segment(text)
    for text in ("", "  ", "---", "😀"):
        with pytest.raises(EmptyKeyError):
            key_segment(text)


def test_ground_fact_identity_uses_values_and_counterexamples() -> None:
    values = {"member": "é", "team": 7}
    assert ground_fact_hash(values) == ground_fact_hash(dict(reversed(values.items())))
    assert ground_fact_hash(values, ("b", "a")) == ground_fact_hash(values, ("a", "b"))
    assert ground_fact_hash(values) != ground_fact_hash(values, ("a",))
    assert ground_fact_hash({"team": 7}) != ground_fact_hash({"team": "7"})


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        "concept:backend",
        "unknown:backend/user",
        "concept:Backend/user",
        "concept:backend/catégorie",
        "concept:backend/user/extra",
        "role:backend/member",
        "ground_fact:backend/team/not-a-hash",
        "validation_rule:backend/team/equality/member",
        "validation_rule:backend/team/uniqueness/team+member",
        "validation_rule:backend/team/value/member+team",
        "validation_rule:backend/team/mandatory/member+team",
    ],
)
def test_invalid_references_are_rejected(identifier: str) -> None:
    with pytest.raises(InvalidReferenceError) as error:
        parse_id(identifier)
    assert error.value.code == "invalid_reference"


@pytest.mark.parametrize(
    ("element_class", "fields"),
    [
        (Concept, dict(term="User", plural=None, definition=None, synonyms=())),
        (
            FactType,
            dict(
                name="Membership",
                templates=("<member>",),
                roles=(),
                identifies=None,
                bindings=(),
            ),
        ),
        (
            Role,
            dict(
                fact_type="fact_type:root/membership",
                name="member",
                concept=None,
                datatype=None,
                mandatory=None,
                bindings=(),
            ),
        ),
        (
            ValidationRule,
            dict(
                fact_type="fact_type:root/membership",
                rule_kind="uniqueness",
                roles=(),
                superset_fact_type=None,
                superset_roles=(),
                allowed_values=(),
                name=None,
                statement=None,
            ),
        ),
        (
            DerivationRule,
            dict(name="Count", statement="Count users", derives=(), uses=()),
        ),
        (
            ExchangeRule,
            dict(name="Add", statement="Add user", operations=("add",), fact_types=()),
        ),
        (
            EventRule,
            dict(name="Joined", statement="Add user", event="On joining", starts=()),
        ),
        (
            GroundFact,
            dict(
                fact_type="fact_type:root/membership",
                values={"member": "42"},
                violates=(),
            ),
        ),
    ],
)
def test_realization_follows_code_citations(element_class, fields) -> None:
    planned = element_class(
        id="example",
        repository="root",
        status="proposed",
        citations=(),
        human_sources=(),
        **fields,
    )
    assert not planned.is_realized
    citation = Citation(
        repository="root", path="models.py", start_line=1, end_line=2, commit="abcdef0"
    )
    realized = planned.model_copy(update={"citations": (citation,)})
    assert realized.is_realized
    assert "is_realized" not in realized.model_dump()
    with pytest.raises(ValidationError):
        planned.status = "confirmed"
    with pytest.raises(ValidationError):
        element_class.model_validate({**planned.model_dump(), "unexpected": True})


def test_domain_model_requires_schema_and_rejects_unknown_fields() -> None:
    data = dict(
        schema_version=1,
        concepts=(),
        fact_types=(),
        roles=(),
        validation_rules=(),
        derivation_rules=(),
        exchange_rules=(),
        event_rules=(),
        ground_facts=(),
    )
    model = DomainModel.model_validate(data)
    assert model.schema_version == 1
    with pytest.raises(ValidationError):
        DomainModel.model_validate({**data, "schema_version": 2})
    with pytest.raises(ValidationError):
        DomainModel.model_validate({**data, "level": 3})


def test_load_error_preserves_all_issues_and_limits_message() -> None:
    issues = tuple(
        Issue(f"roles[{i}]", "invalid_value", f"Issue {i}") for i in range(23)
    )
    error = ModelLoadError(issues)
    assert error.issues == issues
    assert "23 issues" in str(error)
    assert "roles[19]: invalid_value: Issue 19" in str(error)
    assert "roles[20]" not in str(error)
