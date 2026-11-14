"""Magento declarative storage and bounded third-party extraction contracts."""

import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from chunkhound.domain_model.structure.contract import (
    RepositoryRef,
    StructureExtraction,
    dump_structure,
    parse_structure,
)
from chunkhound.domain_model.structure.extract import build_structure

ExtractFixture = Callable[[str], StructureExtraction]


@pytest.mark.parametrize(
    "filename", ["db_schema.xml", "webapi.xml", "frontend/routes.xml", "di.xml"]
)
def test_malformed_xml_reports_error_without_losing_valid_elements(
    tmp_path: Path, filename: str
) -> None:
    module = tmp_path / "app/code/Acme/Notes"
    (module / "etc/frontend").mkdir(parents=True)
    (module / "registration.php").write_text(
        "<?php ComponentRegistrar::register("
        "ComponentRegistrar::MODULE, 'Acme_Notes', __DIR__);"
    )
    (module / "etc/module.xml").write_text(
        '<config><module name="Acme_Notes"/></config>'
    )
    schema = module / "etc/db_schema.xml"
    schema.write_text(
        '<schema><table name="notes"><column name="id" xsi:type="int"/>'
        "</table></schema>"
    )
    path = module / "etc" / filename
    if path != schema:
        path.write_text("<config/>")
    path.write_text(path.read_text() + "\n<")
    repo = RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False)
    result = build_structure(tmp_path, (repo,))
    (finding,) = [
        f
        for f in result.findings
        if f.reason == "unreadable_source"
        and f.citations[0].path == path.relative_to(tmp_path).as_posix()
    ]
    assert finding.kind == "unresolved"
    assert finding.subject is None and finding.detail is None
    assert finding.citations[0].start_line == finding.citations[0].end_line == 2
    assert {fact.name for fact in result.model.fact_types} == {"notes"}
    assert parse_structure(dump_structure(result)) == result


def test_discarded_vendor_table_findings_have_no_dangling_subject(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    shutil.copytree(Path(__file__).parent / "fixtures/magento_schema", project)
    # The referenced vendor table points to an unfollowed table. Columns
    # without usable keys mean it cannot produce a fact type.
    for path in project.rglob("db_schema.xml"):
        text = path.read_text()
        text = re.sub(
            r'(<table name="customer_entity"[^>]*>)(.*?)(</table>)',
            lambda match: match[1]
            + re.sub(r'(name|column)="[^"]+"', r'\1="_"', match[2])
            + match[3],
            text,
            flags=re.DOTALL,
        )
        path.write_text(text)
    repo = RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False)
    result = build_structure(project, (repo,))
    assert "customer_entity" not in {fact.name for fact in result.model.fact_types}
    assert any(
        f.reason == "vendor_not_followed" and f.subject is None for f in result.findings
    )
    dumped = dump_structure(result)
    assert dump_structure(parse_structure(dumped)) == dumped


def test_referenced_vendor_table_is_third_party_with_package(
    extract_fixture: ExtractFixture,
) -> None:
    result = extract_fixture("magento_schema")
    finding = next(
        f
        for f in result.findings
        if f.subject == "fact_type:root/customer-entity" and f.kind == "third_party"
    )
    assert finding.reason == "vendor_table_referenced"
    assert finding.detail == "magento/module-customer 104.0.7"
    assert all(
        c.repository == "root" and c.commit == "1" * 40 for c in finding.citations
    )
    rule = next(
        r
        for r in result.model.validation_rules
        if r.rule_kind == "subset" and r.fact_type == "fact_type:root/acme-note"
    )
    assert rule.fact_type == "fact_type:root/acme-note"
    assert rule.superset_fact_type == "fact_type:root/customer-entity"
    assert any(
        r.rule_kind == "subset"
        and r.fact_type == "fact_type:root/sales-order"
        and r.superset_fact_type == "fact_type:root/customer-entity"
        for r in result.model.validation_rules
    ) and not any(
        f.subject == "fact_type:root/sales-order" and f.reason == "vendor_not_followed"
        for f in result.findings
    )
    assert any(
        f.reason == "vendor_not_followed"
        and f.detail == "(group_id) -> customer_group(id)"
        for f in result.findings
    )


def test_own_column_on_vendor_table_is_not_third_party(
    extract_fixture: ExtractFixture,
) -> None:
    result = extract_fixture("magento_schema")
    marked = {f.subject for f in result.findings if f.kind == "third_party"}
    assert "fact_type:root/sales-order" in marked
    assert "role:root/sales-order/entity-id" in marked
    assert "role:root/sales-order/acme-note" not in marked
    assert any(r.id == "role:root/sales-order/acme-note" for r in result.model.roles)
    assert any(
        f.subject == "fact_type:root/sales-order"
        and f.reason == "vendor_table_extended"
        and f.detail == "magento/module-sales 104.0.7"
        for f in result.findings
    )


