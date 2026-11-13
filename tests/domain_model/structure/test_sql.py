"""User-facing contracts for SQL CREATE extraction, without Git or a database."""

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure


@pytest.fixture
def sql(extract_fixture: Callable[[str], StructureExtraction]) -> StructureExtraction:
    return extract_fixture("sql_create")


def test_named_foreign_key_in_dump_becomes_subset_rule(
    sql: StructureExtraction,
) -> None:
    rule = next(
        r
        for r in sql.model.validation_rules
        if r.id == "validation_rule:root/team-user/subset/user-id"
    )
    assert rule.roles == ("role:root/team-user/user-id",)
    assert rule.superset_fact_type == "fact_type:root/users"
    assert rule.superset_roles == ("role:root/users/id",)
    assert rule.citations[0].start_line == rule.citations[0].end_line == 14
    role = next(r for r in sql.model.roles if r.id == "role:root/team-user/user-id")
    assert role.concept == "concept:root/users"
    assert role.bindings[0].target == "team_user.user_id"
    assert role.mandatory is True


def test_table_without_key_gets_no_concept(sql: StructureExtraction) -> None:
    fact = next(f for f in sql.model.fact_types if f.name == "audit_line")
    assert fact.identifies is None
    assert fact.templates == ("audit_line has note <note>",)
    assert not any(c.term == "audit_line" for c in sql.model.concepts)


def test_join_table_gets_no_concept(sql: StructureExtraction) -> None:
    fact = next(f for f in sql.model.fact_types if f.name == "team_link")
    assert fact.identifies is None
    assert fact.templates == ("team_link(<team_id>, <user_id>)",)
    assert not any(c.term == "team_link" for c in sql.model.concepts)


def test_each_non_key_column_gets_its_own_template(sql: StructureExtraction) -> None:
    fact = next(f for f in sql.model.fact_types if f.name == "team_user")
    assert fact.templates == (
        "team_user(<id>)",
        "team_user(<id>) has team_id <team_id>",
        "team_user(<id>) has user_id <user_id>",
        "team_user(<id>) has role <role>",
    )
    users = next(f for f in sql.model.fact_types if f.name == "users")
    assert users.roles == ("role:root/users/id", "role:root/users/email")
    assert users.templates[0] == "users(<id>)"
    assert users.identifies == "concept:root/users"
    assert not any(r.name == "ignored" for r in sql.model.roles)


def test_enum_and_check_in_become_value_rules(sql: StructureExtraction) -> None:
    rules = {r.id: r for r in sql.model.validation_rules}
    assert rules["validation_rule:root/team-user/value/role"].allowed_values == (
        "member",
        "lead",
    )
    mood = rules["validation_rule:root/invoice/value/mood"]
    assert mood.allowed_values == ("calm", "busy, now", "can't")
    assert mood.citations[0].start_line == 2
    assert rules["validation_rule:root/invoice/value/size"].allowed_values == (
        "small",
        "large",
    )
    assert rules["validation_rule:root/inline-checks/value/state"].allowed_values == (
        "new",
        "done",
    )


def test_other_check_becomes_named_other_rule(sql: StructureExtraction) -> None:
    rules = {r.id: r for r in sql.model.validation_rules}
    rule = rules["validation_rule:root/invoice/other/positive-amount"]
    assert rule.name == "positive_amount"
    assert "CHECK (amount > 0)" in rule.statement
    assert rule.roles == ("role:root/invoice/amount",)
    assert (
        rules["validation_rule:root/invoice/other/check-amount"].statement
        == "CHECK (amount < 100)"
    )
    assert "validation_rule:root/inline-checks/other/check-score" in rules


def test_reference_to_unknown_table_is_external_reference(
    sql: StructureExtraction,
) -> None:
    assert not any(
        r.fact_type == "fact_type:root/external-note" and r.rule_kind == "subset"
        for r in sql.model.validation_rules
    )
    finding = next(f for f in sql.findings if f.kind == "external_reference")
    assert finding.subject == "fact_type:root/external-note"
    assert finding.reason == "table_not_found"
    assert finding.detail == "(remote_id) -> remote_users(id)"


