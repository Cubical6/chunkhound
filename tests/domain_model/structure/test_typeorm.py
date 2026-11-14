"""Storage extraction contracts for TypeORM entities."""

from collections.abc import Callable
from pathlib import Path

from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure


def test_entity_without_name_uses_snake_case_class_name(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("typeorm")
    assert any(f.id == "fact_type:root/team-record" for f in result.model.fact_types)
    assert any(c.term == "team member" for c in result.model.concepts)
    roles = {
        r.name: r
        for r in result.model.roles
        if r.fact_type == "fact_type:root/team-user"
    }
    assert "ignored" not in roles and "alsoIgnored" not in roles
    assert roles["email_address"].datatype == "varchar"
    assert roles["createdAt"].mandatory is True
    assert roles["deletedAt"].mandatory is False
    assert roles["version"].datatype == "number"
    assert any(
        f.kind == "technical" and f.subject == "fact_type:root/migrations"
        for f in result.findings
    )


def test_join_column_names_the_role_and_gives_subset_rule(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("typeorm")
    assert any(
        r.id == "role:root/team-user/team-id" and r.mandatory is True
        for r in result.model.roles
    )
    assert any(
        r.rule_kind == "subset"
        and r.roles == ("role:root/team-user/team-id",)
        and r.superset_roles == ("role:root/team-record/id",)
        for r in result.model.validation_rules
    )


def test_composite_unique_becomes_uniqueness_rule(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("typeorm")
    rules = [
        r.roles for r in result.model.validation_rules if r.rule_kind == "uniqueness"
    ]
    assert ("role:root/team-user/team-id", "role:root/team-user/email-address") in rules
    assert ("role:root/team-user/email-address", "role:root/team-user/role") in rules
    assert ("role:root/team-user/member-id", "role:root/team-user/role") in rules


def test_imported_enum_gives_value_rule(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("typeorm")
    assert any(
        r.rule_kind == "value"
        and r.roles == ("role:root/team-user/role",)
        and r.allowed_values == ("owner", "member")
        for r in result.model.validation_rules
    )


def test_non_literal_option_is_unresolved(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("typeorm")
    findings = [f for f in result.findings if f.reason == "non_literal_argument"]
    assert len(findings) == 1 and findings[0].kind == "unresolved"
    assert findings[0].citations[0].path == "entities.ts"
    assert findings[0].citations[0].start_line == 34
    assert any(
        r.name == "description" and r.datatype == "varchar" for r in result.model.roles
    )


def test_datatypes_use_literal_type_or_annotation(tmp_path: Path) -> None:
    result = extract_source(
        tmp_path,
        """
@Entity() class Item {
 @PrimaryGeneratedColumn() id: number;
 @Column() name: string;
 @CreateDateColumn() createdAt: Date;
 @Column({type: 'varchar', length: 20}) code: string;
 @Column({type: runtimeType}) fallback: string;
 @Column() untyped;
}
""",
    )
    assert {r.name: r.datatype for r in result.model.roles} == {
        "id": "number",
        "name": "string",
        "createdAt": "Date",
        "code": "varchar",
        "fallback": "string",
        "untyped": None,
    }
    assert len(result.findings) == 1
    assert result.findings[0].reason == "non_literal_argument"


def test_join_columns_keep_source_role_and_template_order(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("typeorm")
    fact = next(f for f in result.model.fact_types if f.name == "team_user")
    assert fact.roles == tuple(
        "role:root/team-user/" + name
        for name in (
            "member-id",
            "team-id",
            "email-address",
            "role",
            "createdat",
            "updatedat",
            "deletedat",
            "owner-id",
            "version",
        )
    )
    assert "team_id" in fact.templates[1]
    assert "email_address" in fact.templates[2]


def test_explicit_and_join_columns_merge_in_either_order(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("typeorm")
    roles = {
        r.name: r
        for r in result.model.roles
        if r.fact_type == "fact_type:root/team-user"
    }
    assert roles["team_id"].datatype == "number"
    assert roles["team_id"].mandatory is True
    assert roles["owner_id"].datatype == "number"
    assert roles["owner_id"].mandatory is False
    assert len(roles["team_id"].citations) == len(roles["owner_id"].citations) == 2
    assert {
        r.roles for r in result.model.validation_rules if r.rule_kind == "subset"
    } == {
        ("role:root/team-user/team-id",),
        ("role:root/team-user/owner-id",),
    }
    fact = next(f for f in result.model.fact_types if f.name == "team_user")
    assert fact.roles[1] == "role:root/team-user/team-id"
    assert fact.roles[-2:] == (
        "role:root/team-user/owner-id",
        "role:root/team-user/version",
    )
    assert not any(f.kind == "uncertain" for f in result.findings)


def test_duplicate_entity_does_not_add_members(tmp_path: Path) -> None:
    result = extract_source(
        tmp_path,
        """
@Entity('items') class Item { @PrimaryColumn() id: number; }
@Entity('items') class Duplicate {
 @PrimaryColumn() id: number;
 @Column() extra: string;
 @ManyToOne(() => Missing) missing: Missing;
}
""",
    )
    assert [r.name for r in result.model.roles] == ["id"]
    assert [f.reason for f in result.findings] == ["table_created_twice"]


def test_unknown_relation_targets_keep_columns_without_guessing_foreign_keys(
    tmp_path: Path,
) -> None:
    result = extract_source(
        tmp_path,
        """
import { Team } from '@/entities';
@Entity() class Known { @PrimaryColumn() id: number; }
@Entity() class Item {
 @PrimaryColumn() id: number;
 @ManyToOne(() => Team, {nullable: false, cascade: runtimeOptions})
 @JoinColumn({name: 'team_id'}) team: Team;
 @OneToOne(() => Missing) @JoinColumn() missing: Missing;
 @ManyToOne('Absent') absent: Absent;
 @ManyToOne('Known') known: Known;
}
""",
    )
    roles = {
        r.name: r for r in result.model.roles if r.fact_type == "fact_type:root/item"
    }
    assert set(roles) == {"id", "team_id", "missingId", "absentId", "knownId"}
    assert roles["team_id"].mandatory is True
    assert roles["absentId"].mandatory is False
    assert {(f.reason, f.detail) for f in result.findings} == {
        ("model_table_unknown", "Team"),
        ("model_table_unknown", "Missing"),
        ("model_table_unknown", "Absent"),
    }
    assert [
        r.roles for r in result.model.validation_rules if r.rule_kind == "subset"
    ] == [("role:root/item/knownid",)]


def test_citations_cover_whole_class_and_property(tmp_path: Path) -> None:
    result = extract_source(
        tmp_path,
        """@Entity('items')
export class Item {
 @PrimaryColumn()
 id: number;
 @Column({type: 'varchar'})
 name: string;
}
""",
    )
    fact = result.model.fact_types[0]
    assert (
        fact.bindings[0].citation.start_line,
        fact.bindings[0].citation.end_line,
    ) == (1, 7)
    name = next(r for r in result.model.roles if r.name == "name")
    assert (
        name.bindings[0].citation.start_line,
        name.bindings[0].citation.end_line,
    ) == (5, 6)


def test_javascript_string_escapes_are_literal_enum_values(tmp_path: Path) -> None:
    result = extract_source(
        tmp_path,
        r"""
@Entity() class Item {
 @PrimaryColumn() id: number;
 @Column({type: 'enum', enum: ['\u{1F600}', '\N', '\n\t\r\\\'\"\`', '\u0041\x42']})
 value: string;
}
""",
    )
    assert not result.findings
    assert any(
        r.allowed_values == ("😀", "N", "\n\t\r\\'\"`", "AB")
        for r in result.model.validation_rules
    )


def extract_source(tmp_path: Path, source: str) -> StructureExtraction:
    (tmp_path / "item.ts").write_text(source)
    return build_structure(
        tmp_path, (RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False),)
    )


def test_only_used_dynamic_options_are_unresolved_and_keep_known_columns(
    tmp_path: Path,
) -> None:
    (tmp_path / "role.ts").write_text("export enum Role { A = 'a' }")
    (tmp_path / "barrel.ts").write_text("export * from './role';")
    result = extract_source(
        tmp_path,
        """
import { Role } from './barrel';
import * as E from './role';
@Entity({name: 'items', orderBy: runtimeOptions})
@Unique(['nullable', 'barrel'])
@Index(['namespace', 'length'], {unique: true, where: runtimeFilter})
class Item {
 @PrimaryColumn() id: number;
 @Column({default: () => 'a', transformer: new X()}) ignored: string;
 @Column({default: Role.A}) another: string;
 @Column({nullable: runtimeFlag}) nullable: string;
 @Column({enum: Role}) barrel: Role;
 @Column({enum: E.Role}) namespace: E.Role;
 @Column({length: runtimeLength}) length: string;
 @Column({name: runtimeName}) absent: string;
}
""",
    )
    assert len(result.findings) == 5
    assert all(f.reason == "non_literal_argument" for f in result.findings)
    roles = {r.name: r for r in result.model.roles}
    assert set(roles) == {
        "id",
        "ignored",
        "another",
        "nullable",
        "barrel",
        "namespace",
        "length",
    }
    assert roles["nullable"].mandatory is None
    assert roles["ignored"].mandatory is True
    assert not any(r.rule_kind == "value" for r in result.model.validation_rules)
    unique = {
        r.roles for r in result.model.validation_rules if r.rule_kind == "uniqueness"
    }
    assert ("role:root/items/nullable", "role:root/items/barrel") in unique
    assert ("role:root/items/namespace", "role:root/items/length") in unique


def test_tsx_relative_entities_and_local_numeric_enum(tmp_path: Path) -> None:
    (tmp_path / "target.ts").write_text(
        "@Entity('teams') export default class Team { "
        "@PrimaryGeneratedColumn('uuid') id: string; }"
    )
    (tmp_path / "member.tsx").write_text("""
import Group from './target.js';
enum Status { Draft, Active = 4, Closed }
@Entity({name: 'members'}) export class Member {
 @PrimaryColumn() id: number;
 @Column({type: 'enum', enum: Status}) status: Status;
 @ManyToOne(() => Group) group: Group;
 @OneToOne(() => Group)
 @JoinColumn({name: 'owner', referencedColumnName: 'id'}) owner: Group;
}
""")
    result = build_structure(
        tmp_path, (RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False),)
    )
    assert not result.findings
    assert any(
        r.fact_type == "fact_type:root/teams"
        and r.name == "id"
        and r.datatype == "string"
        for r in result.model.roles
    )
    assert any(
        r.allowed_values == ("0", "4", "5") for r in result.model.validation_rules
    )
    assert {
        r.roles for r in result.model.validation_rules if r.rule_kind == "subset"
    } == {
        ("role:root/members/groupid",),
        ("role:root/members/owner",),
    }
