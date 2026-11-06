"""Versioned, renderer-independent C4 output and per-scope cache contracts."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 5

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
    technology: str = ""
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
    # Prompt, schema and validator of the step; empty in older entries.
    version: str = ""
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
    drop: list[str] = Field(default_factory=list)
    merge: dict[str, str] = Field(default_factory=dict)
    keep_apart: list[tuple[str, str]] = Field(default_factory=list)


class LockedTransition(_C4BaseModel):
    input_fingerprint: str
    history: list[HistoryEdge]
    renames: bool


class ScopeLock(_C4BaseModel):
    base_sha: str
    system: str
    containers: dict[str, str]
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


def relations_off_the_map(
    elements: Sequence[Element], relations: Sequence[Relation]
) -> tuple[set[str], set[str]]:
    """Relations that stay in the pair but not on the map: (inside, redundant).

    Files in no component belong to their container, so their references become
    relations of that container. One with its own component runs inside it, and
    one whose target a component also reaches adds nothing to the container view.
    """
    parents = {
        element.id: element.parent
        for element in elements
        if element.kind == "component"
    }
    containers = {element.id for element in elements if element.kind == "container"}
    reached = {
        (parents[relation.from_id], relation.to_id)
        for relation in relations
        if relation.from_id in parents
    }
    inside = {
        relation.id
        for relation in relations
        if parents.get(relation.from_id) == relation.to_id
        or parents.get(relation.to_id) == relation.from_id
    }
    redundant = {
        relation.id
        for relation in relations
        if relation.from_id in containers
        and relation.status == "found"
        and relation.id not in inside
        and (relation.from_id, relation.to_id) in reached
    }
    return inside, redundant


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
