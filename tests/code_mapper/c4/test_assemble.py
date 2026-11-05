"""Assembly contracts: sources, static edges, coverage and referential integrity."""

from dataclasses import replace

from chunkhound.code_mapper.c4.assemble import (
    AssemblyInput,
    UnlinkedCounts,
    assemble,
    assemble_with_notes,
)
from chunkhound.code_mapper.c4.classify import Classification
from chunkhound.code_mapper.c4.documented import (
    DocElement,
    DocRelation,
    DocumentedOutcome,
    TopicSources,
)
from chunkhound.code_mapper.c4.grouping import Group
from chunkhound.code_mapper.c4.merge import ProposedComponent, relation_fingerprint
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
    *_, notes = assemble_with_notes(inp)
    unlinked = notes.unlinked

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
    _, relations, evidence, notes = assemble_with_notes(inp)
    unlinked = notes.unlinked

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
    elements, relations, evidence, notes = assemble_with_notes(inp)
    unlinked = notes.unlinked
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
        return assemble_with_notes(inp)[3].unlinked.ambiguous

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
    assert assemble_with_notes(system_and_component)[3].unlinked.ambiguous == 1


def test_drop_removes_element_relations_and_citations_but_keeps_references():
    baseline = assemble(assembly_input())
    inp = assembly_input()
    inp.documented.relations = [
        DocRelation("User", "stripe", "pays with", citation(line=8))
    ]
    inp.overrides = Overrides(drop=["external:stripe", "external:stripe"])
    elements, relations, evidence, notes = assemble_with_notes(inp)
    assert "external:stripe" not in {e.id for e in elements}
    assert "external:stripe" not in evidence.element_files
    removed = {
        "external:stripe",
        "component:a->external:stripe",
        "person:user->external:stripe",
    }
    assert removed.isdisjoint(r.id for r in relations)
    assert removed.isdisjoint(c.target for c in evidence.citations)
    reference = next(r for r in evidence.references if r.line == 2)
    assert reference.to == "package:stripe"
    assert reference.relation is None
    assert notes.ignored_overrides == ()
    assert notes.unlinked == UnlinkedCounts()
    assert next(r for r in relations if r.to_id == "storage:sqlite") == next(
        r for r in baseline[1] if r.to_id == "storage:sqlite"
    )


def test_merge_moves_sources_and_collapses_relations():
    inp = assembly_input()
    inp.documented.elements.append(
        DocElement("external", "Payments", citation(line=7), "Takes payments.")
    )
    inp.documented.relations = [
        DocRelation("A", "Payments", "pays via", citation(line=8))
    ]
    inp.references.references.append(
        Reference(
            relation=None,
            from_file="a.py",
            line=8,
            to="package:openai",
            kind="call",
            status="counts",
        )
    )
    inp.references.external_sites["openai"] = [("a.py", 8)]
    inp.classifications["openai"] = Classification(
        "external_system", ("external_system",) * 3, ("disputed",), False
    )
    fingerprint = relation_fingerprint(
        "component:a",
        "external:payments",
        [("import", "package:stripe"), ("call", "package:openai")],
    )
    inp.titles[fingerprint] = "charges cards"
    inp.overrides = Overrides(
        merge={
            "external:stripe": "external:payments",
            "external:openai": "external:payments",
        },
        names={"external:stripe": "Ignored"},
    )
    before = assemble(replace(inp, overrides=Overrides()))
    elements, relations, evidence, notes = assemble_with_notes(inp)
    assert {e.id for e in elements if e.kind == "external"} == {"external:payments"}
    target = next(e for e in elements if e.id == "external:payments")
    assert (target.name, target.description, target.status, target.markers) == (
        "Payments",
        "Takes payments.",
        "found",
        ["disputed"],
    )
    relation = next(r for r in relations if r.to_id == target.id)
    assert (
        relation.id,
        relation.status,
        relation.reference_counts,
        relation.markers,
        relation.title,
    ) == (
        "component:a->external:payments",
        "found",
        {"import": 1, "call": 1},
        ["disputed"],
        "charges cards",
    )
    assert citation("a.py", 2, "code", target.id) in evidence.citations
    assert (
        citation("pyproject.toml", 9, "configuration", target.id) in evidence.citations
    )
    assert citation(line=8, target=relation.id) in evidence.citations
    for line, package in [(2, "package:stripe"), (8, "package:openai")]:
        ref = next(r for r in evidence.references if r.line == line)
        assert (ref.to, ref.relation) == (package, relation.id)
    assert {"external:stripe", "external:openai"}.isdisjoint(evidence.element_files)
    assert notes.ignored_overrides == ()
    assert next(r for r in relations if r.to_id == "storage:sqlite") == next(
        r for r in before[1] if r.to_id == "storage:sqlite"
    )
    # Reassembly is pure and fingerprints use original package targets.
    assert assemble_with_notes(inp) == (elements, relations, evidence, notes)
    assert inp.references.references[-1].relation is None
    assert inp.overrides.merge["external:stripe"] == target.id
    inp.titles[relation.id] = "id title wins"
    assert (
        next(r for r in assemble(inp)[1] if r.id == relation.id).title
        == "id title wins"
    )
    inp.overrides.titles[relation.id] = "manual title wins"
    assert (
        next(r for r in assemble(inp)[1] if r.id == relation.id).title
        == "manual title wins"
    )

    inp = assembly_input()
    inp.documented.elements.append(
        DocElement("external", "Stripe API", citation(line=7))
    )
    inp.documented.relations = [
        DocRelation("User", "Stripe API", "pays with", citation(line=8)),
        DocRelation("Stripe API", "stripe", "wraps", citation(line=9)),
    ]
    inp.overrides = Overrides(merge={"external:stripe-api": "external:stripe"})
    elements, relations, evidence, _ = assemble_with_notes(inp)
    relation = next(r for r in relations if r.from_id == "person:user")
    assert (relation.id, relation.title, relation.status) == (
        "person:user->external:stripe",
        "pays with",
        "documented",
    )
    assert "external:stripe->external:stripe" not in {r.id for r in relations}
    assert all(
        c.target != "external:stripe->external:stripe" for c in evidence.citations
    )
    assert citation(line=9) not in evidence.citations
    assert all(c.file != "README.md" or c.start_line != 9 for c in evidence.citations)
    assert next(e for e in elements if e.id == "external:stripe").name == "stripe"

    inp = assembly_input()
    inp.documented.elements.append(DocElement("person", "Users", citation(line=7)))
    inp.documented.relations = [
        DocRelation("User", "App", "uses", citation(line=5)),
        DocRelation("Users", "App", "works in", citation(line=6)),
    ]
    inp.overrides = Overrides(merge={"person:users": "person:user"})
    elements, relations, evidence, _ = assemble_with_notes(inp)
    person_relations = [r for r in relations if r.from_id == "person:user"]
    assert [(r.id, r.title) for r in person_relations] == [
        ("person:user->container:app", "uses")
    ]
    assert all(
        citation(line=n, target=person_relations[0].id) in evidence.citations
        for n in (5, 6)
    )
    assert "person:users" not in {e.id for e in elements}


