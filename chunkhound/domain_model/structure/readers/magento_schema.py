"""Declarative Magento schemas with a bounded, one-hop vendor boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from chunkhound.domain_model.identity import fact_type_id
from chunkhound.domain_model.loader import COLLECTIONS
from chunkhound.domain_model.model import Citation, DomainModel
from chunkhound.domain_model.structure.contract import Finding
from chunkhound.domain_model.structure.readers._magento import (
    find_modules,
    is_vendor,
    package_detail,
    read_xml,
)
from chunkhound.domain_model.structure.readers._xml import Element
from chunkhound.domain_model.structure.readers.magento_eav import (
    apply_attribute,
    collect_attributes,
)
from chunkhound.domain_model.structure.schema import (
    Column,
    Constraint,
    Schema,
    Span,
    Table,
)

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext


def _citation(ctx: ReadContext, span: Span) -> Citation:
    repo = ctx.repository_of(span.path)
    return Citation(
        repository=repo.key,
        path=span.path,
        start_line=span.start_line,
        end_line=span.end_line,
        commit=repo.commit,
    )


def _apply(schema: Schema, element: Element) -> None:
    attrs = element.attributes
    name = attrs.get("name")
    if not name:
        return
    if attrs.get("disabled") == "true":
        if name in schema.tables:
            schema.drop_table(name, element.span)
        return
    if name not in schema.tables:
        schema.create_table(
            Table(name=name, columns=(), constraints=(), defined_at=element.span)
        )
    else:
        table = schema.tables[name]
        # Own extensions do not turn the vendor table itself into an own element.
        if is_vendor(table.defined_at.path) == is_vendor(element.span.path):
            schema.tables[name] = table.model_copy(
                update={
                    "origin": (*(table.origin or (table.defined_at,)), element.span)
                }
            )
    for child in element.children:
        a = child.attributes
        column_name = a.get("name")
        if child.name == "column" and column_name:
            if a.get("disabled") == "true":
                if any(c.name == column_name for c in schema.tables[name].columns):
                    schema.drop_column(name, column_name, child.span)
                continue
            datatype = a.get("xsi:type")
            if datatype:
                if "precision" in a:
                    datatype += f"({a['precision']}" + (
                        f",{a['scale']})" if "scale" in a else ")"
                    )
                elif "length" in a:
                    datatype += f"({a['length']})"
                if a.get("unsigned") == "true":
                    datatype += " unsigned"
            column = Column(
                name=column_name,
                datatype=datatype,
                mandatory={"false": True, "true": False}.get(a.get("nullable", "")),
                origin=(child.span,),
                defined_at=child.span,
            )
            if any(c.name == column_name for c in schema.tables[name].columns):
                schema.change_column(name, column_name, column)
            else:
                schema.add_column(name, column)
    for child in element.children:
        if child.name != "constraint":
            continue
        a = child.attributes
        identifier = a.get("referenceId")
        kind = a.get("xsi:type")
        existing = next(
            (
                c
                for c in schema.tables[name].constraints
                if identifier and c.name == identifier
            ),
            None,
        )
        if existing:
            schema.drop_constraint(name, identifier, child.span)
        if a.get("disabled") == "true" or kind not in {"primary", "unique", "foreign"}:
            continue
        columns = (
            (a["column"],)
            if kind == "foreign" and "column" in a
            else tuple(
                c.attributes["name"] for c in child.children if "name" in c.attributes
            )
        )
        constraint = Constraint(
            kind=cast(Literal["primary", "unique", "foreign"], kind),
            name=identifier,
            columns=columns,
            ref_table=a.get("referenceTable"),
            ref_columns=(a["referenceColumn"],) if "referenceColumn" in a else (),
            spans=(*existing.spans, child.span) if existing else (child.span,),
        )
        schema.add_constraint(name, constraint)


class MagentoSchemaReader:
    name = "magento_schema"
    patterns: tuple[str, ...] = ("**/module.xml",)

    def read(self, ctx: ReadContext) -> None:
        modules = find_modules(ctx, self.name)
        missing_vendor = next(
            (
                module
                for module in modules
                if not module.third_party
                and not (
                    ctx.project_root
                    / ctx.repository_of(f"{module.path}/etc/module.xml").path
                    / "vendor"
                ).is_dir()
            ),
            None,
        )
        if missing_vendor is not None:
            ctx.findings.append(
                Finding(
                    kind="unresolved",
                    subject=None,
                    reason="vendor_missing",
                    detail=None,
                    citations=(
                        _citation(
                            ctx,
                            Span(
                                path=f"{missing_vendor.path}/etc/module.xml",
                                start_line=1,
                                end_line=1,
                                reader=self.name,
                            ),
                        ),
                    ),
                )
            )
        own: list[Element] = []
        vendor: list[Element] = []
        for module in modules:
            path = f"{module.path}/etc/db_schema.xml"
            if not (ctx.project_root / path).is_file():
                continue
            tables = [
                child
                for root in read_xml(ctx, path, self.name)
                for child in root.children
                if child.name == "table"
            ]
            (vendor if module.third_party else own).extend(tables)
        attributes, unresolved = collect_attributes(ctx, modules)
        for reason, detail, origin in unresolved:
            ctx.findings.append(
                Finding(
                    kind="unresolved",
                    subject=None,
                    reason=reason,
                    detail=detail,
                    citations=(_citation(ctx, origin),),
                )
            )
        wanted: dict[str, set[str]] = {}
        for attribute in attributes:
            repo = ctx.repository_of(attribute.origin.path).key
            wanted.setdefault(repo, set()).add(attribute.table)
        for table in own:
            repo = ctx.repository_of(table.span.path).key
            names = wanted.setdefault(repo, set())
            if table.attributes.get("name"):
                names.add(table.attributes["name"])
            for child in table.children:
                if child.attributes.get("xsi:type") == "foreign":
                    target = child.attributes.get("referenceTable")
                    if target:
                        names.add(target)
        schemas = {repo: Schema(self.name, repo) for repo in sorted(wanted)}
        for table in vendor:
            repo = ctx.repository_of(table.span.path).key
            if table.attributes.get("name") in wanted.get(repo, set()):
                _apply(schemas[repo], table)
        for table in own:
            _apply(schemas[ctx.repository_of(table.span.path).key], table)
        for attribute in attributes:
            repo = ctx.repository_of(attribute.origin.path).key
            apply_attribute(schemas[repo], attribute)
        for repo, schema in schemas.items():
            for name, merged in list(schema.tables.items()):
                kept = []
                for constraint in merged.constraints:
                    if (
                        constraint.kind == "foreign"
                        and all(is_vendor(s.path) for s in constraint.spans)
                        and constraint.ref_table not in schema.tables
                    ):
                        ctx.findings.append(
                            Finding(
                                kind="external_reference",
                                subject=fact_type_id(repo, name),
                                reason="vendor_not_followed",
                                detail=(
                                    f"({', '.join(constraint.columns)}) -> "
                                    f"{constraint.ref_table}"
                                    f"({', '.join(constraint.ref_columns)})"
                                ),
                                citations=tuple(
                                    _citation(ctx, s) for s in constraint.spans
                                ),
                            )
                        )
                    else:
                        kept.append(constraint)
                schema.tables[name] = merged.model_copy(
                    update={"constraints": tuple(kept)}
                )
            ctx.schemas.append(schema)


def third_party_findings(ctx: ReadContext, model: DomainModel) -> list[Finding]:
    """Mark translated elements by their own citations, not their parent table."""
    schemas = [s for s in ctx.schemas if s.reader == "magento_schema"]
    if not schemas:
        return []
    extended = {
        (ctx.repository_of(path).key, table.attributes.get("name"))
        for path in sorted(ctx.read_paths)
        if path.endswith("/etc/db_schema.xml") and not is_vendor(path)
        for root in read_xml(ctx, path, "magento_schema")
        for table in root.children
        if table.name == "table"
    }
    extended.update(
        (schema.repository, table.name)
        for schema in schemas
        for table in schema.tables.values()
        if any(
            column.target and column.target.startswith("eav:")
            for column in table.columns
        )
    )
    vendor_paths = {
        span.path
        for schema in schemas
        for table in schema.tables.values()
        for span in (table.origin or (table.defined_at,))
        if is_vendor(span.path)
    }
    details: dict[str, str | None] = {}
    findings = []
    for collection in COLLECTIONS:
        for element in getattr(model, collection):
            if not element.citations or not all(
                c.path in vendor_paths for c in element.citations
            ):
                continue
            packages = []
            for citation in element.citations:
                root = citation.path.split("/etc/", 1)[0]
                if root not in details:
                    details[root] = package_detail(ctx, root)
                detail = details[root]
                if detail:
                    packages.append(detail)
            table = next(
                (
                    t
                    for s in schemas
                    for t in s.tables.values()
                    if any(c.path == t.defined_at.path for c in element.citations)
                    and t.defined_at.start_line
                    <= element.citations[0].start_line
                    <= t.defined_at.end_line
                ),
                None,
            )
            repo = element.citations[0].repository
            findings.append(
                Finding(
                    kind="third_party",
                    subject=element.id,
                    reason="vendor_table_extended"
                    if table and (repo, table.name) in extended
                    else "vendor_table_referenced",
                    detail="; ".join(sorted(set(packages))) or None,
                    citations=element.citations,
                )
            )
    return findings
