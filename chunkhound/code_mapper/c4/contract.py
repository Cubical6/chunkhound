"""Translate the internal C4 pair into the neutral contract AutoDoc reads.

AutoDoc's loader is the source of truth for this shape. Anything the loader would
warn about is left out here and counted, so the contract loads without a warning;
the internal pair stays complete.

`build_contract` is a pure translation. Reading Git happens around it: which repository
holds a path is its input (`repository_lookup`), and commits and remote URLs are filled
in on its result (`with_git_data`).
"""

import hashlib
import json
import os
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeAlias

from chunkhound.code_mapper.c4.documented import TopicSources
from chunkhound.code_mapper.c4.model import (
    C4Evidence,
    C4Model,
    Citation,
    Element,
    ElementKind,
    Relation,
    SourceKind,
    Status,
)
from chunkhound.code_mapper.orchestrator import _get_head_sha
from chunkhound.utils.git_safe import GitCommandError, run_git

CONTRACT_VERSION = 1
NO_GIT_HEAD = "NO_GIT_HEAD"
ROOT_REPOSITORY = "."
_MAX_LABEL_LENGTH = 60

ContractElementKind: TypeAlias = Literal[
    "container", "component", "person", "externalSystem"
]
ContractStatus: TypeAlias = Literal["aangetroffen", "gedocumenteerd"]
ContractSourceKind: TypeAlias = Literal["code", "config", "doc"]

_ELEMENT_KINDS: dict[ElementKind, ContractElementKind] = {
    "container": "container",
    "storage": "container",
    "component": "component",
    "external": "externalSystem",
    "person": "person",
}
_STATUSES: dict[Status, ContractStatus] = {
    "found": "aangetroffen",
    "documented": "gedocumenteerd",
}
# A "topic" citation has no contract kind, so it never becomes a source.
_SOURCE_KINDS: dict[SourceKind, ContractSourceKind] = {
    "code": "code",
    "configuration": "config",
    "documentation": "doc",
}


@dataclass(frozen=True)
class ContractSystem:
    id: str
    name: str
    description: str


@dataclass(frozen=True)
class ContractRepository:
    id: str
    path: str
    remote_url: str | None
    commit: str


@dataclass(frozen=True)
class ContractElement:
    id: str
    kind: ContractElementKind
    parent: str | None
    name: str
    technology: str
    status: ContractStatus
    files: list[str]
    sources: list[str]
    description: str = ""


@dataclass(frozen=True)
class ContractRelation:
    id: str
    source: str
    target: str
    title: str
    technology: str
    status: ContractStatus
    sources: list[str]


@dataclass(frozen=True)
class ContractSource:
    id: str
    repository: str
    path: str
    start_line: int
    end_line: int
    kind: ContractSourceKind


@dataclass(frozen=True)
class ContractLabel:
    source: str
    target: str
    relations: list[str]
    label: str


@dataclass(frozen=True)
class ContractCover:
    element: str
    files: list[str]


@dataclass(frozen=True)
class ContractTopic:
    file: str
    covers: list[ContractCover]


@dataclass(frozen=True)
class Contract:
    system: ContractSystem
    repositories: list[ContractRepository]
    elements: list[ContractElement]
    relations: list[ContractRelation]
    sources: list[ContractSource]
    merged_labels: list[ContractLabel]
    topics: list[ContractTopic]
    schema_version: int = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        """The JSON document; an empty element description is left out."""
        document = asdict(self)
        for element in document["elements"]:
            if not element["description"]:
                del element["description"]
        return document


@dataclass(frozen=True)
class ContractCounts:
    """What was left out of the contract, and what it holds without a value."""

    components_without_container: int = 0
    elements_without_source: int = 0
    components_without_valid_container: int = 0
    relations_without_endpoint: int = 0
    relations_without_source: int = 0
    labels: int = 0
    without_technology: int = 0
    without_description: int = 0
    container_relations_without_protocol: int = 0


