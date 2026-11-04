"""Assemble source-backed elements and one static relation per ordered pair."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from chunkhound.code_mapper.c4.classify import Classification
from chunkhound.code_mapper.c4.documented import DocumentedOutcome
from chunkhound.code_mapper.c4.grouping import Group
from chunkhound.code_mapper.c4.identity import element_id
from chunkhound.code_mapper.c4.merge import (
    ProposedComponent,
    fallback_title,
    relation_fingerprint,
)
from chunkhound.code_mapper.c4.model import (
    SCHEMA_VERSION,
    C4Evidence,
    Citation,
    Coverage,
    Element,
    ElementKind,
    Marker,
    Overrides,
    Reference,
    Relation,
    SourceKind,
)
from chunkhound.code_mapper.c4.references import ReferenceScan
from chunkhound.code_mapper.c4.runtime import RuntimeScan


@dataclass
class AssemblyInput:
    runtime: RuntimeScan
    references: ReferenceScan
    groups: list[Group]
    components: dict[str, tuple[ProposedComponent, str]]
    direct_groups: dict[str, list[str]]
    classifications: dict[str, Classification]
    documented: DocumentedOutcome
    titles: dict[str, str]
    overrides: Overrides
    fallback_containers: frozenset[str] = frozenset()


@dataclass(frozen=True)
class UnlinkedCounts:
    """Documented relations kept only as unverified citations, by reason."""

    no_match: int = 0
    ambiguous: int = 0
    not_allowed: int = 0


class _Assembly:
    def __init__(self, inp: AssemblyInput) -> None:
        self.inp = inp
        self.unlinked: Counter[str] = Counter()
        self.elements: dict[str, Element] = {}
        self.files: dict[str, list[str]] = {}
        self.owners: dict[str, str] = dict(inp.runtime.container_of)
        self.citations: list[Citation] = []
        self.packages: dict[str, str] = {}
        self.relations: dict[str, Relation] = {}
        self.doc_terms: dict[str, set[str]] = defaultdict(set)

    def element(
        self,
        id: str,
        kind: ElementKind,
        name: str,
        parent: str | None,
        *,
        markers: tuple[Marker, ...] = (),
    ) -> None:
        if id not in self.elements:
            self.elements[id] = Element(
                id=id,
                kind=kind,
                name=name,
                parent=parent,
                description=None,
                status="documented",
                markers=list(markers),
                coverage=Coverage(status="none", topics=[]),
            )
            self.files[id] = []

    def cite(self, target: str, file: str, line: int, source: SourceKind) -> None:
        self.citations.append(
            Citation(
                target=target,
                file=file,
                start_line=line,
                end_line=line,
                source=source,
                verified=True,
            )
        )

    def runtime(self) -> None:
        runtime = self.inp.runtime
        self.element(runtime.system_id, "system", runtime.system_name, None)
        for unit in runtime.containers:
            self.element(
                unit.id,
                "storage" if unit.storage else "container",
                unit.name,
                runtime.system_id,
                markers=unit.markers,
            )
            # On the element only: a marked unit would lose its locked container ID.
            markers = self.elements[unit.id].markers
            if unit.id in self.inp.fallback_containers and "fallback" not in markers:
                markers.append("fallback")
                markers.sort()
            for citation in unit.citations:
                self.citations.extend(
                    [
                        citation.model_copy(update={"target": unit.id}),
                        citation.model_copy(update={"target": runtime.system_id}),
                    ]
                )
        for candidate in runtime.storage:
            classification = self.inp.classifications.get(candidate.key)
            if classification is None or classification.value != "yes":
                continue
            id = element_id("storage", candidate.key)
            self.element(
                id,
                "storage",
                candidate.key,
                runtime.system_id,
                markers=classification.markers,
            )
            self.cite(id, candidate.file, candidate.line, "configuration")

    def components(self) -> None:
        groups = {group.id: group for group in self.inp.groups}
        for proposal, id in sorted(
            self.inp.components.values(), key=lambda pair: pair[1]
        ):
            members = [groups[key] for key in proposal.groups]
            parent = members[0].container
            self.element(
                id,
                "component",
                proposal.name,
                parent,
                markers=proposal.markers,
            )
            self.elements[id].description = proposal.description
            for group in members:
                for file in group.files:
                    self.owners[file] = id
                    self.files[id].append(file)
        for container, keys in self.inp.direct_groups.items():
            for key in keys:
                for file in groups[key].files:
                    self.owners[file] = container
        self.implementation_sources()

    def implementation_sources(self) -> None:
        implementation_files = {
            file for group in self.inp.groups for file in group.files
        }
        for file in sorted(implementation_files):
            owner = self.owners[file]
            if owner not in self.elements:
                continue
            current: str | None = owner
            while current is not None:
                self.files[current].append(file)
                # Implementation files are code sources even without imports.
                self.cite(current, file, 1, "code")
                # Direct container files do not contribute ancestor coverage.
                if self.elements[owner].kind != "component":
                    break
                current = self.elements[current].parent
            if file in self.inp.references.imports_only_files:
                element = self.elements[owner]
                if "imports_only" not in element.markers:
                    element.markers.append("imports_only")
                    element.markers.sort()

    def dependencies(self) -> None:
        names = set(self.inp.references.external_sites)
        names.update(decl.name for decl in self.inp.runtime.dependencies)
        for name in sorted(names):
            classified = self.inp.classifications.get(name)
            if classified is None or classified.value not in {
                "external_system",
                "storage_driver",
            }:
                continue
            kind: ElementKind = (
                "external" if classified.value == "external_system" else "storage"
            )
            id = element_id(kind, name)
            parent = self.inp.runtime.system_id if kind == "storage" else None
            self.element(id, kind, name, parent, markers=classified.markers)
            self.packages["package:" + name] = id
            for decl in self.inp.runtime.dependencies:
                if decl.name == name:
                    self.cite(id, decl.manifest, decl.line, "configuration")
            for file, line in self.inp.references.external_sites.get(name, ()):
                self.cite(id, file, line, "code")

    def static_relations(self) -> list[Reference]:
        references = []
        by_pair: dict[tuple[str, str], list[Reference]] = defaultdict(list)
        for original in self.inp.references.references:
            source = self.owners.get(original.from_file)
            target = self.packages.get(original.to) or self.owners.get(original.to)
            reference = original.model_copy(update={"relation": None})
            if (
                original.status == "counts"
                and source in self.elements
                and target in self.elements
                and source != target
            ):
                assert source is not None and target is not None
                reference.relation = f"{source}->{target}"
                by_pair[source, target].append(reference)
                self.cite(
                    reference.relation, reference.from_file, reference.line, "code"
                )
            references.append(reference)
        for (source, target), refs in sorted(by_pair.items()):
            id = f"{source}->{target}"
            fingerprint = relation_fingerprint(
                source, target, ((r.kind, r.to) for r in refs)
            )
            self.relations[id] = Relation.model_validate(
                {
                    "id": id,
                    "from": source,
                    "to": target,
                    "status": "found",
                    "title": self.inp.titles.get(
                        id,
                        self.inp.titles.get(
                            fingerprint, fallback_title(r.kind for r in refs)
                        ),
                    ),
                    "reference_counts": dict(Counter(r.kind for r in refs)),
                    "markers": sorted(
                        set(self.elements[source].markers)
                        | set(self.elements[target].markers)
                    ),
                }
            )
        return references

    def documented_elements(self) -> None:
        for item in self.inp.documented.elements:
            id = element_id(item.kind, item.term)
            # Match current names too: inherited component IDs may differ from names.
            matching = [
                e.id
                for e in self.elements.values()
                if e.kind == item.kind and e.name == item.term
            ]
            if len(matching) == 1:
                id = matching[0]
            parent = (
                self.inp.runtime.system_id
                if item.kind in {"container", "component"}
                else None
            )
            self.element(id, item.kind, item.term, parent)
            self.citations.append(item.citation.model_copy(update={"target": id}))
            self.doc_terms[item.term].add(id)

    def statuses(self) -> None:
        found = {
            c.target for c in self.citations if c.source in {"code", "configuration"}
        }
        for element in self.elements.values():
            element.status = "found" if element.id in found else "documented"

    def _relation_endpoint(self, ids: set[str]) -> set[str]:
        """A name shared by the system and one container means that container."""
        kinds = {id: self.elements[id].kind for id in ids}
        if sorted(kinds.values()) == ["container", "system"]:
            return {id for id, kind in kinds.items() if kind == "container"}
        return ids

    def documented_relations(self) -> None:
        terms: dict[str, set[str]] = defaultdict(set)
        for element in self.elements.values():
            terms[element.id].add(element.id)
            terms[element.name].add(element.id)
        terms.update(self.doc_terms)
        for item in self.inp.documented.relations:
            source_ids = self._relation_endpoint(terms[item.from_term])
            target_ids = self._relation_endpoint(terms[item.to_term])
            if len(source_ids) != 1 or len(target_ids) != 1:
                reason = "no_match" if not source_ids or not target_ids else "ambiguous"
                self.unlinked[reason] += 1
                self.citations.append(
                    item.citation.model_copy(update={"target": None, "verified": False})
                )
                continue
            source, target = next(iter(source_ids)), next(iter(target_ids))
            id = f"{source}->{target}"
            endpoints = [self.elements[source], self.elements[target]]
            allowed = source != target and (
                id in self.relations
                or any(
                    e.kind in {"person", "external"} or e.status == "documented"
                    for e in endpoints
                )
            )
            if not allowed:
                self.unlinked["not_allowed"] += 1
                self.citations.append(
                    item.citation.model_copy(update={"target": None, "verified": False})
                )
                continue
            if id not in self.relations:
                self.relations[id] = Relation.model_validate(
                    {
                        "id": id,
                        "from": source,
                        "to": target,
                        "title": item.title,
                        "status": "documented",
                        "reference_counts": {},
                        "markers": [],
                    }
                )
            self.citations.append(item.citation.model_copy(update={"target": id}))


def assemble(inp: AssemblyInput) -> tuple[list[Element], list[Relation], C4Evidence]:
    elements, relations, evidence, _ = assemble_with_unlinked(inp)
    return elements, relations, evidence


def assemble_with_unlinked(
    inp: AssemblyInput,
) -> tuple[list[Element], list[Relation], C4Evidence, UnlinkedCounts]:
    """Consume finalized retry outcomes; writer assigns the shared run ID later.

    element_files rolls component files up to their container/system; directly
    owned files stay with the container. Documentation is not file membership.
    """
    state = _Assembly(inp)
    state.runtime()
    state.components()
    state.dependencies()
    state.documented_elements()
    state.statuses()
    references = state.static_relations()
    state.documented_relations()
    for element in state.elements.values():
        element.name = inp.overrides.names.get(element.id, element.name)
        element.description = inp.overrides.descriptions.get(
            element.id, element.description
        )
        if state.files[element.id]:
            element.coverage = Coverage(status="not_computed", topics=[])
    for relation in state.relations.values():
        relation.title = inp.overrides.titles.get(relation.id, relation.title)
    citations = {tuple(c.model_dump().values()): c for c in state.citations}
    evidence = C4Evidence(
        schema_version=SCHEMA_VERSION,
        run_id="",
        references=references,
        citations=sorted(
            citations.values(),
            key=lambda c: (
                c.target or "",
                c.file,
                c.start_line,
                c.end_line,
                c.source,
                c.verified,
            ),
        ),
        element_files={
            id: sorted(set(files)) for id, files in sorted(state.files.items())
        },
    )
    return (
        [state.elements[id] for id in sorted(state.elements)],
        [state.relations[id] for id in sorted(state.relations)],
        evidence,
        UnlinkedCounts(
            no_match=state.unlinked["no_match"],
            ambiguous=state.unlinked["ambiguous"],
            not_allowed=state.unlinked["not_allowed"],
        ),
    )
