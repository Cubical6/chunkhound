"""Reader-independent anchor identities, merging, and translated hint links."""

import hashlib
from collections.abc import Iterable
from typing import Literal

from chunkhound.domain_model.identity import key_segment
from chunkhound.domain_model.model import Citation, DomainModel
from chunkhound.domain_model.structure.contract import Anchor, Hint
from chunkhound.domain_model.structure.schema import Schema


def anchor_id(repository: str, kind: str, method: str | None, path: str) -> str:
    entrance = f"{method} {path}" if method is not None else path
    digest = hashlib.sha256(entrance.encode("utf-8")).hexdigest()[:8]
    return f"anchor:{repository}/{kind}/{key_segment(entrance)}-{digest}"


def hint(
    kind: Literal["operation", "model", "input_type", "input_rule", "enum"],
    citation: Citation,
    *,
    name: str | None = None,
    value: str | None = None,
    values: tuple[str, ...] = (),
) -> Hint:
    return Hint(
        kind=kind,
        name=name,
        value=value,
        values=values,
        fact_type=None,
        role=None,
        citation=citation,
    )


def operation_hint(method: str | None, citation: Citation) -> tuple[Hint, ...]:
    operation = {
        "query": "read",
        "HEAD": "read",
        "GET": "read",
        "POST": "add",
        "PUT": "change",
        "PATCH": "change",
        "DELETE": "remove",
    }.get(method or "")
    return (hint("operation", citation, value=operation),) if operation else ()


def citation_key(citation: Citation) -> tuple[str, str, int, int, str]:
    return (
        citation.repository,
        citation.path,
        citation.start_line,
        citation.end_line,
        citation.commit,
    )


def finalize_anchors(
    anchors: Iterable[Anchor], schemas: Iterable[Schema], model: DomainModel
) -> tuple[Anchor, ...]:
    """Merge raw registrations before resolving model and unambiguous role hints."""
    facts = {(fact.repository, fact.name): fact.id for fact in model.fact_types}
    models: dict[tuple[str, str], str] = {}
    for schema in schemas:
        associations = [(t.name, t.model_class) for t in schema.tables.values()]
        associations.extend((c.table, c.model_class) for c in schema.claims)
        for table, model_class in associations:
            if model_class:
                fid = facts.get((schema.repository, table))
                if fid is not None:
                    models[schema.repository, model_class] = fid
    grouped: dict[str, list[Anchor]] = {}
    for anchor in anchors:
        aid = anchor_id(anchor.repository, anchor.kind, anchor.method, anchor.path)
        grouped.setdefault(aid, []).append(anchor)
    result = []
    for aid, registrations in sorted(grouped.items()):
        # A resolvable handler wins; ties do not depend on reader execution order.
        registrations.sort(
            key=lambda a: (
                a.handler is None or a.handler.citation is None,
                a.source,
                a.handler.symbol if a.handler else "",
                citation_key(a.citations[0]),
            )
        )
        first = registrations[0]
        hints = [
            h.model_copy(
                update={"fact_type": models.get((first.repository, h.name or ""))}
            )
            if h.kind == "model"
            else h
            for a in registrations
            for h in a.hints
        ]
        model_facts = {h.fact_type for h in hints if h.kind == "model" and h.fact_type}
        linked = []
        for h in hints:
            if h.kind == "input_rule":
                roles = {
                    r.id
                    for r in model.roles
                    if r.fact_type in model_facts and r.name == h.name
                }
                h = h.model_copy(
                    update={"role": next(iter(roles)) if len(roles) == 1 else None}
                )
            linked.append(h)
        citations = {c for a in registrations for c in a.citations}
        result.append(
            first.model_copy(
                update={
                    "id": aid,
                    "citations": tuple(sorted(citations, key=citation_key)),
                    "hints": tuple(
                        sorted(set(linked), key=lambda h: h.model_dump_json())
                    ),
                }
            )
        )
    return tuple(result)
