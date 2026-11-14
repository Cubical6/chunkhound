"""Eloquent enrichment obeys storage authority and literal model conventions."""

from collections.abc import Callable
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure


@pytest.mark.parametrize("cast", ["Priority::class", r"'App\Priority'"])
def test_integer_backed_enum_preserves_literal_values(
    tmp_path: Path, cast: str
) -> None:
    (tmp_path / "schema.sql").write_text(
        "CREATE TABLE entries (id INT PRIMARY KEY, priority INT);\n"
    )
    source = r"""<?php
namespace App;
use Illuminate\Database\Eloquent\Model;
enum Priority: int { case Low = -1; case Normal = 1; case High = 010; }
class Entry extends Model {
    protected $casts = ['priority' => Priority::class];
}
"""
    (tmp_path / "Entry.php").write_text(source.replace("Priority::class", cast))
    repo = RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False)
    result = build_structure(tmp_path, (repo,))
    value = next(r for r in result.model.validation_rules if r.rule_kind == "value")
    assert value.allowed_values == ("-1", "1", "8")
    assert value.citations[0].path == "Entry.php"
    assert not result.findings


def test_model_class_names_the_concept(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("eloquent")
    fact = next(f for f in result.model.fact_types if f.name == "team_user")
    concept = next(c for c in result.model.concepts if c.id == fact.identifies)
    assert concept.term == "team member"
    assert any(c.path.endswith("TeamMember.php") for c in concept.citations)
    assert [b.target for b in fact.bindings] == [
        "team_user",
        "App\\Models\\TeamMember",
        "App\\Models\\ZReducedMember",
    ]


def test_lower_source_agreeing_adds_a_citation(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("eloquent")
    rules = result.model.validation_rules
    subset = next(
        r for r in rules if r.rule_kind == "subset" and r.roles[0].endswith("/team-id")
    )
    value = next(
        r for r in rules if r.rule_kind == "value" and r.roles[0].endswith("/status")
    )
    assert len(subset.citations) == len(value.citations) == 2
    assert any(c.path.endswith("TeamMember.php") for c in subset.citations)
    assert not any(
        c.subject == value.id
        and c.source == "eloquent"
        and set(c.value) == {"active", "pending"}
        for c in result.divergent_claims
        if isinstance(c.value, tuple)
    )


def test_lower_source_adding_becomes_own_rule(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("eloquent")
    rule = next(
        r
        for r in result.model.validation_rules
        if r.rule_kind == "value" and r.roles[0].endswith("/visibility")
    )
    assert rule.allowed_values == ("public", "private")
    assert len(rule.citations) == 1
    assert rule.citations[0].path.endswith("TeamMember.php")


def test_lower_source_disagreeing_becomes_divergent_claim(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("eloquent")
    (claim,) = result.divergent_claims
    assert claim.property == "allowed_values"
    assert claim.value == ("active",)
    assert claim.source == "eloquent"
    assert claim.citation.path.endswith("ZReducedMember.php")
    rule = next(r for r in result.model.validation_rules if r.id == claim.subject)
    assert set(rule.allowed_values) == {"active", "pending"}


def test_model_without_table_gives_no_fact_type(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("eloquent")
    missing = [f for f in result.findings if f.detail == "App\\Models\\Missing"]
    assert len(missing) == 1
    assert missing[0].reason == "model_table_unknown"
    assert missing[0].subject is None
    assert {f.name for f in result.model.fact_types} == {
        "squads",
        "users",
        "team_user",
        "people",
        "audit_log",
    }


def test_irregular_plural_needs_explicit_table(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("eloquent")
    assert any(
        f.reason == "model_table_unknown" and f.detail == "App\\Models\\Person"
        for f in result.findings
    )
    people = next(f for f in result.model.fact_types if f.name == "people")
    assert any(b.target == "App\\Models\\ExplicitPerson" for b in people.bindings)
    user = next(f for f in result.model.fact_types if f.name == "users")
    assert any(b.target == "App\\Models\\User" for b in user.bindings)
    audit = next(f for f in result.model.fact_types if f.name == "audit_log")
    assert any(b.target == "App\\Models\\AuditLog" for b in audit.bindings)
