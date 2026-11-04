"""Assembly contracts: sources, static edges, coverage and referential integrity."""

from dataclasses import replace

from chunkhound.code_mapper.c4.assemble import (
    AssemblyInput,
    UnlinkedCounts,
    assemble,
    assemble_with_unlinked,
)
from chunkhound.code_mapper.c4.classify import Classification
from chunkhound.code_mapper.c4.documented import (
    DocElement,
    DocRelation,
    DocumentedOutcome,
    TopicSources,
)
from chunkhound.code_mapper.c4.grouping import Group
from chunkhound.code_mapper.c4.merge import ProposedComponent
from chunkhound.code_mapper.c4.model import Citation, Overrides, Reference
from chunkhound.code_mapper.c4.references import ReferenceScan
from chunkhound.code_mapper.c4.runtime import (
    DependencyDecl,
    RuntimeScan,
    RuntimeUnit,
    StorageCandidate,
)
from chunkhound.code_mapper.c4.topic_coverage import compute_coverage


def citation(file="README.md", line=3, source="documentation", target=None):
    return Citation(
        target=target,
        file=file,
        start_line=line,
        end_line=line,
        source=source,
        verified=True,
    )


def assembly_input():
    container = RuntimeUnit(
        "container:app",
        "App",
        "pyproject.toml",
        ".",
        False,
        (),
        (citation("pyproject.toml", 2, "configuration", "container:app"),),
    )
    groups = [
        Group("a", container.id, "A", ".", ("a.py",)),
        Group("b", container.id, "B", ".", ("b.py",)),
        Group("direct", container.id, "Direct", ".", ("shared.py",)),
    ]
    refs = [
        Reference(
            relation=None,
            from_file="a.py",
            line=line,
            to=target,
            kind=kind,
            status=status,
        )
        for line, target, kind, status in [
            (2, "package:stripe", "import", "counts"),
            (3, "package:sqlite", "import", "counts"),
            (4, "package:helper", "import", "counts"),
            (5, "b.py", "import", "type_only"),
            (6, "a.py", "call", "counts"),
            (7, "b.py", "import", "unused"),
        ]
    ]
    runtime = RuntimeScan(
        "system:app",
        "App",
        [container],
        [],
        [StorageCandidate("DB_PATH", "config.py", 8, "DB_PATH: Path")],
        [DependencyDecl("stripe", "pyproject.toml", 9)],
        {"a.py": container.id, "b.py": container.id, "shared.py": container.id},
    )
    components = {
        key: (ProposedComponent(key, key.upper(), None, (key,), ()), "component:" + key)
        for key in ("a", "b")
    }
    documented = DocumentedOutcome(
        [
            DocElement("component", "A", citation()),
            DocElement("person", "User", citation()),
            DocElement("container", "Dashboard", citation()),
        ],
        [],
        {},
        False,
    )
    return AssemblyInput(
        runtime,
        ReferenceScan(
            refs,
            frozenset({"b.py"}),
            {"stripe": [("a.py", 2)], "sqlite": [("a.py", 3)]},
        ),
        groups,
        components,
        {container.id: ["direct"]},
        {
            "stripe": Classification(
                "external_system", ("external_system",) * 3, (), False
            ),
            "sqlite": Classification(
                "storage_driver", ("storage_driver",) * 3, ("disputed",), False
            ),
            "DB_PATH": Classification("yes", ("yes",) * 3, (), False),
        },
        documented,
        {},
        Overrides(),
    )


def test_status_follows_sources():
    elements, relations, evidence = assemble(assembly_input())
    by_id = {e.id: e for e in elements}
    assert by_id["component:a"].status == "found"
    assert by_id["person:user"].status == "documented"
    assert by_id["container:dashboard"].coverage.status == "none"
    assert by_id["component:b"].markers == ["imports_only"]
    assert "external:helper" not in by_id
    assert by_id["storage:sqlite"].markers == ["disputed"]
    assert (
        citation("pyproject.toml", 2, "configuration", "container:app")
        in evidence.citations
    )
    assert citation("a.py", 2, "code", "external:stripe") in evidence.citations
    assert (
        citation("config.py", 8, "configuration", "storage:db-path")
        in evidence.citations
    )
    assert {r.id for r in relations} == {
        "component:a->external:stripe",
        "component:a->storage:sqlite",
    }
    assert [r.relation for r in evidence.references][2:] == [None] * 4
    assert evidence.element_files["component:a"] == ["a.py"]
    assert evidence.element_files["container:app"] == ["a.py", "b.py", "shared.py"]
    ids = set(by_id) | {r.id for r in relations}
    assert all(c.target is None or c.target in ids for c in evidence.citations)
    assert all(r.relation is None or r.relation in ids for r in evidence.references)
    assert set(evidence.element_files) <= set(by_id)
    assert all(e.parent is None or e.parent in by_id for e in elements)


