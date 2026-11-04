"""The neutral contract version 1 that AutoDoc reads from a map run."""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from chunkhound.autodoc.architecture.loader import ModelLoader
from chunkhound.autodoc.architecture.model import C4Model as LoadedModel
from chunkhound.code_mapper.c4.contract import Contract, build_contract
from chunkhound.code_mapper.c4.documented import TopicSources
from chunkhound.code_mapper.c4.model import C4Evidence, C4Model
from tests.code_mapper.c4.test_pipeline import (
    build,
    classify_answer,
    commit,
    merge_answer,
    payload,
)


def element(
    id: str,
    kind: str,
    parent: str | None = "system:app",
    *,
    description: str | None = "",
    technology: str = "",
    status: str = "found",
) -> dict[str, Any]:
    return {
        "id": id,
        "kind": kind,
        "name": id.split(":")[-1],
        "description": description,
        "technology": technology,
        "status": status,
        "parent": parent,
        "markers": ["fallback"],
        "coverage": {"status": "none", "topics": []},
    }


def relation(
    source: str, target: str, title: str = "uses", *, status: str = "found"
) -> dict[str, Any]:
    return {
        "id": f"{source}->{target}",
        "from": source,
        "to": target,
        "title": title,
        "status": status,
        "reference_counts": {},
        "markers": [],
    }


def arrow(
    source: str, target: str, underlying: list[str], label: str, *, view: str = "v"
) -> dict[str, Any]:
    return {
        "id": f"{view}:{source}->{target}",
        "from": source,
        "to": target,
        "view": view,
        "label": label,
        "underlying": underlying,
        "markers": [],
    }


def cite(
    target: str | None,
    file: str = "a.py",
    line: int = 1,
    *,
    source: str = "code",
    verified: bool = True,
) -> dict[str, Any]:
    return {
        "target": target,
        "file": file,
        "start_line": line,
        "end_line": line,
        "source": source,
        "verified": verified,
    }


SYSTEM = element("system:app", "system", None, description="The app.")


def pair(
    elements: Sequence[dict[str, Any]],
    relations: Sequence[dict[str, Any]] = (),
    merged: Sequence[dict[str, Any]] = (),
    citations: Sequence[dict[str, Any]] = (),
    files: dict[str, list[str]] | None = None,
) -> tuple[C4Model, C4Evidence]:
    model = C4Model.model_validate(
        {
            "run": {
                "id": "",
                "kind": "full",
                "schema_version": 4,
                "head_sha": "abc",
                "scope": "/",
                "fallback_count": 0,
                "renames": False,
            },
            "elements": [SYSTEM, *elements],
            "relations": list(relations),
            "merged": list(merged),
            "history": [],
        }
    )
    evidence = C4Evidence.model_validate(
        {
            "schema_version": 4,
            "run_id": "",
            "references": [],
            "citations": list(citations),
            "element_files": files or {},
        }
    )
    return model, evidence


def root_repository(_path: str) -> str:
    return "."


