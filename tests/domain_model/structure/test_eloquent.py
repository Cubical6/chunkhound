"""Eloquent enrichment obeys storage authority and literal model conventions."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure


@pytest.mark.parametrize(
    "cast,expected",
    [
        ("Priority::class", ("-1", "1", "8")),
        (r"'App\Priority'", ("-1", "1", "8")),
        ("Pure::class", ()),
        ("AsArrayObject::class", ()),
        (r"\Vendor\CustomCast::class", ()),
    ],
)
def test_casts_only_add_values_for_backed_project_enums(
    tmp_path: Path, cast: str, expected: tuple[str, ...]
) -> None:
    (tmp_path / "schema.sql").write_text(
        "CREATE TABLE entries (id INT PRIMARY KEY, priority INT);\n"
    )
    source = r"""<?php
namespace App;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Casts\AsArrayObject;
enum Pure { case Low; case High; }
enum Priority: int { case Low = -1; case Normal = 1; case High = 010; }
class Entry extends Model {
    protected $casts = ['priority' => Priority::class];
}
"""
    (tmp_path / "Entry.php").write_text(source.replace("Priority::class", cast))
    repo = RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False)
    result = build_structure(tmp_path, (repo,))
    values = [r for r in result.model.validation_rules if r.rule_kind == "value"]
    assert len(values) == bool(expected)
    if expected:
        assert values[0].allowed_values == expected
        assert values[0].citations[0].path == "Entry.php"
    assert not result.findings


@pytest.mark.parametrize(
    "table,reason",
    [
        ("'absent_users'", "model_table_unknown"),
        ("USER_TABLE", "non_literal_argument"),
    ],
)
def test_explicit_table_never_falls_back(
    tmp_path: Path, table: str, reason: str
) -> None:
    fixture = Path(__file__).parent / "fixtures/eloquent"
    shutil.copytree(fixture, tmp_path, dirs_exist_ok=True)
    user = tmp_path / "app/Models/User.php"
    user.write_text(
        user.read_text().replace(
            "class User extends BaseRecord {}",
            "class User extends BaseRecord { protected $table = " + table + "; }",
        )
    )
    repo = RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False)
    result = build_structure(tmp_path, (repo,))
    findings = [f for f in result.findings if f.citations[0].path.endswith("User.php")]
    assert len(findings) == 1 and findings[0].reason == reason
    if reason == "model_table_unknown":
        assert findings[0].detail == "App\\Models\\User"
    users = next(f for f in result.model.fact_types if f.name == "users")
    assert [b.target for b in users.bindings] == ["users"]


@pytest.mark.parametrize("key", ["id", "uuid"])
def test_belongs_to_uses_method_name_and_related_primary_key(
    tmp_path: Path, key: str
) -> None:
    (tmp_path / "schema.sql").write_text(
        f"CREATE TABLE users ({key} INT PRIMARY KEY);\n"
        f"CREATE TABLE posts (id INT PRIMARY KEY, owner_{key} INT, "
        f"team_lead_{key} INT, explicit_owner INT);\n"
    )
    source = r"""<?php
use Illuminate\Database\Eloquent\Model;
class User extends Model { PRIMARY_KEY }
class Post extends Model {
    function owner() { return $this->belongsTo(User::class); }
    function teamLead() { return $this->belongsTo(User::class); }
    function custom() { return $this->belongsTo(User::class, 'explicit_owner'); }
}
"""
    declaration = "" if key == "id" else "protected $primaryKey = 'uuid';"
    (tmp_path / "Models.php").write_text(source.replace("PRIMARY_KEY", declaration))
    repo = RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False)
    result = build_structure(tmp_path, (repo,))
    subsets = [r for r in result.model.validation_rules if r.rule_kind == "subset"]
    assert {r.roles[0].rsplit("/", 1)[-1] for r in subsets} == {
        "owner-" + key,
        "team-lead-" + key,
        "explicit-owner",
    }
    assert all(r.superset_roles == ("role:root/users/" + key,) for r in subsets)
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
    assert {f.detail for f in result.findings} == {
        "App\\Models\\Missing",
        "App\\Models\\Person",
    }
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