def test_documentation_relation_rules():
    inp = assembly_input()
    inp.documented.elements.append(DocElement("container", "App", citation()))
    inp.documented.relations = [
        DocRelation("A", "B", "feeds", citation()),
        DocRelation("User", "App", "uses", citation()),
        DocRelation("Unknown", "App", "uses", citation(line=5)),
    ]
    _, relations, evidence = assemble(inp)
    assert "component:a->component:b" not in {r.id for r in relations}
    assert (
        next(r for r in relations if r.from_id == "person:user").status == "documented"
    )
    assert len([c for c in evidence.citations if not c.verified]) == 2
    inp.references.references.append(
        Reference(
            relation=None,
            from_file="a.py",
            line=12,
            to="b.py",
            kind="call",
            status="counts",
        )
    )
    _, relations, evidence = assemble(inp)
    relation = next(r for r in relations if r.id == "component:a->component:b")
    assert relation.status == "found"
    assert relation.reference_counts == {"call": 1}
    assert citation(target=relation.id) in evidence.citations


def test_ambiguous_untyped_documentation_endpoint_stays_off_map():
    inp = assembly_input()
    inp.documented.elements.append(DocElement("person", "Dashboard", citation()))
    inp.documented.relations = [DocRelation("User", "Dashboard", "uses", citation())]
    _, relations, evidence = assemble(inp)
    assert not any(r.from_id == "person:user" for r in relations)
    assert citation().model_copy(update={"verified": False}) in evidence.citations


def test_relations_collapse_and_overrides_win():
    inp = assembly_input()
    inp.references.references.extend(
        Reference(
            relation=None,
            from_file="a.py",
            line=n,
            to="b.py",
            kind=kind,
            status="counts",
        )
        for n, kind in [(12, "import"), (13, "call"), (14, "call")]
    )
    inp = replace(
        inp,
        overrides=Overrides(
            names={"component:a": "Orders"},
            descriptions={"component:a": "Handles orders"},
            titles={"component:a->component:b": "verwerkt"},
        ),
    )
    elements, relations, evidence = assemble(inp)
    a = next(e for e in elements if e.id == "component:a")
    assert (a.name, a.description) == ("Orders", "Handles orders")
    relation = next(r for r in relations if r.id == "component:a->component:b")
    assert (relation.title, relation.reference_counts) == (
        "verwerkt",
        {"import": 1, "call": 2},
    )
    assert all(r.relation == relation.id for r in evidence.references if r.line >= 12)


def test_coverage_via_shared_cited_files():
    _, _, evidence = assemble(assembly_input())
    files = evidence.element_files
    assert files["container:app"] == ["a.py", "b.py", "shared.py"]
    assert files["system:app"] == ["a.py", "b.py"]
    direct = {"container:app": ["shared.py"]}
    topics = [
        TopicSources("shared", ("shared.py",)),
        TopicSources("a", ("a.py",)),
        TopicSources("both", ("a.py", "shared.py", "a.py")),
    ]
    result = compute_coverage(element_files=files, direct_files=direct, topics=topics)
    assert result["component:b"].status == "undescribed"
    assert result["component:a"].topics == ["a", "both"]
    assert result["container:app"].topics == ["both", "a", "shared"]
    assert result["system:app"].topics == ["a", "both"]
    assert result["container:dashboard"].status == "none"
    direct_only = compute_coverage(
        element_files=files, direct_files=direct, topics=[topics[0]]
    )
    assert {
        id for id, coverage in direct_only.items() if coverage.status == "covered"
    } == {"container:app"}
    trial = compute_coverage(element_files=files, direct_files=direct, topics=None)
    assert trial["component:a"].status == "not_computed"
    assert trial["container:dashboard"].status == "none"


def test_unlinked_documented_relations_are_counted_by_reason():
    inp = assembly_input()
    # Same term as the documented container: the endpoint becomes ambiguous.
    inp.documented.elements.append(DocElement("person", "Dashboard", citation(line=4)))
    inp.documented.relations = [
        DocRelation("Unknown", "User", "uses", citation(line=5)),
        DocRelation("User", "Dashboard", "uses", citation(line=6)),
        DocRelation("A", "B", "feeds", citation(line=7)),
    ]
    elements, relations, evidence = assemble(inp)
    *_, unlinked = assemble_with_unlinked(inp)

    assert unlinked == UnlinkedCounts(no_match=1, ambiguous=1, not_allowed=1)
    kept = [
        c
        for c in evidence.citations
        if c.start_line in {5, 6, 7} and c.file == "README.md"
    ]
    assert len(kept) == 3
    assert all(c.target is None and not c.verified for c in kept)
    # Counting changes nothing about what is linked.
    assert (elements, relations, evidence) == assemble(inp)


