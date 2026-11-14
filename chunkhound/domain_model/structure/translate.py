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
    TableClaims,
)
from chunkhound.domain_model.structure.technical import technical_matches


def concept_term(name: str, model_class: str | None = None) -> str:
    """Derive the concept term mechanically, shared by storage and API sources."""
    if not model_class:
        return name
    term = model_class.replace("\\", ".").split(".")[-1]
    term = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", term)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", term).replace("_", " ").lower()


def _check_tokens(statement: str | None) -> tuple[str, ...]:
    """Compare trivial SQL formatting without changing literals or identifiers."""
    # Open decision: DivergentClaim has no "statement" property (see plan Progress log).
    keywords = {
        "and",
        "or",
        "not",
        "in",
        "is",
        "null",
        "true",
        "false",
        "between",
        "like",
    }
    tokens = re.findall(
        r"'(?:''|\\.|[^'\\])*'|\"(?:\"\"|\\.|[^\"\\])*\"|`(?:``|\\.|[^`\\])*`|"
        r"[A-Za-z_][A-Za-z_0-9]*|\d+|>=|<=|<>|!=|\S",
        statement or "",
    )
    if len(tokens) >= 3 and tokens[0].upper() == "CONSTRAINT":
        tokens = tokens[2:]
    if tokens and tokens[0].upper() == "CHECK":
        tokens = tokens[1:]
    while len(tokens) >= 2 and tokens[0] == "(" and tokens[-1] == ")":
        depth = 0
        for index, token in enumerate(tokens):
            depth += (token == "(") - (token == ")")
            if depth == 0:
                break
        if index != len(tokens) - 1:
            break
        tokens = tokens[1:-1]
    return tuple(t.upper() if t.lower() in keywords else t for t in tokens)


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
    rank = {
        "sql": 0,
        "laravel": 1,
        "laravel_migrations": 1,
        "magento": 2,
        "magento_schema": 2,
        "prisma": 4,
        "typeorm": 5,
        "eloquent": 6,
        "graphql": 7,
    }
    lower: list[tuple[str, str, TableClaims]] = []
    table_readers: dict[tuple[str, str], str] = {}
    for schema in sorted(schemas, key=lambda s: rank.get(s.reader, 7)):
        lower.extend(
            (schema.repository, schema.reader, claim) for claim in schema.claims
        )
        for table_name, reason, span in schema.orphans:
            finding("uncertain", None, reason, table_name, (span,))
        for table in schema.tables.values():
            key = (schema.repository, table.name)
            if key in tables:
                lower.append(
                    (
                        schema.repository,
                        schema.reader,
                        TableClaims(
                            table=table.name,
                            span=table.defined_at,
                            columns=table.columns,
                            constraints=table.constraints,
                        ),
                    )
                )
                if schema.reader in {"magento", "magento_schema"}:
                    # EAV attributes supplement physical storage, regardless of rank.
                    for column in table.columns:
                        if not column.target or not column.target.startswith("eav:"):
                            continue
                        if column.name in columns[key]:
                            continue
                        try:
                            rid = identity.role_id(fact_ids[key], column.name)
                        except identity.EmptyKeyError:
                            rid = ""
                        if not rid or any(
                            identity.role_id(fact_ids[key], n) == rid
                            for n in columns[key]
                        ):
                            finding(
                                "unresolved",
                                fact_ids[key],
                                "key_collision",
                                column.name,
                                column.origin,
                            )
                            continue
                        columns[key][column.name] = column
                for reason, span in table.uncertain:
                    if reason != "entity_table_missing":
                        finding("uncertain", fact_ids[key], reason, None, (span,))
                continue
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
            table_readers[key] = schema.reader
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

    extra_constraints: dict[tuple[str, str], list[tuple[str, Constraint]]] = {}
    model_spans: dict[tuple[str, str], list[tuple[str, Span]]] = {}
    for repository, reader, claim in lower:
        key = (repository, claim.table)
        if key not in tables:
            finding(
                "unresolved",
                None,
                "model_table_unknown",
                claim.model_class or claim.table,
                (claim.span,),
            )
            continue
        table = tables[key]
        fid = fact_ids[key]
        if claim.model_class:
            model_spans.setdefault(key, []).append((claim.model_class, claim.span))
            if len(model_spans[key]) == 1:
                tables[key] = table.model_copy(
                    update={"model_class": claim.model_class}
                )
        primary = next((c for c in table.constraints if c.kind == "primary"), None)
        lower_primary = {
            name for c in claim.constraints if c.kind == "primary" for name in c.columns
        }
        for column in claim.columns:
            previous_column = columns[key].get(column.name)
            if previous_column is None:
                finding(
                    "uncertain",
                    fid,
                    "column_only_in_lower_source",
                    column.name,
                    column.origin,
                )
                continue
            mandatory = (
                True
                if primary and column.name in primary.columns
                else previous_column.mandatory
            )
            lower_mandatory = True if column.name in lower_primary else column.mandatory
            if lower_mandatory is None:
                continue
            if mandatory != lower_mandatory:
                claims.append(
                    DivergentClaim(
                        subject=identity.role_id(fid, column.name),
                        property="mandatory",
                        value=lower_mandatory,
                        source=reader,
                        citation=citation(column.defined_at),
                    )
                )
            else:
                columns[key][column.name] = previous_column.model_copy(
                    update={
                        "origin": tuple(
                            dict.fromkeys((*previous_column.origin, *column.origin))
                        ),
                    }
                )
        for constraint in claim.constraints:
            missing = [name for name in constraint.columns if name not in columns[key]]
            if missing:
                for name in missing:
                    if not any(c.name == name for c in claim.columns):
                        finding(
                            "uncertain",
                            fid,
                            "column_only_in_lower_source",
                            name,
                            constraint.spans,
                        )
                continue
            # A lower primary key is only a uniqueness claim, not an identifier.
            extra_constraints.setdefault(key, []).append(
                (
                    reader,
                    constraint.model_copy(update={"kind": "unique"})
                    if constraint.kind == "primary"
                    else constraint,
                )
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
        term = concept_term(table.name, table.model_class)
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
                **common(
                    cid,
                    key[0],
                    (
                        *(table.origin or (table.defined_at,)),
                        *(s for _, s in model_spans.get(key, [])),
                    ),
                ),
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
        if any(reason == "entity_table_missing" for reason, _ in table.uncertain):
            identifying = None
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
                **common(
                    fid,
                    repository,
                    (
                        *(table.origin or (table.defined_at,)),
                        *(s for _, s in model_spans.get(key, [])),
                    ),
                ),
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
                )
                + tuple(
                    CodeBinding(
                        repository=repository, target=name, citation=citation(span)
                    )
                    for name, span in model_spans.get(key, [])
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
                            target=column.target or f"{table.name}.{name}",
                            citation=citation(column.defined_at),
                        ),
                    ),
                )
            )
        for reason, span in table.uncertain:
            finding("uncertain", fid, reason, None, (span,))
        for reader, constraint, is_lower in (
            *((table_readers[key], c, False) for c in constraints),
            *((r, c, True) for r, c in extra_constraints.get(key, [])),
        ):
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
            if is_lower and kind == "other":
                candidates = [
                    r
                    for r in rules.values()
                    if r.fact_type == fid
                    and r.rule_kind == "other"
                    and set(r.roles) == set(rule.roles)
                ]
                if candidates:
                    previous = next(
                        (
                            r
                            for r in candidates
                            if _check_tokens(r.statement)
                            == _check_tokens(rule.statement)
                        ),
                        None,
                    )
                    if previous is None:
                        continue
                    identifier = previous.id
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
                        source=reader,
                        citation=citation(constraint.spans[0]),
                    )
                )
            elif kind == "value" and set(previous.allowed_values) != set(
                rule.allowed_values
            ):
                claims.append(
                    DivergentClaim(
                        subject=identifier,
                        property="allowed_values",
                        value=rule.allowed_values,
                        source=reader,
                        citation=citation(constraint.spans[0]),
                    )
                )
            elif kind == "other" and not is_lower and previous.name != rule_name:
                finding("unresolved", fid, "key_collision", rule_name, constraint.spans)
            elif kind == "other" and _check_tokens(previous.statement) != _check_tokens(
                rule.statement
            ):
                continue
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