def _source_id(
    repository: str,
    path: str,
    start_line: int,
    end_line: int,
    kind: ContractSourceKind,
) -> str:
    canonical = json.dumps(
        [repository, path, start_line, end_line, kind],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "src:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _source(citation: Citation, repository: str) -> ContractSource | None:
    kind = _SOURCE_KINDS.get(citation.source)
    if kind is None:
        return None
    return ContractSource(
        id=_source_id(
            repository, citation.file, citation.start_line, citation.end_line, kind
        ),
        repository=repository,
        path=citation.file,
        start_line=citation.start_line,
        end_line=citation.end_line,
        kind=kind,
    )


def _sources_by_target(
    evidence: C4Evidence,
    system_id: str,
    repository_of: Callable[[str], str],
) -> dict[str, dict[str, ContractSource]]:
    """Verified citations per target; the system has no field for them."""
    by_target: dict[str, dict[str, ContractSource]] = defaultdict(dict)
    for citation in evidence.citations:
        if (
            not citation.verified
            or citation.target is None
            or citation.target == system_id
        ):
            continue
        source = _source(citation, repository_of(citation.file))
        if source is not None:
            by_target[citation.target][source.id] = source
    return by_target


def _direct_files(model: C4Model, evidence: C4Evidence) -> dict[str, list[str]]:
    """Files of an element itself: a container's list also holds its components'."""
    of_components: dict[str, set[str]] = defaultdict(set)
    for element in model.elements:
        if element.kind == "component" and element.parent is not None:
            of_components[element.parent].update(
                evidence.element_files.get(element.id, ())
            )
    return {
        element.id: sorted(
            set(evidence.element_files.get(element.id, ()))
            - (of_components[element.id] if element.kind == "container" else set())
        )
        for element in model.elements
    }


@dataclass(frozen=True)
class _KeptElements:
    elements: list[Element]
    without_container: int
    without_source: int
    without_valid_container: int


def _keep_elements(
    model: C4Model, sources: Mapping[str, Mapping[str, ContractSource]]
) -> _KeptElements:
    candidates = [element for element in model.elements if element.kind != "system"]
    containers = {element.id for element in candidates if element.kind == "container"}
    placed = [
        element
        for element in candidates
        if element.kind != "component" or element.parent in containers
    ]
    cited = [element for element in placed if sources.get(element.id)]
    surviving = {element.id for element in cited if element.kind == "container"}
    kept = [
        element
        for element in cited
        if element.kind != "component" or element.parent in surviving
    ]
    return _KeptElements(
        elements=sorted(kept, key=lambda element: element.id),
        without_container=len(candidates) - len(placed),
        without_source=len(placed) - len(cited),
        without_valid_container=len(cited) - len(kept),
    )


def _element(
    element: Element,
    system_id: str,
    files: list[str],
    sources: Iterable[str],
) -> ContractElement:
    kind = _ELEMENT_KINDS[element.kind]
    parent: str | None
    if kind == "container":
        parent = system_id
    elif kind == "component":
        parent = element.parent
    else:
        parent = None
    return ContractElement(
        id=element.id,
        kind=kind,
        parent=parent,
        name=element.name,
        description=element.description or "",
        technology=element.technology,
        status=_STATUSES[element.status],
        files=files,
        sources=sorted(sources),
    )


def _relation(relation: Relation, sources: Iterable[str]) -> ContractRelation:
    return ContractRelation(
        id=relation.id,
        source=relation.from_id,
        target=relation.to_id,
        title=relation.title,
        technology="",
        status=_STATUSES[relation.status],
        sources=sorted(sources),
    )


def _label_usable(label: str) -> bool:
    return (
        bool(label.strip()) and len(label) <= _MAX_LABEL_LENGTH and "[...]" not in label
    )


def _labels(
    model: C4Model, endpoints: set[str], kept_relations: set[str]
) -> tuple[list[ContractLabel], int]:
    """One label per endpoint pair and relation set, with the omissions counted.

    An arrow needs a label only over at least two distinct titles, so an arrow
    with one title is not an omission. The same text in several views is one.
    """
    titles = {relation.id: relation.title for relation in model.relations}
    needed: set[tuple[str, str, tuple[str, ...], str]] = set()
    chosen: dict[tuple[str, str, tuple[str, ...]], str] = {}
    for arrow in model.merged:
        relations = tuple(sorted(set(arrow.underlying)))
        if len({titles[id] for id in relations if id in titles}) < 2:
            continue
        key = (arrow.from_id, arrow.to_id, relations)
        needed.add((*key, arrow.label))
        if (
            {arrow.from_id, arrow.to_id} <= endpoints
            and kept_relations.issuperset(relations)
            and _label_usable(arrow.label)
        ):
            chosen[key] = min(chosen.get(key, arrow.label), arrow.label)
    labels = [
        ContractLabel(source, target, list(relations), label)
        for (source, target, relations), label in sorted(chosen.items())
    ]
    return labels, len(needed) - len(labels)


def _topics(
    topics: Sequence[TopicSources] | None, elements: Sequence[ContractElement]
) -> list[ContractTopic]:
    cited: dict[str, set[str]] = defaultdict(set)
    for topic in topics or ():
        cited[topic.topic].update(topic.files)
    result = []
    for file, files in sorted(cited.items()):
        shared = (
            (element.id, files.intersection(element.files)) for element in elements
        )
        result.append(
            ContractTopic(
                file,
                [
                    ContractCover(element, sorted(covered))
                    for element, covered in shared
                    if covered
                ],
            )
        )
    return result


def _repositories(
    sources: Iterable[ContractSource],
    elements: Iterable[ContractElement],
    repository_of: Callable[[str], str],
) -> list[ContractRepository]:
    ids = {ROOT_REPOSITORY, *(source.repository for source in sources)}
    ids.update(repository_of(file) for element in elements for file in element.files)
    return [
        ContractRepository(id=id, path=id, remote_url=None, commit=NO_GIT_HEAD)
        for id in sorted(ids)
    ]


def build_contract(
    model: C4Model,
    evidence: C4Evidence,
    topics: Sequence[TopicSources] | None,
    repository_of: Callable[[str], str],
) -> tuple[Contract, ContractCounts]:
    """Build the contract from one run's pair; `topics=None` means no research."""
    system_element = next(e for e in model.elements if e.kind == "system")
    system = ContractSystem(
        id=system_element.id,
        name=system_element.name,
        description=system_element.description or "",
    )
    sources = _sources_by_target(evidence, system.id, repository_of)
    direct_files = _direct_files(model, evidence)

    kept = _keep_elements(model, sources)
    elements = [
        _element(element, system.id, direct_files[element.id], sources[element.id])
        for element in kept.elements
    ]
    endpoints = {system.id, *(element.id for element in elements)}
    connected = [
        relation
        for relation in model.relations
        if {relation.from_id, relation.to_id} <= endpoints
    ]
    relations = [
        _relation(relation, sources[relation.id])
        for relation in sorted(connected, key=lambda relation: relation.id)
        if sources.get(relation.id)
    ]
    labels, omitted_labels = _labels(
        model, endpoints, {relation.id for relation in relations}
    )
    used = {
        id: source
        for owner in (*endpoints - {system.id}, *(r.id for r in relations))
        for id, source in sources[owner].items()
    }

    contract_containers = {e.id for e in elements if e.kind == "container"}
    counts = ContractCounts(
        components_without_container=kept.without_container,
        elements_without_source=kept.without_source,
        components_without_valid_container=kept.without_valid_container,
        relations_without_endpoint=len(model.relations) - len(connected),
        relations_without_source=len(connected) - len(relations),
        labels=omitted_labels,
        # C4 asks technology of containers and components only (spec §5).
        without_technology=sum(
            not element.technology
            for element in elements
            if element.kind in {"container", "component"}
        ),
        # The spec's §5 table asks a description of the system as well.
        without_description=sum(not element.description for element in elements)
        + (not system.description),
        container_relations_without_protocol=sum(
            not relation.technology
            and {relation.source, relation.target} <= contract_containers
            for relation in relations
        ),
    )
    return (
        Contract(
            system=system,
            repositories=_repositories(used.values(), elements, repository_of),
            elements=elements,
            relations=relations,
            sources=[used[id] for id in sorted(used)],
            merged_labels=labels,
            topics=_topics(topics, elements),
        ),
        counts,
    )


def repository_lookup(project_root: Path) -> Callable[[str], str]:
    """Map a path from the index root to the deepest repository on its route.

    Only directories on a path's own route are inspected, each one once.
    """
    known: dict[PurePosixPath, str] = {}

    def of_directory(directory: PurePosixPath) -> str:
        if directory == directory.parent:
            return ROOT_REPOSITORY
        if directory not in known:
            known[directory] = (
                directory.as_posix()
                if os.path.exists(project_root / directory / ".git")
                else of_directory(directory.parent)
            )
        return known[directory]

    return lambda path: of_directory(PurePosixPath(path).parent)


class _NoSourceLinksError(Exception):
    """A checked condition failed; the message is the reason in the report."""


def _git(args: Sequence[str], directory: Path) -> str:
    process = run_git(args, cwd=directory)
    if process.returncode != 0:
        raise GitCommandError(
            f"git {args[0]} mislukt", process.returncode, process.stderr
        )
    return process.stdout or ""


def _without_credentials(url: str) -> str:
    """Keep only what identifies the repository, for every remote notation.

    Split by hand: `urlsplit` ends the authority at a `?` or `#` in user information,
    which would leave part of a token behind as the host.
    """
    scheme, separator, rest = url.partition("://")
    if not separator:
        scheme, rest = "", url
    authority, slash, path = rest.partition("/")
    if not separator and ":" not in authority:
        return url  # A local path, not user@host:path.
    user, _, host = authority.rpartition("@")
    keep_user = user.partition(":")[0] == "git" and scheme.lower() in ("", "ssh")
    location = re.split("[?#]", f"{host}{slash}{path}", maxsplit=1)[0]
    return f"{scheme}{separator}{'git@' if keep_user else ''}{location}"


def _blocked_files(paths: Iterable[str], state: str) -> _NoSourceLinksError:
    ordered = sorted(paths)
    noun = "geciteerd bestand" if len(ordered) == 1 else "geciteerde bestanden"
    return _NoSourceLinksError(f"{len(ordered)} {noun} {state}, eerste: {ordered[0]}")


def _checked_remote_url(
    directory: Path, commit: str, run_head: str | None, cited: set[str]
) -> str:
    """The URL of `origin` if every link condition holds; `run_head` is only for `.`."""
    toplevel = _git(["rev-parse", "--show-toplevel"], directory).rstrip("\n")
    if Path(toplevel).resolve() != directory.resolve():
        raise _NoSourceLinksError(f"de wortel van deze repository is {toplevel}")
    if run_head is not None and _get_head_sha(directory) != run_head:
        raise _NoSourceLinksError("HEAD is tijdens de run veranderd")
    if commit == NO_GIT_HEAD:
        raise _NoSourceLinksError("de repository heeft geen commit")
    url = _git(["remote", "get-url", "origin"], directory).strip()
    contains = ["branch", "-r", "--contains", commit, "--list", "origin/*"]
    if not _git(contains, directory).strip():
        raise _NoSourceLinksError(f"commit {commit} staat niet op origin")
    untracked = cited - set(_git(["ls-files", "-z"], directory).split("\0"))
    if untracked:
        raise _blocked_files(untracked, "niet gevolgd")
    # Each entry is two status characters, a space and the path; never strip the
    # output, because a change in the worktree alone starts with a space.
    status = _git(["status", "--porcelain", "-z", "--no-renames"], directory)
    changed = cited.intersection(entry[3:] for entry in status.split("\0"))
    if changed:
        raise _blocked_files(changed, "gewijzigd")
    return _without_credentials(url)


def _with_git_row(
    row: ContractRepository, project_root: Path, head_sha: str, cited: set[str]
) -> tuple[ContractRepository, str | None]:
    directory = project_root / row.path
    is_root = row.id == ROOT_REPOSITORY
    commit = head_sha if is_root else _get_head_sha(directory)
    try:
        url = _checked_remote_url(
            directory, commit, head_sha if is_root else None, cited
        )
    except _NoSourceLinksError as blocked:
        return replace(row, commit=commit), str(blocked)
    except (GitCommandError, OSError, ValueError) as error:
        # Git's hints span several lines; a reason is one line of the report.
        return replace(row, commit=commit), " ".join(str(error).split())
    return replace(row, remote_url=url, commit=commit), None


def with_git_data(
    contract: Contract, project_root: Path, head_sha: str
) -> tuple[Contract, dict[str, str]]:
    """Fill each repository row from Git, locally, with why a row has no remote URL.

    `head_sha` is the HEAD this run started from. A Git failure is never fatal: it
    only costs that repository its source links.
    """
    cited: dict[str, set[str]] = defaultdict(set)
    for source in contract.sources:
        cited[source.repository].add(source.path.removeprefix(f"{source.repository}/"))
    rows = []
    reasons = {}
    for row in contract.repositories:
        filled, reason = _with_git_row(row, project_root, head_sha, cited[row.id])
        rows.append(filled)
        if reason is not None:
            reasons[row.id] = reason
    return replace(contract, repositories=rows), reasons