def test_untouched_vendor_table_is_absent(extract_fixture: ExtractFixture) -> None:
    result = extract_fixture("magento_schema")
    names = {f.name for f in result.model.fact_types}
    assert "untouched_vendor" not in names
    assert "customer_group" not in names


def test_vendor_is_read_despite_gitignore(extract_fixture: ExtractFixture) -> None:
    result = extract_fixture("magento_schema")
    assert any(
        f.id == "fact_type:root/customer-entity" for f in result.model.fact_types
    )
    assert not any(f.reason == "vendor_missing" for f in result.findings)


def test_module_outside_app_code_is_read(extract_fixture: ExtractFixture) -> None:
    result = extract_fixture("magento_schema")
    assert any(f.id == "fact_type:root/acme-audit" for f in result.model.fact_types)
    assert any(r.id == "role:root/acme-note/audit-message" for r in result.model.roles)
    assert not any(f.reason == "table_created_twice" for f in result.findings)


def test_missing_vendor_is_reported_once(extract_fixture: ExtractFixture) -> None:
    result = extract_fixture("magento_schema_no_vendor")
    assert sum(f.reason == "vendor_missing" for f in result.findings) == 1
    assert any(
        f.kind == "external_reference"
        and f.reason == "table_not_found"
        and f.subject == "fact_type:root/acme-note"
        for f in result.findings
    )


def test_declarative_types_nullability_and_disabled_elements(
    extract_fixture: ExtractFixture,
) -> None:
    result = extract_fixture("magento_schema")
    roles = {r.id: r for r in result.model.roles}
    assert roles["role:root/acme-note/id"].datatype == "int unsigned"
    assert roles["role:root/acme-note/id"].mandatory is True
    assert roles["role:root/acme-note/amount"].datatype == "decimal(12,4)"
    assert roles["role:root/acme-note/amount"].mandatory is None
    assert roles["role:root/acme-note/label"].datatype == "varchar(80)"
    assert roles["role:root/acme-note/label"].mandatory is False
    assert "role:root/acme-note/obsolete" not in roles
    assert "role:root/sales-order/old-column" not in roles
    assert not any(
        f.id == "fact_type:root/removed-table" for f in result.model.fact_types
    )
    assert any(
        r.rule_kind == "uniqueness" and r.roles == ("role:root/acme-note/label",)
        for r in result.model.validation_rules
    )
    assert not any(
        "old-column" in role for r in result.model.validation_rules for role in r.roles
    )
    assert not any(f.kind == "uncertain" for f in result.findings)


def test_vendor_discovery_respects_declared_repository_roots(tmp_path: Path) -> None:
    fixtures = Path(__file__).parent / "fixtures"
    shutil.copytree(fixtures / "magento_schema", tmp_path, dirs_exist_ok=True)
    nested = tmp_path / "nested"
    shutil.copytree(fixtures / "magento_schema", nested)
    # A vendor tree below an arbitrary directory is not a repository vendor tree.
    shutil.copytree(tmp_path / "vendor", tmp_path / "unrelated/vendor")
    repos = tuple(
        RepositoryRef(key=key, path=path, commit="1" * 40, dirty=False)
        for key, path in (("root", "."), ("nested", "nested"))
    )
    result = build_structure(tmp_path, repos)
    assert any(
        f.id == "fact_type:nested/customer-entity" for f in result.model.fact_types
    )
    assert not any(
        c.path.startswith("unrelated/")
        for f in result.model.fact_types
        for c in f.citations
    )
    assert not any(f.reason == "vendor_missing" for f in result.findings)
    shutil.rmtree(nested / "vendor")
    result = build_structure(tmp_path, repos)
    missing = [f for f in result.findings if f.reason == "vendor_missing"]
    assert len(missing) == 1
    assert missing[0].citations[0].repository == "nested"
    shutil.rmtree(tmp_path / "vendor")
    result = build_structure(tmp_path, repos)
    assert sum(f.reason == "vendor_missing" for f in result.findings) == 1


def test_xml_external_entities_are_not_resolved(tmp_path: Path) -> None:
    module = tmp_path / "packages/notes"
    (module / "etc").mkdir(parents=True)
    (module / "registration.php").write_text("<?php // registration\n")
    (module / "etc/module.xml").write_text(
        '<config><module name="Acme_Notes"/></config>'
    )
    secret = tmp_path / "secret.txt"
    secret.write_text("private-content")
    (module / "etc/db_schema.xml").write_text(
        f'<!DOCTYPE schema [<!ENTITY external SYSTEM "{secret.as_uri()}">]>'
        '<schema xmlns:xsi="urn:test"><table name="notes">'
        '<column xsi:type="text" name="&external;"/></table></schema>'
    )
    result = build_structure(
        tmp_path, (RepositoryRef(key="root", path=".", commit="1" * 40, dirty=False),)
    )
    assert any(r.name == "&external;" for r in result.model.roles)
    assert not any(r.name == "private-content" for r in result.model.roles)
