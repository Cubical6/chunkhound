"""Versioned, renderer-independent C4 output and per-scope cache contracts."""

from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 3

ElementKind: TypeAlias = Literal[
    "system", "container", "storage", "component", "external", "person"
]
Status: TypeAlias = Literal["found", "documented"]
ReferenceKind: TypeAlias = Literal["import", "call", "inherit"]
ReferenceStatus: TypeAlias = Literal["counts", "type_only", "unused"]
SourceKind: TypeAlias = Literal["code", "configuration", "documentation", "topic"]
HistoryKind: TypeAlias = Literal["continuation", "split", "merge", "new", "removed"]
RunKind: TypeAlias = Literal["full", "trial"]
Marker: TypeAlias = Literal[
    "fallback",
    "trial",
    "disputed",
    "undescribed",
    "imports_only",
    "provisional",
    "not_merged",
    "not_classified",
]
CoverageStatus: TypeAlias = Literal["covered", "undescribed", "not_computed", "none"]


class _C4BaseModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class RunInfo(_C4BaseModel):
    id: str
    kind: RunKind
    schema_version: int
    head_sha: str
    scope: str
    fallback_count: int
    # Documentation fragments that were not examined; 0 in files from older runs.
    fallback_fragments: int = 0
    renames: bool


class Coverage(_C4BaseModel):
    status: CoverageStatus
    topics: list[str]


class Element(_C4BaseModel):
    id: str
    kind: ElementKind
    name: str
    description: str | None
    status: Status
    parent: str | None
    markers: list[Marker]
    coverage: Coverage


class Relation(_C4BaseModel):
    id: str
    from_id: str = Field(alias="from")
    to_id: str = Field(alias="to")
    title: str
    status: Status
    reference_counts: dict[ReferenceKind, int]
    markers: list[Marker]


class MergedArrow(_C4BaseModel):
    id: str
    from_id: str = Field(alias="from")
    to_id: str = Field(alias="to")
    view: str
    label: str
    underlying: list[str]
    markers: list[Marker]


class HistoryEdge(_C4BaseModel):
    from_id: str
    to_id: str
    kind: HistoryKind


class C4Model(_C4BaseModel):
    run: RunInfo
    elements: list[Element]
    relations: list[Relation]
    merged: list[MergedArrow]
    history: list[HistoryEdge]


class Reference(_C4BaseModel):
    relation: str | None
    from_file: str = Field(alias="from")
    line: int
    to: str
    kind: ReferenceKind
    status: ReferenceStatus


class Citation(_C4BaseModel):
    target: str | None
    file: str
    start_line: int
    end_line: int
    source: SourceKind
    verified: bool


class C4Evidence(_C4BaseModel):
    schema_version: int
    run_id: str
    references: list[Reference]
    citations: list[Citation]
    element_files: dict[str, list[str]]


class LockedComponent(_C4BaseModel):
    name: str
    description: str | None
    container: str
    groups: list[str]
    files: list[str]


class LockedRelation(_C4BaseModel):
    title: str
    fingerprint: str


class LockedClassification(_C4BaseModel):
    value: str
    votes: list[str | None]
    markers: list[Marker]


class LockedDocumented(_C4BaseModel):
    hashes: dict[str, str]
    elements: list[dict[str, Any]]
    relations: list[dict[str, Any]]


class Overrides(_C4BaseModel):
    classifications: dict[str, str] = Field(default_factory=dict)
    placements: dict[str, str] = Field(default_factory=dict)
    names: dict[str, str] = Field(default_factory=dict)
    descriptions: dict[str, str] = Field(default_factory=dict)
    titles: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)


class LockedTransition(_C4BaseModel):
    input_fingerprint: str
    history: list[HistoryEdge]
    renames: bool


class ScopeLock(_C4BaseModel):
    base_sha: str
    system: str
    containers: dict[str, str]
    tree_spec: dict[str, dict[str, Any]]
    group_membership: dict[str, dict[str, str]]
    direct_groups: dict[str, list[str]]
    transition: LockedTransition | None
    components: dict[str, LockedComponent]
    tombstones: dict[str, str]
    relations: dict[str, LockedRelation]
    classifications: dict[str, LockedClassification]
    documented: LockedDocumented | None
    summaries: dict[str, str]
    overrides: Overrides


class MapLock(_C4BaseModel):
    version: int = SCHEMA_VERSION
    scopes: dict[str, ScopeLock]


class C4PairMismatchError(ValueError):
    """The model and evidence cannot safely be read as one run."""


def load_c4_pair(model_path: Path, evidence_path: Path) -> tuple[C4Model, C4Evidence]:
    """Validate both documents and reject a partially replaced output pair."""
    model = C4Model.model_validate_json(model_path.read_text(encoding="utf-8"))
    evidence = C4Evidence.model_validate_json(evidence_path.read_text(encoding="utf-8"))
    if model.run.id != evidence.run_id:
        raise C4PairMismatchError(
            "C4 model and evidence come from different runs; run `chunkhound map` again"
        )
    return model, evidence