def test_key_collision_is_reported(sql: StructureExtraction) -> None:
    collisions = [f for f in sql.findings if f.reason == "key_collision"]
    assert {f.detail for f in collisions} == {"collision-a", "column_collision.user-id"}
    assert all(f.kind == "unresolved" for f in collisions)
    assert (
        next(
            f for f in sql.model.fact_types if f.id == "fact_type:root/collision-a"
        ).name
        == "collision_a"
    )
    assert not any(r.name == "user-id" for r in sql.model.roles)


def test_unique_index_and_unique_key_become_uniqueness_rules(
    sql: StructureExtraction,
) -> None:
    ids = {r.id for r in sql.model.validation_rules if r.rule_kind == "uniqueness"}
    assert {
        "validation_rule:root/users/uniqueness/email",
        "validation_rule:root/invoice/uniqueness/note",
        "validation_rule:root/team-user/uniqueness/team-id+user-id",
        "validation_rule:root/inline-checks/uniqueness/code",
    } <= ids
    assert not any(
        r.rule_kind == "uniqueness" and r.roles == ("role:root/invoice/amount",)
        for r in sql.model.validation_rules
    )
    assert {
        r.name for r in sql.model.roles if r.fact_type == "fact_type:root/search-data"
    } == {"body", "location"}
    fact = next(f for f in sql.model.fact_types if f.name == "unique_only")
    assert fact.identifies is None
    assert fact.templates == (
        "unique_only(<code>)",
        "unique_only(<code>) has note <note>",
    )


def test_second_foreign_key_is_a_divergent_claim(sql: StructureExtraction) -> None:
    claim = next(
        c
        for c in sql.divergent_claims
        if c.subject == "validation_rule:root/ambiguous/subset/owner-id"
    )
    assert claim.subject == "validation_rule:root/ambiguous/subset/owner-id"
    assert claim.value == ("fact_type:root/teams", "role:root/teams/id")
    assert claim.source == "sql"
    rule = next(r for r in sql.model.validation_rules if r.id == claim.subject)
    assert rule.superset_fact_type == "fact_type:root/users"


def test_datatypes_nullability_and_literal_defaults_are_preserved(
    sql: StructureExtraction,
) -> None:
    roles = {r.id: r for r in sql.model.roles}
    assert roles["role:root/users/id"].datatype == "bigint unsigned"
    assert roles["role:root/users/email"].datatype == "varchar(255)"
    assert roles["role:root/users/email"].mandatory is True
    assert roles["role:root/unique-only/code"].datatype == "varchar(8)"
    assert roles["role:root/invoice/amount"].datatype == "numeric(12,4)"
    assert roles["role:root/invoice/id"].mandatory is True
    assert roles["role:root/team-user/role"].mandatory is False
    assert roles["role:root/inline-checks/description"].mandatory is False
    assert roles["role:root/literal-values/count"].mandatory is True
    assert roles["role:root/literal-values/owner-id"].mandatory is True
    assert roles["role:root/literal-values/label"].datatype == (
        "enum('busy, now','With (spaces)','can''t')"
    )
    assert all(
        f.reason == "key_collision" or f.kind in {"external_reference", "uncertain"}
        for f in sql.findings
    )
    assert {
        (f.subject, f.reason, f.detail) for f in sql.findings if f.kind == "uncertain"
    } == {
        (None, "unparsed_statement", "later_table"),
        ("fact_type:root/inline-checks", "unparsed_statement", "audit_line"),
    }


