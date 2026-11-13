"""Mechanical storage-schema translation to the version-one domain contract."""

import hashlib
import re
from collections.abc import Callable
from typing import Any, Literal

from chunkhound.core.config.domain_config import DomainConfig
from chunkhound.domain_model import identity
from chunkhound.domain_model.model import (
    Citation,
    CodeBinding,
    Concept,
    DomainModel,
    FactType,
    Role,
    ValidationRule,
)
from chunkhound.domain_model.structure.contract import (
    DivergentClaim,
    Finding,
    RepositoryRef,
)
from chunkhound.domain_model.structure.schema import (
    Column,
    Constraint,
    Schema,
    Span,
    Table,
)
from chunkhound.domain_model.structure.technical import technical_matches


def translate(
    schemas: list[Schema],
    repository_of: Callable[[str], RepositoryRef],
    config: DomainConfig | None = None,
) -> tuple[DomainModel, list[Finding], list[DivergentClaim]]:
    """Resolve all tables before following references; never synthesize targets."""
    findings: list[Finding] = []
    claims: list[DivergentClaim] = []
    concepts: list[Concept] = []
    facts: list[FactType] = []
    roles: list[Role] = []
    rules: dict[str, ValidationRule] = {}

    def citation(span: Span) -> Citation:
        repo = repository_of(span.path)
        return Citation(
            repository=repo.key,
            path=span.path,
            start_line=span.start_line,
            end_line=span.end_line,
            commit=repo.commit,
        )

    def citations(spans: tuple[Span, ...]) -> tuple[Citation, ...]:
        return tuple(dict.fromkeys(citation(span) for span in spans))

    def common(
        identifier: str, repository: str, spans: tuple[Span, ...]
    ) -> dict[str, Any]:
        return dict(
            id=identifier,
            repository=repository,
            status="extracted",
            citations=citations(spans),
            human_sources=(),
        )

    def finding(
        kind: Literal["unresolved", "uncertain", "external_reference", "technical"],
        subject: str | None,
        reason: str,
        detail: str | None,
        spans: tuple[Span, ...],
    ) -> None:
        findings.append(
            Finding(
                kind=kind,
                subject=subject,
                reason=reason,
                detail=detail,
                citations=citations(spans),
            )
        )

    # Dict insertion order preserves reader/source order, including collision winners.
    tables: dict[tuple[str, str], Table] = {}
    fact_ids: dict[tuple[str, str], str] = {}
    columns: dict[tuple[str, str], dict[str, Column]] = {}
    seen_facts: set[str] = set()
    for schema in schemas:
        for table_name, reason, span in schema.orphans:
            finding("uncertain", None, reason, table_name, (span,))
        for table in schema.tables.values():
            key = (schema.repository, table.name)
            try:
                fid = identity.fact_type_id(schema.repository, table.name)
            except identity.EmptyKeyError:
                fid = ""
            if not fid or fid in seen_facts:
                finding(
                    "unresolved", None, "key_collision", table.name, (table.defined_at,)
                )
                continue
            seen_facts.add(fid)
            kept: dict[str, Column] = {}
            seen_roles: set[str] = set()
            for column in table.columns:
                try:
                    rid = identity.role_id(fid, column.name)
                except identity.EmptyKeyError:
                    rid = ""
                if not rid or rid in seen_roles:
                    finding(
                        "unresolved",
                        None,
                        "key_collision",
                        f"{table.name}.{column.name}",
                        column.origin,
                    )
                    continue
                kept[column.name] = column
                seen_roles.add(rid)
            # A CREATE with no retained columns has no fact type to mark.
            if not kept:
                for reason, span in table.uncertain:
                    finding("uncertain", None, reason, table.name, (span,))
                continue
            tables[key] = table
            columns[key] = kept
            fact_ids[key] = fid
            for reason, list_name in technical_matches(
                table.name,
                schema.reader,
                table.defined_at.path,
                (config or DomainConfig()).technical_tables,
            ):
                finding("technical", fid, reason, list_name, (table.defined_at,))

    def valid_constraints(key: tuple[str, str]) -> tuple[Constraint, ...]:
        return tuple(
            c
            for c in tables[key].constraints
            if all(name in columns[key] for name in c.columns)
        )

    concept_ids: dict[tuple[str, str], str] = {}
    seen_concepts: set[str] = set()
    for key, table in tables.items():
        constraints = valid_constraints(key)
        primary = next((c for c in constraints if c.kind == "primary"), None)
        foreign = {
            name for c in constraints if c.kind == "foreign" for name in c.columns
        }
        if primary is None or not set(primary.columns) - foreign:
            continue
        term = table.name
        if table.model_class:
            term = table.model_class.replace("\\", ".").split(".")[-1]
            term = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", term)
            term = (
                re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", term).replace("_", " ").lower()
            )
        try:
            cid = identity.concept_id(key[0], term)
        except identity.EmptyKeyError:
            cid = ""
        if not cid or cid in seen_concepts:
            finding(
                "unresolved", fact_ids[key], "key_collision", term, (table.defined_at,)
            )
            continue
        concept_ids[key] = cid
        seen_concepts.add(cid)
        concepts.append(
            Concept(
                **common(cid, key[0], table.origin or (table.defined_at,)),
                term=term,
                plural=None,
                definition=None,
                synonyms=(),
            )
        )

    for key, table in tables.items():
        repository = key[0]
        fid = fact_ids[key]
        constraints = valid_constraints(key)
        primary = next((c for c in constraints if c.kind == "primary"), None)
        uniques = [c for c in constraints if c.kind == "unique" and c.columns]
        identifying = primary or (
            min(uniques, key=lambda c: len(c.columns)) if uniques else None
        )
        keys = identifying.columns if identifying else ()
        ordered_names = (*keys, *(n for n in columns[key] if n not in keys))
        prefix = (
            f"{table.name}({', '.join(f'<{n}>' for n in keys)})" if keys else table.name
        )
        templates = ([prefix] if keys else []) + [
            f"{prefix} has {n} <{n}>" for n in ordered_names if n not in keys
        ]
        facts.append(
            FactType(
                **common(fid, repository, table.origin or (table.defined_at,)),
                name=table.name,
                templates=tuple(templates),
                roles=tuple(identity.role_id(fid, n) for n in ordered_names),
                identifies=concept_ids.get(key),
                bindings=(
                    CodeBinding(
                        repository=repository,
                        target=table.name,
                        citation=citation((table.origin or (table.defined_at,))[-1]),
                    ),
                ),
            )
        )
        for name in ordered_names:
            column = columns[key][name]
            concept = (
                concept_ids.get(key) if primary and primary.columns == (name,) else None
            )
            if concept is None:
                foreign_key = next(
                    (
                        c
                        for c in constraints
                        if c.kind == "foreign" and c.columns == (name,)
                    ),
                    None,
                )
                if foreign_key:
                    concept = concept_ids.get((repository, foreign_key.ref_table or ""))
            roles.append(
                Role(
                    **common(identity.role_id(fid, name), repository, column.origin),
                    fact_type=fid,
                    name=name,
                    concept=concept,
                    datatype=column.datatype,
                    mandatory=True
                    if primary and name in primary.columns
                    else column.mandatory,
                    bindings=(
                        CodeBinding(
                            repository=repository,
                            target=f"{table.name}.{name}",
                            citation=citation(column.defined_at),
                        ),
                    ),
                )
            )
        for reason, span in table.uncertain:
            finding("uncertain", fid, reason, None, (span,))
        for constraint in constraints:
            kind: Literal["uniqueness", "subset", "value", "other"]
            rule_name = None
            target_fid = None
            target_roles: tuple[str, ...] = ()
            if constraint.kind in {"primary", "unique"}:
                kind = "uniqueness"
                if not constraint.columns:
                    continue
            elif constraint.kind == "foreign":
                kind = "subset"
                target_key = (repository, constraint.ref_table or "")
                target_fid = fact_ids.get(target_key)
                if target_fid is None:
                    detail = (
                        f"({', '.join(constraint.columns)}) -> {constraint.ref_table}"
                        f"({', '.join(constraint.ref_columns)})"
                    )
                    finding(
                        "external_reference",
                        fid,
                        "table_not_found",
                        detail,
                        constraint.spans,
                    )
                    continue
                ref_columns = constraint.ref_columns
                if not ref_columns:
                    target_primary = next(
                        (
                            c
                            for c in valid_constraints(target_key)
                            if c.kind == "primary"
                        ),
                        None,
                    )
                    ref_columns = target_primary.columns if target_primary else ()
                if (
                    not constraint.columns
                    or len(constraint.columns) != len(ref_columns)
                    or not all(n in columns[target_key] for n in ref_columns)
                ):
                    finding(
                        "uncertain",
                        fid,
                        "unparsed_statement",
                        constraint.ref_table,
                        constraint.spans,
                    )
                    continue
                target_roles = tuple(
                    identity.role_id(target_fid, n) for n in ref_columns
                )
            elif constraint.kind == "value":
                kind = "value"
                if len(constraint.columns) != 1:
                    continue
            else:
                kind = "other"
                rule_name = constraint.name or (
                    f"check-{constraint.columns[0]}"
                    if len(constraint.columns) == 1
                    else "check-"
                    + hashlib.sha256((constraint.statement or "").encode()).hexdigest()[
                        :8
                    ]
                )
            try:
                identifier = identity.validation_rule_id(
                    fid, kind, constraint.columns, name=rule_name
                )
            except identity.EmptyKeyError:
                finding("unresolved", fid, "key_collision", rule_name, constraint.spans)
                continue
            rule = ValidationRule(
                **common(identifier, repository, constraint.spans),
                fact_type=fid,
                rule_kind=kind,
                roles=tuple(identity.role_id(fid, n) for n in constraint.columns),
                superset_fact_type=target_fid,
                superset_roles=target_roles,
                allowed_values=constraint.allowed_values,
                name=rule_name,
                statement=constraint.statement,
            )
            previous = rules.get(identifier)
            if previous is None:
                rules[identifier] = rule
            elif kind == "subset" and (
                previous.superset_fact_type,
                previous.superset_roles,
            ) != (target_fid, target_roles):
                claims.append(
                    DivergentClaim(
                        subject=identifier,
                        property="superset",
                        value=(target_fid or "", *target_roles),
                        source=constraint.spans[0].reader,
                        citation=citation(constraint.spans[0]),
                    )
                )
            elif kind == "value" and previous.allowed_values != rule.allowed_values:
                claims.append(
                    DivergentClaim(
                        subject=identifier,
                        property="allowed_values",
                        value=rule.allowed_values,
                        source=constraint.spans[0].reader,
                        citation=citation(constraint.spans[0]),
                    )
                )
            elif kind == "other" and (previous.name, previous.statement) != (
                rule_name,
                rule.statement,
            ):
                finding("unresolved", fid, "key_collision", rule_name, constraint.spans)
            else:
                rules[identifier] = previous.model_copy(
                    update={
                        "citations": tuple(
                            dict.fromkeys((*previous.citations, *rule.citations))
                        )
                    }
                )
    return (
        DomainModel(
            schema_version=1,
            concepts=tuple(concepts),
            fact_types=tuple(facts),
            roles=tuple(roles),
            validation_rules=tuple(rules.values()),
            derivation_rules=(),
            exchange_rules=(),
            event_rules=(),
            ground_facts=(),
        ),
        findings,
        claims,
    )
