"""Versioned CogNIAM domain knowledge contract."""

from collections.abc import Mapping
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

Status: TypeAlias = Literal["extracted", "proposed", "confirmed"]
EntryPoint: TypeAlias = Literal["cli", "mcp"]
HumanOp: TypeAlias = Literal["put", "confirm", "unconfirm", "delete"]
GroundValue: TypeAlias = str | int | float | bool | None


class _DomainBaseModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Citation(_DomainBaseModel):
    repository: str
    path: str
    # Line ranges are checked by the loader to report invalid_line_range.
    start_line: int
    end_line: int
    commit: str = Field(pattern=r"^[0-9a-fA-F]{7,40}$")


class CodeBinding(_DomainBaseModel):
    repository: str
    target: str
    citation: Citation


class HumanSource(_DomainBaseModel):
    record: int
    op: HumanOp
    put_status: Literal["proposed", "confirmed"] | None
    author_name: str
    author_email: str | None
    entry_point: EntryPoint
    recorded_at: str


class _Element(_DomainBaseModel):
    id: str
    repository: str
    status: Status
    citations: tuple[Citation, ...]
    human_sources: tuple[HumanSource, ...]

    @property
    def is_realized(self) -> bool:
        return bool(self.citations)


class Concept(_Element):
    term: str
    plural: str | None
    definition: str | None
    synonyms: tuple[str, ...]


class FactType(_Element):
    name: str
    templates: tuple[str, ...] = Field(min_length=1)
    roles: tuple[str, ...]
    identifies: str | None
    bindings: tuple[CodeBinding, ...]


class Role(_Element):
    fact_type: str
    name: str
    concept: str | None
    datatype: str | None
    mandatory: bool | None
    bindings: tuple[CodeBinding, ...]


class ValidationRule(_Element):
    fact_type: str
    rule_kind: Literal["uniqueness", "subset", "value", "other"]
    roles: tuple[str, ...]
    superset_fact_type: str | None
    superset_roles: tuple[str, ...]
    allowed_values: tuple[str, ...]
    name: str | None
    statement: str | None


class DerivationRule(_Element):
    name: str
    statement: str
    derives: tuple[str, ...]
    uses: tuple[str, ...]


class ExchangeRule(_Element):
    name: str
    statement: str
    operations: tuple[Literal["add", "change", "remove"], ...] = Field(min_length=1)
    fact_types: tuple[str, ...]


class EventRule(_Element):
    name: str
    statement: str
    event: str
    starts: tuple[str, ...]


class GroundFact(_Element):
    fact_type: str
    values: Mapping[str, GroundValue]
    violates: tuple[str, ...]


class DomainModel(_DomainBaseModel):
    schema_version: Literal[1]
    concepts: tuple[Concept, ...]
    fact_types: tuple[FactType, ...]
    roles: tuple[Role, ...]
    validation_rules: tuple[ValidationRule, ...]
    derivation_rules: tuple[DerivationRule, ...]
    exchange_rules: tuple[ExchangeRule, ...]
    event_rules: tuple[EventRule, ...]
    ground_facts: tuple[GroundFact, ...]