def load_quietly(contract: Contract, directory: Path) -> LoadedModel:
    """Read the contract the way AutoDoc does; any warning fails the contract."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "shop_c4_model.json").write_text(
        json.dumps(contract.to_dict()), encoding="utf-8"
    )
    warnings: list[str] = []
    loaded = ModelLoader.load(
        index_path=directory / "shop_code_mapper_index.md",
        log_warning=warnings.append,
    )
    assert warnings == []
    assert loaded is not None
    return loaded


@pytest.fixture
def contract_answers(scripted, monkeypatch):
    """Every internal relation gets its own title, so projections need labels."""
    monkeypatch.setenv("CHUNKHOUND_USE_RUST", "0")
    scripted.answers.update(
        {
            "classify": classify_answer,
            "merge": merge_answer,
            "titles": lambda prompt: {
                "titles": [
                    {"fingerprint": row["fingerprint"], "title": row["fingerprint"][:8]}
                    for row in payload(prompt)["relations"]
                ]
            },
            "summaries": lambda prompt: {
                "labels": [
                    {"key": row["key"], "label": "gebruikt diensten"}
                    for row in payload(prompt)["arrows"]
                ]
            },
        }
    )
    return scripted


async def test_contract_loads_without_warnings(
    fixture_repo, c4_llm_manager, contract_answers, tmp_path
):
    # A second component using the same external system gives a projected arrow
    # over two relations with different titles.
    (fixture_repo / "extra.py").write_text(
        'import requests\n\nrequests.get("https://example.invalid")\n',
        encoding="utf-8",
    )
    commit(fixture_repo, "Use requests from the root too")

    result = await build(
        fixture_repo,
        c4_llm_manager,
        topics=[
            TopicSources("shop_arch_topic_01_orders.md", ("shop/orders.py",)),
            TopicSources("shop_arch_topic_02_nothing.md", ("not/in/the/map.py",)),
        ],
    )

    assert result.contract is not None
    assert result.contract_counts is not None
    loaded = load_quietly(result.contract, tmp_path / "out")

    assert loaded.system.id == result.contract.system.id
    assert {e.id for e in loaded.elements} == {e.id for e in result.contract.elements}
    assert {e.kind.value for e in loaded.elements} >= {"container", "component"}
    assert len(loaded.relations) == len(result.contract.relations) > 0
    assert len(loaded.sources) == len(result.contract.sources) > 0
    assert len(loaded.merged_labels) == len(result.contract.merged_labels) > 0
    assert [(t.file, bool(t.covers)) for t in loaded.topics] == [
        ("shop_arch_topic_01_orders.md", True),
        ("shop_arch_topic_02_nothing.md", False),
    ]


async def test_trial_run_builds_no_contract(
    fixture_repo, c4_llm_manager, contract_answers
):
    result = await build(fixture_repo, c4_llm_manager, trial=True)

    assert result.contract is None
    assert result.contract_counts is None


def test_elements_and_relations_translate_to_contract_terms() -> None:
    model, evidence = pair(
        [
            element(
                "container:api",
                "container",
                description="Serves requests.",
                technology="Python",
            ),
            element(
                "component:orders",
                "component",
                "container:api",
                description="Handles orders.",
                technology="Python",
            ),
            element(
                "storage:db",
                "storage",
                description="",
                technology="DuckDB",
                status="documented",
            ),
            element("external:stripe", "external", None, description=None),
            element("person:admin", "person", None, status="documented"),
        ],
        [
            relation("component:orders", "storage:db", "writes"),
            relation("person:admin", "system:app", "uses", status="documented"),
        ],
        citations=[
            cite("system:app", "pyproject.toml"),
            cite("container:api", "pyproject.toml"),
            cite("component:orders", "shop/orders.py"),
            cite("storage:db", "compose.yaml", source="configuration"),
            cite("external:stripe", "shop/orders.py", 4),
            cite("person:admin", "README.md", 3, source="documentation"),
            cite("component:orders->storage:db", "shop/orders.py", 9),
            cite("person:admin->system:app", "README.md", 3, source="documentation"),
        ],
        files={
            "system:app": ["shop/orders.py"],
            "container:api": ["pyproject.toml", "shop/orders.py"],
            "component:orders": ["shop/orders.py"],
        },
    )

    document = build_contract(model, evidence, None, root_repository)[0].to_dict()

    assert document["schema_version"] == 1
    assert document["system"] == {
        "id": "system:app",
        "name": "app",
        "description": "The app.",
    }
    sources = {source["id"]: source for source in document["sources"]}
    elements = {row["id"]: row for row in document["elements"]}
    for row in elements.values():
        row["sources"] = [
            (sources[id]["path"], sources[id]["kind"]) for id in row.pop("sources")
        ]
    assert elements == {
        "container:api": {
            "id": "container:api",
            "kind": "container",
            "parent": "system:app",
            "name": "api",
            "description": "Serves requests.",
            "technology": "Python",
            "status": "aangetroffen",
            "files": ["pyproject.toml"],
            "sources": [("pyproject.toml", "code")],
        },
        "component:orders": {
            "id": "component:orders",
            "kind": "component",
            "parent": "container:api",
            "name": "orders",
            "description": "Handles orders.",
            "technology": "Python",
            "status": "aangetroffen",
            "files": ["shop/orders.py"],
            "sources": [("shop/orders.py", "code")],
        },
        "storage:db": {
            "id": "storage:db",
            "kind": "container",
            "parent": "system:app",
            "name": "db",
            "technology": "DuckDB",
            "status": "gedocumenteerd",
            "files": [],
            "sources": [("compose.yaml", "config")],
        },
        "external:stripe": {
            "id": "external:stripe",
            "kind": "externalSystem",
            "parent": None,
            "name": "stripe",
            "technology": "",
            "status": "aangetroffen",
            "files": [],
            "sources": [("shop/orders.py", "code")],
        },
        "person:admin": {
            "id": "person:admin",
            "kind": "person",
            "parent": None,
            "name": "admin",
            "technology": "",
            "status": "gedocumenteerd",
            "files": [],
            "sources": [("README.md", "doc")],
        },
    }
    relations = {row["id"]: row for row in document["relations"]}
    assert relations["component:orders->storage:db"]["source"] == "component:orders"
    assert relations["component:orders->storage:db"]["target"] == "storage:db"
    assert relations["component:orders->storage:db"]["title"] == "writes"
    assert relations["component:orders->storage:db"]["technology"] == ""
    assert relations["component:orders->storage:db"]["status"] == "aangetroffen"
    assert relations["person:admin->system:app"]["status"] == "gedocumenteerd"
    for rows in (document["elements"], document["relations"], document["sources"]):
        assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)


def test_source_ids_are_exact_stable_and_unique() -> None:
    def build_document(repository: str = "nested") -> dict[str, Any]:
        model, evidence = pair(
            [
                element("container:a", "container"),
                element("container:b", "container"),
            ],
            citations=[
                # One citation shared by two targets is one source.
                cite("container:a", "nested/é b.py", 2),
                cite("container:b", "nested/é b.py", 2),
                cite("container:a", "nested/é b.py", 2, source="documentation"),
                cite("container:a", "nested/é b.py", 3),
            ],
        )
        return build_contract(model, evidence, None, lambda _path: repository)[
            0
        ].to_dict()

    document = build_document()

    assert json.dumps(document) == json.dumps(build_document())
    canonical = '["nested","nested/é b.py",2,2,"code"]'
    expected = "src:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    assert expected in {source["id"] for source in document["sources"]}
    assert len(document["sources"]) == 3
    assert len({source["id"] for source in document["sources"]}) == 3
    by_id = {row["id"]: row for row in document["elements"]}
    assert expected in by_id["container:a"]["sources"]
    assert by_id["container:b"]["sources"] == [expected]
    # The repository is part of a source's identity.
    other = {source["id"] for source in build_document("other")["sources"]}
    assert other.isdisjoint(source["id"] for source in document["sources"])


def test_only_verified_citations_on_contract_parts_become_sources() -> None:
    model, evidence = pair(
        [element("container:a", "container")],
        citations=[
            cite("container:a", "kept.py"),
            cite("container:a", "unverified.py", verified=False),
            cite("container:a", "topic.md", source="topic"),
            cite(None, "no-target.md", source="documentation"),
            cite("system:app", "system.py"),
            cite("container:gone", "unknown-target.py"),
        ],
    )

    contract, _ = build_contract(model, evidence, None, root_repository)

    assert [source.path for source in contract.sources] == ["kept.py"]


def test_repository_rows_cover_every_repository_in_the_contract() -> None:
    model, evidence = pair(
        [
            element("container:a", "container"),
            element("container:b", "container"),
        ],
        citations=[
            cite("container:a", "vendor/a.py"),
            cite("container:b", "pyproject.toml"),
        ],
        # A direct file alone also brings in its repository.
        files={"container:a": ["vendor/a.py", "other/only_direct.py"]},
    )

    document = build_contract(
        model, evidence, None, lambda path: path.split("/")[0] if "/" in path else "."
    )[0].to_dict()

    assert document["repositories"] == [
        {"id": ".", "path": ".", "remote_url": None, "commit": "NO_GIT_HEAD"},
        {"id": "other", "path": "other", "remote_url": None, "commit": "NO_GIT_HEAD"},
        {"id": "vendor", "path": "vendor", "remote_url": None, "commit": "NO_GIT_HEAD"},
    ]
    assert {source["path"]: source["repository"] for source in document["sources"]} == {
        "pyproject.toml": ".",
        "vendor/a.py": "vendor",
    }


def test_repository_of_the_index_root_is_always_listed() -> None:
    model, evidence = pair(
        [element("container:a", "container")],
        citations=[cite("container:a", "vendor/a.py")],
    )

    contract, _ = build_contract(model, evidence, None, lambda _path: "vendor")

    assert [row.id for row in contract.repositories] == [".", "vendor"]


def test_omitted_parts_are_absent_counted_and_kept_in_the_pair(tmp_path) -> None:
    model, evidence = pair(
        [
            element("container:kept", "container"),
            element("component:kept", "component", "container:kept"),
            # Rule 1: documented components hang directly under the system.
            element("component:no-container", "component", "system:app"),
            # Rule 2: no source of its own, or its container falls away.
            element("external:no-source", "external", None),
            element("container:no-source", "container"),
            element("component:orphan", "component", "container:no-source"),
            element("component:no-source", "component", "container:no-source"),
        ],
        [
            relation("component:kept", "system:app"),
            # Rule 3: endpoints that are not in the contract.
            relation("component:kept", "external:no-source"),
            relation("component:no-container", "component:kept"),
            relation("component:orphan", "component:kept"),
            relation("component:kept", "external:never-existed"),
            # Rule 3: both endpoints exist, but nothing supports the relation.
            relation("container:kept", "component:kept"),
        ],
        citations=[
            cite("container:kept", "kept.py"),
            cite("component:kept", "kept.py"),
            cite("component:no-container", "gone-component.md"),
            cite("component:orphan", "gone-orphan.py"),
            cite("component:kept->system:app", "kept.py", 5),
            cite("component:kept->external:no-source", "gone-relation.py"),
            cite("component:no-container->component:kept", "gone-relation.py", 2),
            cite("component:orphan->component:kept", "gone-relation.py", 3),
            cite("component:kept->external:never-existed", "gone-relation.py", 4),
        ],
        files={"component:orphan": ["gone-orphan.py"], "component:kept": ["kept.py"]},
    )
    model_before = model.model_dump_json()
    evidence_before = evidence.model_dump_json()

    contract, counts = build_contract(
        model,
        evidence,
        [TopicSources("topic.md", ("gone-orphan.py",))],
        root_repository,
    )

    assert sorted(e.id for e in contract.elements) == [
        "component:kept",
        "container:kept",
    ]
    assert [r.id for r in contract.relations] == ["component:kept->system:app"]
    # Sources and coverage that only served the omitted part leave with it.
    assert {s.path for s in contract.sources} == {"kept.py"}
    assert [(t.file, t.covers) for t in contract.topics] == [("topic.md", [])]
    assert counts.components_without_container == 1
    assert counts.elements_without_source == 3
    assert counts.components_without_valid_container == 1
    assert counts.relations_without_endpoint == 4
    assert counts.relations_without_source == 1
    # The internal pair stays complete.
    assert model.model_dump_json() == model_before
    assert evidence.model_dump_json() == evidence_before
    load_quietly(contract, tmp_path)


def test_component_of_a_container_without_source_falls_away() -> None:
    model, evidence = pair(
        [
            element("container:bare", "container"),
            element("component:cited", "component", "container:bare"),
        ],
        citations=[cite("component:cited", "a.py")],
    )

    contract, counts = build_contract(model, evidence, None, root_repository)

    assert contract.elements == []
    assert counts.elements_without_source == 1
    assert counts.components_without_valid_container == 1
    assert counts.components_without_container == 0


def test_direct_files_and_topic_coverage() -> None:
    model, evidence = pair(
        [
            element("container:app", "container"),
            element("component:orders", "component", "container:app"),
            element("component:bare", "component", "container:app"),
        ],
        citations=[
            cite("container:app", "orders.py"),
            cite("container:app", "z_setup.py"),
            cite("component:orders", "orders.py"),
            cite("component:bare", "bare.py"),
        ],
        files={
            "system:app": ["bare.py", "orders.py", "z_setup.py"],
            "container:app": ["bare.py", "orders.py", "z_setup.py"],
            "component:orders": ["orders.py"],
            "component:bare": ["bare.py"],
        },
    )
    topics = [
        TopicSources("b_both.md", ("z_setup.py", "orders.py", "elsewhere.py")),
        TopicSources("a_component_only.md", ("orders.py",)),
        TopicSources("c_none.md", ("elsewhere.py",)),
    ]

    document = build_contract(model, evidence, topics, root_repository)[0].to_dict()

    files = {row["id"]: row["files"] for row in document["elements"]}
    # Sources stay rolled up to the container; only files are direct.
    sources = {row["id"]: len(row["sources"]) for row in document["elements"]}
    assert files["container:app"] == ["z_setup.py"]
    assert sources["container:app"] == 2
    assert files["component:orders"] == ["orders.py"]
    assert document["topics"] == [
        {
            "file": "a_component_only.md",
            "covers": [{"element": "component:orders", "files": ["orders.py"]}],
        },
        {
            "file": "b_both.md",
            "covers": [
                {"element": "component:orders", "files": ["orders.py"]},
                {"element": "container:app", "files": ["z_setup.py"]},
            ],
        },
        {"file": "c_none.md", "covers": []},
    ]


def test_run_without_research_has_no_topics() -> None:
    model, evidence = pair(
        [element("container:a", "container")],
        citations=[cite("container:a")],
        files={"container:a": ["a.py"]},
    )

    contract, _ = build_contract(model, evidence, None, root_repository)

    assert contract.to_dict()["topics"] == []


def labelled_pair(
    *arrows: dict[str, Any],
    titles: tuple[str, str] = ("reads", "writes"),
    extra: Sequence[dict[str, Any]] = (),
) -> tuple[C4Model, C4Evidence]:
    return pair(
        [
            element("container:a", "container"),
            element("container:b", "container"),
            element("component:a1", "component", "container:a"),
            element("component:b1", "component", "container:b"),
            element("component:b2", "component", "container:b"),
        ],
        [
            relation("component:a1", "component:b1", titles[0]),
            relation("component:a1", "component:b2", titles[1]),
            *extra,
        ],
        list(arrows),
        [
            cite("container:a", "a.py"),
            cite("container:b", "b.py"),
            cite("component:a1", "a.py"),
            cite("component:b1", "b1.py"),
            cite("component:b2", "b2.py"),
            cite("component:a1->component:b1", "a.py", 1),
            cite("component:a1->component:b2", "a.py", 2),
        ],
    )


UNDERLYING = ["component:a1->component:b2", "component:a1->component:b1"]


def labels_of(model: C4Model, evidence: C4Evidence) -> tuple[list[dict], int]:
    contract, counts = build_contract(model, evidence, None, root_repository)
    return contract.to_dict()["merged_labels"], counts.labels


def test_two_titles_give_a_label(tmp_path) -> None:
    model, evidence = labelled_pair(
        arrow("container:a", "container:b", UNDERLYING, "uses storage")
    )

    labels, omitted = labels_of(model, evidence)

    assert labels == [
        {
            "source": "container:a",
            "target": "container:b",
            "relations": sorted(UNDERLYING),
            "label": "uses storage",
        }
    ]
    assert omitted == 0
    load_quietly(build_contract(model, evidence, None, root_repository)[0], tmp_path)


def test_one_title_gives_no_label_and_omits_nothing() -> None:
    model, evidence = labelled_pair(
        arrow("container:a", "container:b", UNDERLYING, "reads"),
        titles=("reads", "reads"),
    )

    assert labels_of(model, evidence) == ([], 0)


@pytest.mark.parametrize(
    "label",
    ["", "   ", "x" * 61, "reads [...] writes"],
    ids=["empty", "blank", "too-long", "elided"],
)
def test_unusable_label_is_omitted_and_counted(label: str) -> None:
    model, evidence = labelled_pair(
        arrow("container:a", "container:b", UNDERLYING, label)
    )

    assert labels_of(model, evidence) == ([], 1)


def test_label_of_exactly_sixty_characters_is_kept() -> None:
    model, evidence = labelled_pair(
        arrow("container:a", "container:b", UNDERLYING, "x" * 60)
    )

    labels, omitted = labels_of(model, evidence)

    assert [row["label"] for row in labels] == ["x" * 60]
    assert omitted == 0


def test_label_over_an_omitted_relation_is_omitted_and_counted() -> None:
    uncited = "component:a1->component:gone"
    model, evidence = labelled_pair(
        arrow("container:a", "container:b", [*UNDERLYING, uncited], "uses"),
        extra=[relation("component:a1", "component:gone", "drops")],
    )

    assert labels_of(model, evidence) == ([], 1)


def test_label_with_an_omitted_endpoint_is_omitted_and_counted() -> None:
    model, evidence = labelled_pair(
        arrow("container:gone", "container:b", UNDERLYING, "uses")
    )

    assert labels_of(model, evidence) == ([], 1)


def test_label_may_end_at_the_system() -> None:
    model, evidence = labelled_pair(
        arrow("system:app", "container:b", UNDERLYING, "uses")
    )

    labels, _ = labels_of(model, evidence)

    assert [row["source"] for row in labels] == ["system:app"]


def test_same_relations_in_two_views_give_one_label_first_in_sorting() -> None:
    model, evidence = labelled_pair(
        arrow("container:a", "container:b", UNDERLYING, "zeta", view="v1"),
        arrow(
            "container:a", "container:b", list(reversed(UNDERLYING)), "alpha", view="v2"
        ),
        arrow("container:a", "container:b", UNDERLYING, "zeta", view="v3"),
    )

    labels, omitted = labels_of(model, evidence)

    assert [row["label"] for row in labels] == ["alpha"]
    assert omitted == 1


def test_one_pair_keeps_a_label_per_relation_set() -> None:
    third = "component:a1->component:b3"
    model, evidence = pair(
        [
            element("container:a", "container"),
            element("container:b", "container"),
            element("component:a1", "component", "container:a"),
            element("component:b1", "component", "container:b"),
            element("component:b2", "component", "container:b"),
            element("component:b3", "component", "container:b"),
        ],
        [
            relation("component:a1", "component:b1", "reads"),
            relation("component:a1", "component:b2", "writes"),
            relation("component:a1", "component:b3", "deletes"),
        ],
        [
            arrow("container:a", "container:b", UNDERLYING, "narrow", view="v1"),
            arrow(
                "container:a", "container:b", [*UNDERLYING, third], "wide", view="v2"
            ),
        ],
        [
            cite("container:a", "a.py"),
            cite("container:b", "b.py"),
            cite("component:a1", "a.py"),
            cite("component:b1", "b1.py"),
            cite("component:b2", "b2.py"),
            cite("component:b3", "b3.py"),
            cite("component:a1->component:b1", "a.py", 1),
            cite("component:a1->component:b2", "a.py", 2),
            cite(third, "a.py", 3),
        ],
    )

    labels, omitted = labels_of(model, evidence)

    assert [row["label"] for row in labels] == ["narrow", "wide"]
    assert omitted == 0


def test_incomplete_parts_are_counted() -> None:
    model, evidence = pair(
        [
            element("container:bare", "container"),
            element("container:full", "container", description="d", technology="Go"),
            element("storage:volume", "storage", description="d"),
            element("component:bare", "component", "container:bare"),
            # C4 asks no technology of these two, but a description of everyone.
            element("person:admin", "person", None),
            element("external:api", "external", None, description="An API."),
        ],
        [
            relation("container:bare", "container:full"),
            relation("container:full", "storage:volume"),
            relation("component:bare", "container:full"),
            relation("person:admin", "container:full"),
        ],
        citations=[
            cite("container:bare"),
            cite("container:full"),
            cite("storage:volume"),
            cite("component:bare"),
            cite("person:admin"),
            cite("external:api"),
            cite("container:bare->container:full", line=2),
            cite("container:full->storage:volume", line=3),
            cite("component:bare->container:full", line=4),
            cite("person:admin->container:full", line=5),
        ],
    )

    _, counts = build_contract(model, evidence, None, root_repository)

    assert counts.without_technology == 3
    assert counts.without_description == 3
    assert counts.container_relations_without_protocol == 2


def test_system_without_description_counts_as_incomplete() -> None:
    model, evidence = pair(
        [element("container:a", "container", description="d", technology="Go")],
        citations=[cite("container:a")],
    )
    system = next(e for e in model.elements if e.kind == "system")
    system.description = None

    contract, counts = build_contract(model, evidence, None, root_repository)

    assert contract.system.description == ""
    assert counts.without_description == 1
