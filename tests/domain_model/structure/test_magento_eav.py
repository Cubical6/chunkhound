"""Magento EAV roles share the entity's storage fact type and provenance."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
)
from chunkhound.domain_model.structure.extract import build_structure

ExtractFixture = Callable[[str], StructureExtraction]
FACT = "fact_type:root/catalog-product-entity"
ROLE = "role:root/catalog-product-entity/"
FIXTURE = Path(__file__).parent / "fixtures/magento_eav"
PATCH = "app/code/Acme/Notes/Setup/Patch/Data/AddAttributes.php"


def test_eav_attribute_becomes_role_on_entity_fact_type(
    extract_fixture: ExtractFixture,
) -> None:
    result = extract_fixture("magento_eav")
    fact = next(f for f in result.model.fact_types if f.id == FACT)
    roles = {r.name: r for r in result.model.roles if r.fact_type == FACT}
    for code, datatype in (
        ("external_code", "varchar"),
        ("color", "int"),
        ("status", "int"),
    ):
        role = roles[code]
        assert role.bindings[0].target == f"eav:catalog_product.{code}"
        assert role.datatype == datatype
        assert (
            f"catalog_product_entity(<entity_id>) has {code} <{code}>" in fact.templates
        )
    assert sum(r.bindings[0].target.startswith("eav:") for r in roles.values()) == 3
    assert roles["external_code"].mandatory is True
    assert roles["color"].mandatory is False
    assert roles["status"].mandatory is False
    assert len(result.model.fact_types) == 1
    assert not any(f.reason == "vendor_missing" for f in result.findings)
    assert not any(f.kind == "uncertain" for f in result.findings)
    assert any(f.reason == "vendor_not_followed" for f in result.findings)


def test_required_unique_attribute_gets_uniqueness_rule(
    extract_fixture: ExtractFixture,
) -> None:
    result = extract_fixture("magento_eav")
    rule = next(
        r for r in result.model.validation_rules if r.roles == (ROLE + "external-code",)
    )
    assert rule.rule_kind == "uniqueness"
    assert rule.citations[0].path == PATCH


def test_own_source_model_gives_value_rule(extract_fixture: ExtractFixture) -> None:
    result = extract_fixture("magento_eav")
    rules = [r for r in result.model.validation_rules if r.rule_kind == "value"]
    assert len(rules) == 1
    assert rules[0].roles == (ROLE + "color",)
    assert rules[0].allowed_values == ("red", "blue")
    assert rules[0].citations[0].path.endswith("/Model/Source/Color.php")
    assert not any(f.subject == ROLE + "status" for f in result.findings)
    assert not any(f.reason == "unreadable_source" for f in result.findings)


def test_variable_attribute_code_is_unresolved(extract_fixture: ExtractFixture) -> None:
    result = extract_fixture("magento_eav")
    unresolved = [f for f in result.findings if f.kind == "unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0].reason == "non_literal_argument"
    assert unresolved[0].citations[0].path == PATCH
    assert unresolved[0].citations[0].start_line == 20


def test_eav_role_is_not_third_party_but_entity_table_is(
    extract_fixture: ExtractFixture,
) -> None:
    result = extract_fixture("magento_eav")
    marked = {f.subject: f for f in result.findings if f.kind == "third_party"}
    assert marked[FACT].reason == "vendor_table_extended"
    assert marked[FACT].detail == "magento/module-catalog 104.0.7"
    assert ROLE + "entity-id" in marked
    for code in ("external-code", "color", "status"):
        assert ROLE + code not in marked


def _build(project: Path) -> StructureExtraction:
    return build_structure(
        project, (RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False),)
    )


def test_literal_custom_entity_has_unknown_table(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    path = tmp_path / PATCH
    path.write_text(
        path.read_text().replace(
            "Product::ENTITY, $dynamicCode", "'my_custom_entity', 'code'"
        )
    )
    result = _build(tmp_path)
    assert [(f.reason, f.detail) for f in result.findings if f.kind == "unresolved"] == [
        ("model_table_unknown", "my_custom_entity")
    ]


def test_missing_entity_table_is_uncertain_without_key_roles(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    shutil.rmtree(tmp_path / "vendor")
    result = _build(tmp_path)
    fact = next(f for f in result.model.fact_types if f.id == FACT)
    assert fact.identifies is None
    assert len(fact.roles) == len(fact.templates) == 3
    assert (
        fact.templates[0] == "catalog_product_entity has external_code <external_code>"
    )
    assert any(
        f.kind == "uncertain"
        and f.reason == "entity_table_missing"
        and f.subject == FACT
        for f in result.findings
    )
    assert sum(f.reason == "vendor_missing" for f in result.findings) == 1
    assert not any(f.kind == "third_party" for f in result.findings)


@pytest.mark.parametrize(
    "entity, table",
    [
        ("'catalog_category'", "catalog_category_entity"),
        ("\\Magento\\Catalog\\Model\\Category::ENTITY", "catalog_category_entity"),
        ("\\Magento\\Customer\\Model\\Customer::ENTITY", "customer_entity"),
        (
            "\\Magento\\Customer\\Api\\AddressMetadataInterface::ENTITY_TYPE_ADDRESS",
            "customer_address_entity",
        ),
    ],
)
def test_known_entities_and_setup_subclasses(
    entity: str, table: str, tmp_path: Path
) -> None:
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    (tmp_path / PATCH).write_text(
        "<?php namespace Acme\\Notes\\Setup\\Patch\\Data;\n"
        "use Magento\\Customer\\Setup\\CustomerSetup as Setup;\n"
        "class CustomSetup extends Setup {}\n"
        "class Patch { function apply(CustomSetup $setup) {\n"
        f"$setup->addAttribute({entity}, 'flag', ['type' => 'static']);\n"
        "} }\n"
    )
    result = _build(tmp_path)
    role = next(r for r in result.model.roles if r.name == "flag")
    assert role.bindings[0].target == f"eav:{table.removesuffix('_entity')}.flag"
    assert role.datatype == "static"
    assert role.mandatory is False


def test_dynamic_entity_is_unresolved_and_dynamic_source_is_ignored(
    tmp_path: Path,
) -> None:
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    path = tmp_path / PATCH
    path.write_text(
        path.read_text().replace(
            "Product::ENTITY, $dynamicCode", "$entity, 'known_code'"
        )
    )
    source = tmp_path / "app/code/Acme/Notes/Model/Source/Color.php"
    source.write_text(source.read_text().replace("'red'", "$dynamicValue"))
    result = _build(tmp_path)
    assert sum(f.reason == "non_literal_argument" for f in result.findings) == 1
    assert not any(r.rule_kind == "value" for r in result.model.validation_rules)
    assert not any(f.subject == ROLE + "color" for f in result.findings)