def test_index_before_table_does_not_prevent_table_creation(
    sql: StructureExtraction,
) -> None:
    fact = next(f for f in sql.model.fact_types if f.name == "later_table")
    assert fact.roles == ("role:root/later-table/x",)
    assert not any(r.fact_type == fact.id for r in sql.model.validation_rules)
    assert not any(f.reason == "table_created_twice" for f in sql.findings)
    findings = [f for f in sql.findings if f.detail == "later_table"]
    assert len(findings) == 1
    assert findings[0].kind == "uncertain"
    assert findings[0].subject is None
    assert findings[0].reason == "unparsed_statement"
    assert findings[0].citations[0].path == "a.sql"


def test_reference_without_columns_uses_only_the_target_primary_key(
    sql: StructureExtraction,
) -> None:
    rules = {r.id: r for r in sql.model.validation_rules}
    for table in ("invoice", "inline-checks"):
        rule = rules[f"validation_rule:root/{table}/subset/user-id"]
        assert rule.superset_fact_type == "fact_type:root/users"
        assert rule.superset_roles == ("role:root/users/id",)
    assert "validation_rule:root/inline-checks/subset/audit-note" not in rules
    assert any(
        f.kind == "uncertain"
        and f.subject == "fact_type:root/inline-checks"
        and f.reason == "unparsed_statement"
        and f.detail == "audit_line"
        for f in sql.findings
    )


def test_constraint_source_order_selects_keys_and_foreign_key_winner(
    sql: StructureExtraction,
) -> None:
    fact = next(f for f in sql.model.fact_types if f.name == "ordered_keys")
    assert fact.templates == (
        "ordered_keys(<second>)",
        "ordered_keys(<second>) has first <first>",
    )
    rule_id = "validation_rule:root/ordered-references/subset/owner-id"
    rule = next(r for r in sql.model.validation_rules if r.id == rule_id)
    assert rule.superset_fact_type == "fact_type:root/users"
    claim = next(c for c in sql.divergent_claims if c.subject == rule_id)
    assert claim.value == ("fact_type:root/teams", "role:root/teams/id")


def test_composite_foreign_key_preserves_role_pairs(sql: StructureExtraction) -> None:
    rule = next(
        r
        for r in sql.model.validation_rules
        if r.id == "validation_rule:root/pair-link/subset/left-id+right-id"
    )
    assert rule.roles == ("role:root/pair-link/left-id", "role:root/pair-link/right-id")
    assert rule.superset_roles == (
        "role:root/pair-target/first-id",
        "role:root/pair-target/second-id",
    )
    assert all(
        r.concept is None
        for r in sql.model.roles
        if r.fact_type == "fact_type:root/pair-link"
    )


def test_unnamed_multi_column_check_has_stable_source_hash(
    sql: StructureExtraction,
) -> None:
    statement = "CHECK (count > other_id)"
    name = "check-" + hashlib.sha256(statement.encode()).hexdigest()[:8]
    rule = next(
        r
        for r in sql.model.validation_rules
        if r.id == f"validation_rule:root/literal-values/other/{name}"
    )
    assert rule.name == name
    assert rule.statement == statement
    assert rule.roles == (
        "role:root/literal-values/count",
        "role:root/literal-values/other-id",
    )


def test_sql_references_and_citations_stay_in_the_declared_repository(
    sql: StructureExtraction,
    tmp_path: Path,
) -> None:
    project = tmp_path / "sql_create"
    backend = project / "backend"
    backend.mkdir()
    (project / "postgres.sql").rename(backend / "postgres.sql")
    result = build_structure(
        project,
        (
            sql.repositories[0],
            RepositoryRef(key="backend", path="backend", commit="1" * 40, dirty=False),
        ),
    )
    fact = next(f for f in result.model.fact_types if f.name == "invoice")
    assert fact.id == "fact_type:backend/invoice"
    assert fact.citations[0].repository == "backend"
    assert fact.citations[0].path == "backend/postgres.sql"
    assert fact.citations[0].commit == "1" * 40
    assert any(
        f.subject == fact.id and f.reason == "table_not_found" for f in result.findings
    )
    assert not any(
        r.fact_type == fact.id and r.rule_kind == "subset"
        for r in result.model.validation_rules
    )