def test_curation_ignores_invalid_entries_with_a_reason():
    inp = assembly_input()
    inp.documented.elements.extend(
        [
            DocElement("external", "Payments", citation(line=7)),
            DocElement("external", "Billing", citation(line=8)),
        ]
    )
    cases = [
        (
            Overrides(
                drop=["external:gone", "container:app"],
                merge={
                    "person:user": "external:stripe",
                    "external:stripe": "external:stripe",
                    "external:payments": "external:billing",
                    "external:billing": "external:stripe",
                },
            ),
            (
                "C4-overrides: drop ignored for container:app "
                "(not an external system or person)",
                "C4-overrides: drop ignored for external:gone (not on the map)",
                "C4-overrides: merge ignored for external:payments -> external:billing "
                "(target is merged itself)",
                "C4-overrides: merge ignored for external:stripe -> external:stripe "
                "(same element)",
                "C4-overrides: merge ignored for person:user -> external:stripe "
                "(different kinds)",
            ),
            {"external:stripe", "external:payments"},
        ),
        (
            Overrides(
                merge={
                    "external:payments": "external:billing",
                    "external:billing": "external:payments",
                }
            ),
            (
                "C4-overrides: merge ignored for external:billing -> external:payments "
                "(target is merged itself)",
                "C4-overrides: merge ignored for external:payments -> external:billing "
                "(target is merged itself)",
            ),
            {"external:stripe", "external:payments", "external:billing"},
        ),
        (
            Overrides(
                merge={
                    "external:payments": "external:stripe",
                    "external:billing": "external:gone",
                }
            ),
            (
                "C4-overrides: merge ignored for external:billing -> external:gone "
                "(not on the map)",
            ),
            {"external:stripe", "external:billing"},
        ),
        (
            Overrides(
                drop=["external:stripe"], merge={"external:payments": "external:stripe"}
            ),
            (
                "C4-overrides: merge ignored for external:payments -> external:stripe "
                "(dropped)",
            ),
            {"external:payments", "external:billing"},
        ),
        (
            Overrides(
                drop=["external:gone", "external:gone"],
                merge={
                    "external:gone": "container:app",
                    "container:app": "external:gone",
                    "external:stripe": "container:app",
                    "external:payments": "external:stripe",
                },
            ),
            (
                "C4-overrides: drop ignored for external:gone (not on the map)",
                "C4-overrides: merge ignored for container:app -> external:gone "
                "(not on the map)",
                "C4-overrides: merge ignored for external:gone -> container:app "
                "(not on the map)",
                "C4-overrides: merge ignored for external:stripe -> container:app "
                "(not an external system or person)",
            ),
            {"external:stripe", "external:billing"},
        ),
    ]
    for overrides, ignored, external_ids in cases:
        result = assemble_with_notes(replace(inp, overrides=overrides))
        assert result[3].ignored_overrides == ignored
        assert {e.id for e in result[0] if e.kind == "external"} == external_ids
        reversed_overrides = overrides.model_copy(
            update={
                "drop": list(reversed(overrides.drop)),
                "merge": dict(reversed(list(overrides.merge.items()))),
            }
        )
        assert assemble_with_notes(replace(inp, overrides=reversed_overrides)) == result
