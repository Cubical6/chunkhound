"""Assembly contracts: sources, static edges, coverage and referential integrity."""

from dataclasses import replace

from chunkhound.code_mapper.c4.assemble import AssemblyInput, assemble
from chunkhound.code_mapper.c4.classify import Classification
from chunkhound.code_mapper.c4.documented import (
    DocElement,
    DocRelation,
    DocumentedOutcome,
    TopicSources,
)
from chunkhound.code_mapper.c4.grouping import Group, GroupingResult
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
        "systeem:app",
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
        GroupingResult({}, groups, frozenset(), {}),
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
    assert by_id["persoon:user"].status == "documented"
    assert by_id["container:dashboard"].coverage.status == "none"
    assert by_id["component:b"].markers == ["imports_only"]
    assert "extern:helper" not in by_id
    assert by_id["opslag:sqlite"].markers == ["disputed"]
    assert (
        citation("pyproject.toml", 2, "configuration", "container:app")
        in evidence.citations
    )
    assert citation("a.py", 2, "code", "extern:stripe") in evidence.citations
    assert (
        citation("config.py", 8, "configuration", "opslag:db-path")
        in evidence.citations
    )
    assert {r.id for r in relations} == {
        "component:a->extern:stripe",
        "component:a->opslag:sqlite",
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
        next(r for r in relations if r.from_id == "persoon:user").status == "documented"
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
    inp.documented.relations = [DocRelation("User", "App", "uses", citation())]
    _, relations, evidence = assemble(inp)
    assert not any(r.from_id == "persoon:user" for r in relations)
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
    files = {
        "component:a": ["a.py"],
        "component:b": ["b.py"],
        "container:app": ["a.py", "b.py"],
        "systeem:app": ["a.py", "b.py", "shared.py"],
        "container:doc": [],
    }
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
    assert result["systeem:app"].topics == ["both", "a", "shared"]
    assert result["container:doc"].status == "none"
    trial = compute_coverage(element_files=files, direct_files=direct, topics=None)
    assert trial["component:a"].status == "not_computed"
    assert trial["container:doc"].status == "none"
