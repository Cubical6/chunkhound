"""Technical findings retain facts and obey reader scope and project settings."""

from collections.abc import Callable
from pathlib import Path

from chunkhound.core.config.config import Config
from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure


def test_migration_tool_tables_are_technical(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("sql")
    subject = "fact_type:root/flyway-schema-history"
    assert any(f.id == subject for f in result.model.fact_types)
    assert any(
        f.subject == subject
        and f.kind == "technical"
        and f.reason == "framework_table"
        and f.detail == "migration_tools"
        for f in result.findings
    )


def test_technical_tables_follow_config(tmp_path: Path) -> None:
    schema = tmp_path / "database" / "schema"
    schema.mkdir(parents=True)
    (schema / "dump.sql").write_text(
        "CREATE TABLE sessions (id int PRIMARY KEY);\n"
        "CREATE TABLE jobs (id int PRIMARY KEY);\n"
        "CREATE TABLE audit_log (id int PRIMARY KEY);\n"
        "CREATE TABLE team_user (id int PRIMARY KEY);\n"
    )
    (tmp_path / ".chunkhound.json").write_text(
        '{"domain":{"technical_tables":{"add":["audit_*"],"remove":["sessions"]}}}'
    )
    repositories = (RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False),)
    default = build_structure(tmp_path, repositories)
    assert any(
        f.subject == "fact_type:root/sessions" and f.detail == "laravel"
        for f in default.findings
    )
    config = Config(
        target_dir=tmp_path, skip_layers={"env", "global", "config_file", "cli"}
    )
    result = build_structure(tmp_path, repositories, config)
    marked = {f.subject: f for f in result.findings if f.kind == "technical"}
    assert set(marked) == {"fact_type:root/jobs", "fact_type:root/audit-log"}
    assert marked["fact_type:root/audit-log"].reason == "configured"
    assert marked["fact_type:root/jobs"].reason == "framework_table"
    assert len(result.model.fact_types) == 4


def test_loose_sql_uses_only_applicable_technical_lists(tmp_path: Path) -> None:
    (tmp_path / "schema.sql").write_text(
        "CREATE TABLE jobs (id int PRIMARY KEY);\n"
        "CREATE TABLE sessions (id int PRIMARY KEY);\n"
        "CREATE TABLE migrations (id int PRIMARY KEY);\n"
        "CREATE TABLE notes_idx (id int PRIMARY KEY);\n"
    )
    result = build_structure(
        tmp_path, (RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False),)
    )
    assert [(f.subject, f.detail) for f in result.findings] == [
        ("fact_type:root/migrations", "typeorm")
    ]
