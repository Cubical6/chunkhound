"""Storage readers have explicit priority and never union their columns."""

from collections.abc import Callable
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure


def test_storage_claims_agree_add_and_diverge(
    extract_fixture: Callable[[str], StructureExtraction],
) -> None:
    result = extract_fixture("overlap")
    subset = next(r for r in result.model.validation_rules if r.rule_kind == "subset")
    assert len(subset.citations) == 2
    value = next(
        r
        for r in result.model.validation_rules
        if r.rule_kind == "value" and r.roles[0].endswith("/visibility")
    )
    assert value.allowed_values == ("public", "private")
    assert len(value.citations) == 1
    assert "migrations" in value.citations[0].path
    (claim,) = result.divergent_claims
    assert claim.property == "allowed_values" and claim.value == ("active",)
    assert claim.source == "laravel_migrations"
    assert any(
        f.reason == "column_only_in_lower_source" and f.detail == "lower_only"
        for f in result.findings
    )
    assert not any(f.reason == "key_collision" for f in result.findings)
    role = next(r for r in result.model.roles if r.name == "visibility")
    assert role.datatype == "varchar(30)"


def test_lower_mandatory_claim_preserves_storage_authority(tmp_path: Path) -> None:
    (tmp_path / "schema.sql").write_text(
        "CREATE TABLE items (id BIGINT PRIMARY KEY, "
        "required TEXT NOT NULL, optional TEXT);\n"
    )
    migration = tmp_path / "database/migrations/2024_create.php"
    migration.parent.mkdir(parents=True)
    migration.write_text("""<?php
use Illuminate\\Support\\Facades\\Schema;
return new class {
    public function up() {
        Schema::create('items', function ($table) {
            $table->id();
            $table->string('required')->nullable();
            $table->string('optional')->nullable();
        });
    }
};
""")
    repo = RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False)
    result = build_structure(tmp_path, (repo,))
    required = next(r for r in result.model.roles if r.name == "required")
    optional = next(r for r in result.model.roles if r.name == "optional")
    assert required.mandatory is True and optional.mandatory is False
    assert len(required.citations) == 1 and len(optional.citations) == 2
    (claim,) = result.divergent_claims
    assert claim.subject == required.id
    assert claim.property == "mandatory" and claim.value is False
    assert claim.source == "laravel_migrations"


SOURCES = [
    {"schema.sql": "CREATE TABLE items (id BIGINT PRIMARY KEY, sql_only TEXT);\n"},
    {
        "database/migrations/2024_create.php": """<?php
use Illuminate\\Support\\Facades\\Schema;
return new class {
    public function up() {
        Schema::create('items', function ($table) {
            $table->id(); $table->string('laravel_only');
        });
    }
};
"""
    },
    {
        "app/code/Acme/Notes/registration.php": (
            "<?php ComponentRegistrar::register("
            "ComponentRegistrar::MODULE, 'Acme_Notes', __DIR__);\n"
        ),
        "app/code/Acme/Notes/etc/module.xml": (
            '<config><module name="Acme_Notes"/></config>\n'
        ),
        "app/code/Acme/Notes/etc/db_schema.xml": (
            '<schema xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<table name="items"><column xsi:type="int" name="id" nullable="false"/>'
            '<column xsi:type="text" name="magento_only"/></table></schema>\n'
        ),
    },
    {
        "schema.prisma": (
            'model Item {\n id Int @id\n prisma_only String\n @@map("items")\n}\n'
        )
    },
    {
        "entity.ts": (
            "@Entity('items')\nexport class Item {\n"
            " @PrimaryGeneratedColumn() id: number;\n"
            " @Column() typeorm_only: string;\n}\n"
        )
    },
]


def test_lower_source_does_not_fill_unknown_storage_mandatory(tmp_path: Path) -> None:
    for path, content in SOURCES[2].items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.replace("magento_only", "shared"))
    (tmp_path / "schema.prisma").write_text(
        'model Item {\n id Int @id\n shared String\n @@map("items")\n}\n'
    )
    repo = RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False)
    result = build_structure(tmp_path, (repo,))
    shared = next(r for r in result.model.roles if r.name == "shared")
    assert shared.mandatory is None
    (claim,) = result.divergent_claims
    assert claim.subject == shared.id
    assert claim.property == "mandatory" and claim.value is True
    assert claim.source == "prisma"


@pytest.mark.parametrize(
    "higher,lower", [(h, low) for h in range(4) for low in range(h + 1, 5)]
)
def test_second_storage_source_never_adds_a_role(
    tmp_path: Path, higher: int, lower: int
) -> None:
    for source in (SOURCES[higher], SOURCES[lower]):
        for path, content in source.items():
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    repo = RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False)
    result = build_structure(tmp_path, (repo,))
    expected = [
        "sql_only",
        "laravel_only",
        "magento_only",
        "prisma_only",
        "typeorm_only",
    ]
    assert len(result.model.fact_types) == 1
    assert {r.name for r in result.model.roles} == {"id", expected[higher]}
    assert any(
        f.reason == "column_only_in_lower_source" and f.detail == expected[lower]
        for f in result.findings
    )
    assert not any(f.reason == "key_collision" for f in result.findings)