def test_documented_relation_with_shared_name_links_to_container():
    # The fixture's system and its only container are both called "App".
    inp = assembly_input()
    inp.documented.relations = [
        DocRelation("User", "App", "uses", citation(line=5)),
        DocRelation("App", "User", "notifies", citation(line=6)),
    ]
    _, relations, evidence, unlinked = assemble_with_unlinked(inp)

    assert unlinked == UnlinkedCounts()
    assert {"person:user->container:app", "container:app->person:user"} <= {
        r.id for r in relations
    }
    assert {c.target for c in evidence.citations if c.start_line in {5, 6}} >= {
        "person:user->container:app",
        "container:app->person:user",
    }


def test_documented_own_name_joins_that_element_and_links_its_relations():
    inp = assembly_input()
    inp.runtime = replace(
        inp.runtime,
        storage=[StorageCandidate("Duckdb", "compose.yaml", 2, "DUCKDB=1")],
    )
    inp.classifications["Duckdb"] = Classification("yes", ("yes",), (), False)
    inp.documented.elements = [
        DocElement("external", "APP", citation(line=7)),
        DocElement("component", "App", citation(line=8)),
        DocElement("external", "DuckDB", citation(line=9)),
        DocElement("external", "Stripe", citation(line=10)),
        # A person may carry a name of the system, so this one stays.
        DocElement("person", "App", citation(line=11)),
    ]
    inp.documented.relations = [
        DocRelation("APP", "Stripe", "betaalt via", citation(line=12))
    ]
    elements, relations, evidence, unlinked = assemble_with_unlinked(inp)
    ids = {element.id for element in elements}
    assert {"external:app", "component:app", "external:duckdb"}.isdisjoint(ids)
    assert {"person:app", "external:stripe"} <= ids
    assert "container:app->external:stripe" in {relation.id for relation in relations}
    assert unlinked.ambiguous == 0
    assert citation(line=7, target="container:app") in evidence.citations
    assert citation(line=9, target="storage:duckdb") in evidence.citations


def test_document_gives_a_description_and_a_package_its_display_name():
    inp = assembly_input()
    inp.references.external_sites["openai"] = [("a.py", 1)]
    inp.classifications["openai"] = Classification("external_system", (), (), False)
    inp.documented.elements = [
        DocElement("external", "OpenAI", citation(line=7), "Levert taalmodellen."),
        DocElement("external", "OPENAI", citation(line=8), "Andere zin."),
        DocElement("person", "Beheerder", citation(line=9), "Beheert de app."),
    ]
    elements = {element.id: element for element in assemble(inp)[0]}
    assert elements["external:openai"].name == "OpenAI"
    assert elements["external:openai"].description == "Levert taalmodellen."
    assert elements["person:beheerder"].description == "Beheert de app."

    inp.overrides = Overrides(
        names={"external:openai": "Eigen naam"},
        descriptions={"external:openai": "Eigen zin."},
    )
    elements = {element.id: element for element in assemble(inp)[0]}
    assert elements["external:openai"].name == "Eigen naam"
    assert elements["external:openai"].description == "Eigen zin."


def test_other_shared_names_stay_ambiguous():
    def ambiguous_count(*extra_units: RuntimeUnit) -> int:
        inp = assembly_input()
        inp.runtime = replace(
            inp.runtime, containers=[*inp.runtime.containers, *extra_units]
        )
        inp.documented.relations = [DocRelation("User", "App", "uses", citation())]
        return assemble_with_unlinked(inp)[3].ambiguous

    second_container = RuntimeUnit(
        "container:app-2", "App", "web/package.json", "web", False, (), ()
    )
    storage = RuntimeUnit("storage:app", "App", "", ".", True, (), ())
    assert ambiguous_count() == 0
    assert ambiguous_count(second_container) == 1
    assert ambiguous_count(storage) == 1

    system_and_component = assembly_input()
    system_and_component.runtime = replace(
        system_and_component.runtime, system_name="B"
    )
    system_and_component.documented.relations = [
        DocRelation("User", "B", "uses", citation())
    ]
    assert assemble_with_unlinked(system_and_component)[3].ambiguous == 1
