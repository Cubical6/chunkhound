"""Read only the neutral model adjacent to the selected Code Mapper index."""

import json
import posixpath
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from chunkhound.autodoc.architecture.model import (
    C4Model,
    CoveredElement,
    Element,
    ElementKind,
    MergedLabel,
    Relation,
    Repository,
    SoftwareSystem,
    Source,
    SourceKind,
    Status,
    TopicCoverage,
)

_Warning = Callable[[str], None]
_E = TypeVar("_E", bound=Enum)
# The producer's contract version; version 1 used Dutch statuses.
_SCHEMA_VERSION = 2


class _InvalidModelError(ValueError):
    """An expected producer document shape or value error."""


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _InvalidModelError("expected a JSON object")
    return value


def _records(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list):
        raise _InvalidModelError(f"{key}: expected an array")
    return [_object(item) for item in value]


def _text(data: dict[str, Any], key: str, *, default: str | None = None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise _InvalidModelError(f"{key}: expected text")
    return value


def _optional_text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise _InvalidModelError(f"{key}: expected text or null")
    return value


def _strings(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise _InvalidModelError(f"{key}: expected an array of text")
    return value


def _enum(enum: type[_E], data: dict[str, Any], key: str) -> _E:
    value = _text(data, key)
    try:
        return enum(value)
    except ValueError as exc:
        raise _InvalidModelError(f"{key}: unknown value {value!r}") from exc


def _line(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if type(value) is not int or value < 1:
        raise _InvalidModelError(f"{key}: expected a positive line number")
    return value


def _files(data: dict[str, Any]) -> list[str]:
    return sorted({posixpath.normpath(path) for path in _strings(data, "files")})


def _unique_ids(records: list[Any], label: str) -> set[str]:
    ids: set[str] = set()
    for record in records:
        if not record.id or record.id in ids:
            raise _InvalidModelError(f"{label}: empty or duplicate id {record.id!r}")
        ids.add(record.id)
    return ids


class ModelLoader:
    @staticmethod
    def load(
        *, index_path: Path, log_warning: _Warning | None = None
    ) -> C4Model | None:
        suffix = "_code_mapper_index.md"
        if not index_path.name.endswith(suffix):
            # Retain support for the existing legacy index selector, without
            # looking for a different scope or inferring one from its heading.
            suffix = "_autodoc_index.md"
        if not index_path.name.endswith(suffix):
            if log_warning:
                log_warning(
                    f"Cannot select C4 model for {index_path}: unknown index name. "
                    "Re-run map to regenerate its index and adjacent C4 model."
                )
            return None
        model_path = index_path.with_name(
            index_path.name.removesuffix(suffix) + "_c4_model.json"
        )

        def warn(message: str) -> None:
            if log_warning:
                log_warning(f"C4 model {model_path}: {message}")

        try:
            document = json.loads(model_path.read_text(encoding="utf-8"))
            return _read_model(_object(document), warn)
        except (OSError, UnicodeError, json.JSONDecodeError, _InvalidModelError) as exc:
            warn(
                f"{exc}. Re-run map to regenerate the version {_SCHEMA_VERSION} C4 "
                "model beside the selected index; continuing without architecture."
            )
            return None


def _read_model(data: dict[str, Any], warn: _Warning) -> C4Model:
    version = data.get("schema_version")
    if type(version) is not int or version != _SCHEMA_VERSION:
        raise _InvalidModelError(
            f"unsupported schema_version (expected {_SCHEMA_VERSION})"
        )
    raw_system = _object(data.get("system"))
    system = SoftwareSystem(
        id=_text(raw_system, "id"),
        name=_text(raw_system, "name"),
        description=_text(raw_system, "description"),
    )
    if not system.id:
        raise _InvalidModelError("system: empty id")
    repositories = [
        Repository(
            id=_text(row, "id"),
            path=posixpath.normpath(_text(row, "path")),
            remote_url=_optional_text(row, "remote_url"),
            commit=_text(row, "commit"),
        )
        for row in _records(data, "repositories")
    ]
    repository_ids = _unique_ids(repositories, "repositories")
    sources = _read_sources(data, repository_ids, warn)
    source_ids = {source.id for source in sources}
    elements = _read_elements(data, system.id, source_ids, warn)
    element_ids = {system.id, *(element.id for element in elements)}
    relations = _read_relations(data, element_ids, source_ids, warn)
    return C4Model(
        schema_version=_SCHEMA_VERSION,
        system=system,
        repositories=repositories,
        elements=elements,
        relations=relations,
        sources=sources,
        merged_labels=_read_labels(data, element_ids, relations, warn),
        topics=_read_topics(data, element_ids, warn),
    )


def _read_sources(
    data: dict[str, Any], repository_ids: set[str], warn: _Warning
) -> list[Source]:
    sources = [
        Source(
            id=_text(row, "id"),
            repository_id=_text(row, "repository"),
            path=_text(row, "path"),
            start_line=_line(row, "start_line"),
            end_line=_line(row, "end_line"),
            kind=_enum(SourceKind, row, "kind"),
        )
        for row in _records(data, "sources")
    ]
    _unique_ids(sources, "sources")
    kept = []
    for source in sources:
        if source.repository_id not in repository_ids:
            warn(
                f"Skipping source {source.id}: unknown repository "
                f"{source.repository_id}."
            )
        elif source.end_line < source.start_line:
            warn(f"Skipping source {source.id}: reversed line range.")
        else:
            kept.append(source)
    return kept


def _evidence(row: dict[str, Any], source_ids: set[str], warn: _Warning) -> list[str]:
    ids = _strings(row, "sources")
    for source_id in ids:
        if source_id not in source_ids:
            warn(f"{row.get('id')}: unknown source {source_id}; ignoring reference.")
    return list(dict.fromkeys(sid for sid in ids if sid in source_ids))


def _read_elements(
    data: dict[str, Any], system_id: str, source_ids: set[str], warn: _Warning
) -> list[Element]:
    elements = [
        Element(
            id=_text(row, "id"),
            kind=_enum(ElementKind, row, "kind"),
            parent_id=_optional_text(row, "parent"),
            name=_text(row, "name"),
            description=_text(row, "description", default=""),
            technology=_text(row, "technology"),
            status=_enum(Status, row, "status"),
            files=_files(row),
            source_ids=_evidence(row, source_ids, warn),
        )
        for row in _records(data, "elements")
    ]
    all_ids = _unique_ids(elements, "elements")
    if system_id in all_ids:
        raise _InvalidModelError("system id is also an element id")
    # Resolve the two internal levels in order, so removing a container also
    # removes its components regardless of producer record order.
    containers = {
        element.id
        for element in elements
        if element.kind == ElementKind.CONTAINER
        and element.parent_id == system_id
        and element.source_ids
    }
    kept = []
    for element in elements:
        if not _parent_valid(element, system_id, containers):
            warn(
                f"Skipping element {element.id}: unknown or invalid parent "
                f"{element.parent_id}."
            )
        elif not element.source_ids:
            warn(f"Skipping element {element.id}: no surviving sources.")
        else:
            kept.append(element)
    return kept


def _parent_valid(element: Element, system_id: str, containers: set[str]) -> bool:
    if element.kind == ElementKind.CONTAINER:
        return element.parent_id == system_id
    if element.kind == ElementKind.COMPONENT:
        return element.parent_id in containers
    return element.parent_id is None


def _read_relations(
    data: dict[str, Any],
    element_ids: set[str],
    source_ids: set[str],
    warn: _Warning,
) -> list[Relation]:
    relations = [
        Relation(
            id=_text(row, "id"),
            source_id=_text(row, "source"),
            target_id=_text(row, "target"),
            title=_text(row, "title"),
            technology=_text(row, "technology"),
            status=_enum(Status, row, "status"),
            source_ids=_evidence(row, source_ids, warn),
        )
        for row in _records(data, "relations")
    ]
    _unique_ids(relations, "relations")
    kept = []
    for relation in relations:
        if not {relation.source_id, relation.target_id} <= element_ids:
            warn(
                f"Skipping relation {relation.id}: unknown endpoint "
                f"{relation.source_id} -> {relation.target_id}."
            )
        elif not relation.source_ids:
            warn(f"Skipping relation {relation.id}: no surviving sources.")
        else:
            kept.append(relation)
    return kept


def _read_labels(
    data: dict[str, Any],
    element_ids: set[str],
    relations: list[Relation],
    warn: _Warning,
) -> list[MergedLabel]:
    relation_by_id = {relation.id: relation for relation in relations}
    labels = []
    rows = data.get("merged_labels")
    if not isinstance(rows, list):
        raise _InvalidModelError("merged_labels: expected an array")
    for value in rows:
        try:
            row = _object(value)
            label = MergedLabel(
                source_id=_text(row, "source"),
                target_id=_text(row, "target"),
                relation_ids=_strings(row, "relations"),
                label=_text(row, "label"),
            )
        except _InvalidModelError as exc:
            warn(f"Skipping unusable merged label: {exc}.")
            continue
        if _label_usable(label, element_ids, relation_by_id):
            labels.append(label)
        else:
            warn(
                f"Skipping unusable merged label {label.source_id} -> "
                f"{label.target_id}, relations {label.relation_ids}."
            )
    return labels


def _label_usable(
    label: MergedLabel, element_ids: set[str], relations: dict[str, Relation]
) -> bool:
    if not {label.source_id, label.target_id} <= element_ids:
        return False
    if not set(label.relation_ids) <= relations.keys():
        return False
    if len({relations[rid].title for rid in label.relation_ids}) < 2:
        return False
    return (
        bool(label.label.strip())
        and len(label.label) <= 60
        and "[...]" not in label.label
    )


def _read_topics(
    data: dict[str, Any], element_ids: set[str], warn: _Warning
) -> list[TopicCoverage]:
    topics = []
    for row in _records(data, "topics"):
        covers = []
        for cover in _records(row, "covers"):
            element_id = _text(cover, "element")
            files = _files(cover)
            if element_id not in element_ids:
                warn(f"Skipping topic cover: unknown element {element_id}.")
            else:
                covers.append(CoveredElement(element_id=element_id, files=files))
        topics.append(TopicCoverage(file=_text(row, "file"), covers=covers))
    return topics
