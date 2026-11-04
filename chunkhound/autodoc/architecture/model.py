"""Renderer-neutral producer contract; identities and classifications are supplied."""

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    FOUND = "found"
    DOCUMENTED = "documented"


class ElementKind(str, Enum):
    CONTAINER = "container"
    COMPONENT = "component"
    PERSON = "person"
    EXTERNAL_SYSTEM = "externalSystem"


class SourceKind(str, Enum):
    CODE = "code"
    CONFIG = "config"
    DOC = "doc"


@dataclass
class SoftwareSystem:
    id: str
    name: str
    description: str


@dataclass
class Element:
    id: str
    kind: ElementKind
    parent_id: str | None
    name: str
    description: str
    technology: str
    status: Status
    files: list[str]
    source_ids: list[str]


@dataclass
class Relation:
    id: str
    source_id: str
    target_id: str
    title: str
    technology: str
    status: Status
    source_ids: list[str]


@dataclass
class Source:
    id: str
    repository_id: str
    path: str
    start_line: int
    end_line: int
    kind: SourceKind


@dataclass
class Repository:
    id: str
    path: str
    remote_url: str | None
    commit: str


@dataclass
class MergedLabel:
    source_id: str
    target_id: str
    relation_ids: list[str]
    label: str


@dataclass
class CoveredElement:
    element_id: str
    files: list[str]


@dataclass
class TopicCoverage:
    file: str
    covers: list[CoveredElement]


@dataclass
class C4Model:
    schema_version: int
    system: SoftwareSystem
    repositories: list[Repository] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    merged_labels: list[MergedLabel] = field(default_factory=list)
    topics: list[TopicCoverage] = field(default_factory=list)
