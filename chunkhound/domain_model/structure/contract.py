"""Versioned, deterministic output of structural extraction."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chunkhound.domain_model.identity import key_segment
from chunkhound.domain_model.loader import COLLECTIONS, dump_model, parse_model
from chunkhound.domain_model.model import Citation, DomainModel

STRUCTURE_SCHEMA_VERSION = 1


class _StructureModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RepositoryRef(_StructureModel):
    key: str
    path: str
    commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    dirty: bool


class Handler(_StructureModel):
    symbol: str
    citation: Citation | None


class Hint(_StructureModel):
    kind: Literal["operation", "model", "input_type", "input_rule", "enum"]
    name: str | None
    value: str | None
    values: tuple[str, ...]
    fact_type: str | None
    role: str | None
    citation: Citation


class Anchor(_StructureModel):
    id: str
    repository: str
    kind: Literal["http", "graphql", "command", "action"]
    method: str | None
    path: str
    handler: Handler | None
    source: str
    citations: tuple[Citation, ...] = Field(min_length=1)
    hints: tuple[Hint, ...]


class Finding(_StructureModel):
    kind: Literal[
        "technical", "third_party", "uncertain", "unresolved", "external_reference"
    ]
    subject: str | None
    reason: str
    detail: str | None
    citations: tuple[Citation, ...] = Field(min_length=1)


class DivergentClaim(_StructureModel):
    subject: str
    property: Literal["mandatory", "allowed_values", "superset"]
    value: str | bool | tuple[str, ...]
    source: str
    citation: Citation


class StructureExtraction(_StructureModel):
    schema_version: Literal[1]
    repositories: tuple[RepositoryRef, ...]
    model: DomainModel
    anchors: tuple[Anchor, ...]
    findings: tuple[Finding, ...]
    divergent_claims: tuple[DivergentClaim, ...]


def anchor_id(repository: str, kind: str, method: str | None, path: str) -> str:
    identity = f"{method} {path}" if method else path
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
    return f"anchor:{repository}/{kind}/{key_segment(identity)}-{digest}"


def parse_structure(data: object) -> StructureExtraction:
    """Validate the domain model and all extraction-level references."""
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    extraction = StructureExtraction.model_validate(data)
    parse_model(extraction.model.model_dump(mode="json"))
    if any(
        getattr(extraction.model, collection)
        for collection in (
            "derivation_rules",
            "exchange_rules",
            "event_rules",
            "ground_facts",
        )
    ):
        raise ValueError("Structure extraction only contains storage model elements")
    ids = {
        element.id
        for collection in COLLECTIONS
        for element in getattr(extraction.model, collection)
    } | {anchor.id for anchor in extraction.anchors}
    references = [finding.subject for finding in extraction.findings]
    references.extend(claim.subject for claim in extraction.divergent_claims)
    for anchor in extraction.anchors:
        for hint in anchor.hints:
            references.extend((hint.fact_type, hint.role))
    for reference in references:
        if reference is not None and reference not in ids:
            raise ValueError(f"Unknown structure reference: {reference}")
    return extraction


def _citation_key(citation: Citation) -> tuple[str, str, int, int, str]:
    return (
        citation.repository,
        citation.path,
        citation.start_line,
        citation.end_line,
        citation.commit,
    )


def dump_structure(extraction: StructureExtraction) -> str:
    """Serialize in field order, with stable ordering of non-positional lists."""
    ordered = extraction.model_copy(
        update={
            "repositories": tuple(sorted(extraction.repositories, key=lambda x: x.key)),
            "anchors": tuple(sorted(extraction.anchors, key=lambda x: x.id)),
            "findings": tuple(
                sorted(
                    extraction.findings,
                    key=lambda x: (
                        x.kind,
                        x.subject or "",
                        x.reason,
                        x.detail or "",
                        _citation_key(x.citations[0]),
                    ),
                )
            ),
            "divergent_claims": tuple(
                sorted(
                    extraction.divergent_claims,
                    key=lambda x: (
                        x.subject,
                        x.property,
                        x.source,
                        _citation_key(x.citation),
                    ),
                )
            ),
        }
    )
    data = ordered.model_dump(mode="json")
    data["model"] = json.loads(dump_model(extraction.model))
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
