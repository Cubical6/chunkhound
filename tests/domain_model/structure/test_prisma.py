"""Prisma extraction contracts."""

from collections.abc import Callable

from chunkhound.domain_model.structure.contract import StructureExtraction


def test_prisma_models_map_to_storage_and_relations(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("prisma")
    assert any(f.name == "team_members" for f in result.model.fact_types)
    assert any(r.name == "e_mail" for r in result.model.roles)
    assert any(c.term == "team member" for c in result.model.concepts)
    roles = {
        r.name
        for r in result.model.roles
        if r.fact_type == "fact_type:root/team-members"
    }
    assert "team_id" in roles and "team" not in roles and "omitted" not in roles
    assert any(
        r.rule_kind == "subset"
        and r.fact_type == "fact_type:root/team-members"
        and r.superset_fact_type == "fact_type:root/teams"
        for r in result.model.validation_rules
    )
    assert any(
        r.rule_kind == "value"
        and r.fact_type == "fact_type:root/users"
        and r.allowed_values == ("active", "INACTIVE")
        for r in result.model.validation_rules
    )
    assert any(
        r.rule_kind == "uniqueness"
        and r.roles
        == ("role:root/team-members/team-id", "role:root/team-members/userid")
        for r in result.model.validation_rules
    )
    assert any(
        r.rule_kind == "uniqueness"
        and r.roles == ("role:root/pair/left", "role:root/pair/right")
        for r in result.model.validation_rules
    )
    assert any(
        r.rule_kind == "uniqueness"
        and r.roles == ("role:root/pair/right", "role:root/pair/extra")
        for r in result.model.validation_rules
    )
    assert any(r.name == "nickname" for r in result.model.roles)
    assert not any(
        r.rule_kind == "uniqueness"
        and ("role:root/users/nickname" in r.roles or "role:root/users/note" in r.roles)
        for r in result.model.validation_rules
    )
    assert not any(
        f.kind == "uncertain"
        and f.subject in {"fact_type:root/team-members", "fact_type:root/pair"}
        for f in result.findings
    )
    assert any(
        f.kind == "technical" and f.subject == "fact_type:root/prisma-migrations"
        for f in result.findings
    )
    assert not any(f.name == "Ignored" for f in result.model.fact_types)
