"""Closed decisions change the map, reuse only matching evidence, and fail safely."""

import json
import os
import time
from copy import deepcopy
from dataclasses import replace

import pytest

from chunkhound.code_mapper.c4.assemble import AssemblyInput, assemble_with_notes
from chunkhound.code_mapper.c4.documented import (
    DocElement,
    DocRelation,
    DocumentedOutcome,
)
from chunkhound.code_mapper.c4.llm import C4Llm, RetryQueue
from chunkhound.code_mapper.c4.model import Citation, Overrides
from chunkhound.code_mapper.c4.references import ReferenceScan
from chunkhound.code_mapper.c4.runtime import RuntimeScan
from chunkhound.llm_manager import LLMManager
from chunkhound.services.extraction.budget import (
    effective_target,
    fits,
    measure_request,
)
from tests.code_mapper.c4.conftest import decision_items

KINDS = {"Astro": "neither", "AI assistant": "person", "Stripe": "external"}


def answer(prompt):
    return {
        "decisions": [
            {"id": i["id"], "value": KINDS[i["term"]]} for i in decision_items(prompt)
        ]
    }


def documents(root):
    (root / "README.md").write_text(
        "Astro is a framework.\nAI assistant uses Shop.\nShop uses Stripe.\n"
    )
    citations = [
        Citation(
            target=None,
            file="README.md",
            start_line=n,
            end_line=n,
            source="documentation",
            verified=True,
        )
        for n in (1, 2, 3)
    ]
    return DocumentedOutcome(
        [
            DocElement("external", term, citation)
            for term, citation in zip(KINDS, citations)
        ],
        [
            DocRelation("Shop", "Astro", "uses", citations[0]),
            DocRelation("AI assistant", "Shop", "uses", citations[1]),
            DocRelation("Shop", "Stripe", "uses", citations[2]),
        ],
        {"README.md": "source-hash"},
        False,
        version="raw-extraction-version",
    )


async def run(root, manager, docs, *, trial=False, retries=None):
    from chunkhound.code_mapper.c4.decisions import decide

    llm = C4Llm(manager, concurrency=2, trial=trial)
    outcome = await decide(
        project_root=root,
        doc_files=["README.md"],
        system_name="Shop",
        documented=docs,
        llm=llm,
        retries=retries or RetryQueue(),
    )
    return outcome, llm


def assembled(root, docs):
    runtime = RuntimeScan("system:shop", "Shop", [], [], [], [], {})
    return assemble_with_notes(
        AssemblyInput(
            runtime,
            ReferenceScan([], frozenset(), {}),
            [],
            {},
            {},
            {},
            docs,
            {},
            Overrides(),
            project_root=root,
        )
    )


def cache_files(root):
    return sorted((root / ".chunkhound/extraction/decisions/c4_element").glob("*.json"))


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


async def test_r20_element_decisions_change_map_not_raw_lock(
    tmp_path, c4_llm_manager, scripted
):
    docs = documents(tmp_path)
    before = deepcopy(docs)
    scripted.answers["c4_element"] = answer
    result, _ = await run(tmp_path, c4_llm_manager, docs)
    elements, _, evidence, notes = assembled(tmp_path, result.documented)
    assert {e.id for e in elements} == {
        "system:shop",
        "person:ai-assistant",
        "external:stripe",
    }
    assert not any(c.target == "external:astro" for c in evidence.citations)
    assert notes.unlinked.no_match == 1
    assert docs == before
    assert result.documented is not docs
    assert result.documented.relations == docs.relations
    report = "\n".join(result.report_lines)
    assert "Astro" in report and "dropped" in report
    assert "AI assistant" in report and "person" in report and "kind changed" in report


async def test_r23_element_cache_reuses_only_unchanged_items(
    tmp_path, c4_llm_manager, scripted, monkeypatch
):
    docs = documents(tmp_path)
    seen = []

    def record(prompt):
        seen.append({i["term"] for i in decision_items(prompt)})
        return answer(prompt)

    scripted.answers["c4_element"] = record
    await run(tmp_path, c4_llm_manager, docs)
    seen.clear()
    await run(
        tmp_path, c4_llm_manager, replace(docs, elements=list(reversed(docs.elements)))
    )
    assert seen == []
    # Only the literal quote changes; positions and extraction objects do not.
    path = tmp_path / "README.md"
    path.write_text(path.read_text().replace("framework", "web framework"))
    await run(tmp_path, c4_llm_manager, docs)
    assert seen == [{"Astro"}]
    seen.clear()

    synthesis = LLMManager(
        utility_config=c4_llm_manager.role_config("utility"),
        synthesis_config={"provider": "other", "model": "other"},
    )
    await run(tmp_path, synthesis, docs)
    assert seen == []
    for field, value in (
        ("provider", "other"),
        ("model", "other"),
        ("reasoning_effort", "high"),
        ("base_url", "https://other.invalid"),
    ):
        config = {**c4_llm_manager.role_config("utility"), field: value}
        manager = LLMManager(utility_config=config, synthesis_config=config)
        await run(tmp_path, manager, docs)
        assert seen.pop() == set(KINDS)

    from chunkhound.code_mapper.c4 import decisions

    original = decisions.load_c4_prompt
    monkeypatch.setattr(
        decisions,
        "load_c4_prompt",
        lambda step: original(step) + "\nAdditional criteria.",
    )
    await run(tmp_path, c4_llm_manager, docs)
    assert seen.pop() == set(KINDS)
    monkeypatch.setattr(decisions, "_VALIDATOR_VERSION", 2)
    await run(tmp_path, c4_llm_manager, docs)
    assert seen.pop() == set(KINDS)


@pytest.mark.parametrize("corruption", ["json", "key", "parts", "format", "answer"])
async def test_r23_bad_cache_is_a_miss(tmp_path, c4_llm_manager, scripted, corruption):
    docs = replace(documents(tmp_path), elements=documents(tmp_path).elements[:1])
    scripted.answers["c4_element"] = answer
    await run(tmp_path, c4_llm_manager, docs)
    (path,) = cache_files(tmp_path)
    data = json.loads(path.read_text())
    if corruption == "json":
        path.write_text("{not json")
    else:
        if corruption == "key":
            data["key"] = "foreign"
        elif corruption == "parts":
            data["key_parts"]["item"]["term"] = "foreign"
        elif corruption == "format":
            data["format"] = 99
        else:
            data["answer"] = {"decisions": [{"id": "foreign", "value": "person"}]}
        path.write_text(json.dumps(data))
    before = scripted.question_calls["c4_element"]
    result, _ = await run(tmp_path, c4_llm_manager, docs)
    assert scripted.question_calls["c4_element"] == before + 1
    assert result.documented.elements == []


@pytest.mark.parametrize("fault", ["missing", "duplicate", "unknown", "value", "extra"])
async def test_closed_answers_retry_then_fall_back(
    tmp_path, c4_llm_manager, scripted, fault
):
    docs = documents(tmp_path)

    def invalid(prompt):
        result = answer(prompt)
        rows = result["decisions"]
        if fault == "missing":
            rows.pop()
        elif fault == "duplicate":
            rows.append(dict(rows[0]))
        elif fault == "unknown":
            rows[0]["id"] = "unknown"
        elif fault == "value":
            rows[0]["value"] = "container"
        else:
            rows[0]["explanation"] = "not allowed"
        return result

    scripted.answers["c4_element"] = invalid
    result, llm = await run(tmp_path, c4_llm_manager, docs)
    assert result.documented.elements == docs.elements
    assert scripted.question_calls["c4_element"] == 2
    assert ", fallback" in "\n".join(llm.report_lines())
    assert cache_files(tmp_path) == []
    scripted.answers["c4_element"] = ValueError("invalid provider configuration")
    with pytest.raises(ValueError, match="configuration"):
        await run(tmp_path, c4_llm_manager, docs)


async def test_decision_bundles_retry_independently(tmp_path, c4_llm_manager, scripted):
    from chunkhound.code_mapper.c4.decisions import DecisionAnswer

    docs = documents(tmp_path)
    docs.elements = [
        replace(docs.elements[n], description="evidence " * 550) for n in (0, 1)
    ]
    config = {
        **c4_llm_manager.role_config("utility"),
        "max_input_chars": 12_000,
        "max_input_tokens": 4_000,
    }
    manager = LLMManager(utility_config=config, synthesis_config=config)
    meter = C4Llm(manager, concurrency=2, trial=False)
    attempts = {}

    def bounded(prompt):
        assert fits(
            prompt,
            DecisionAnswer.model_json_schema(),
            meter.input_limit("utility"),
            meter.estimate_tokens,
        )
        assert measure_request(
            prompt, DecisionAnswer.model_json_schema(), []
        ) <= effective_target(meter.input_limit("utility"))
        terms = tuple(i["term"] for i in decision_items(prompt))
        attempts[terms] = attempts.get(terms, 0) + 1
        return {"decisions": []} if attempts[terms] == 1 else answer(prompt)

    scripted.answers["c4_element"] = bounded
    result, _ = await run(tmp_path, manager, docs)
    assert [(e.term, e.kind) for e in result.documented.elements] == [
        ("AI assistant", "person")
    ]
    assert attempts == {("Astro",): 2, ("AI assistant",): 2}
    oversized = replace(
        docs, elements=[replace(docs.elements[0], description="x" * 20_000)]
    )
    result, llm = await run(tmp_path, manager, oversized)
    assert result.documented.elements == oversized.elements
    assert llm.calls == 0
    assert "fallback" in "\n".join(llm.report_lines())


async def test_r23_trial_is_read_only(tmp_path, c4_llm_manager, scripted):
    docs = documents(tmp_path)
    scripted.answers["c4_element"] = answer
    await run(tmp_path, c4_llm_manager, replace(docs, elements=docs.elements[:1]))
    lock = tmp_path / ".chunkhound/map.lock.json"
    lock.write_text("untouched raw lock")
    before = snapshot(tmp_path)
    result, llm = await run(tmp_path, c4_llm_manager, docs, trial=True)
    assert [(e.term, e.kind) for e in result.documented.elements] == [
        ("AI assistant", "external"),
        ("Stripe", "external"),
    ]
    assert llm.calls == 0
    assert "trial" in "\n".join(result.report_lines)
    assert snapshot(tmp_path) == before
    empty = tmp_path / "empty"
    empty.mkdir()
    other = documents(empty)
    await run(empty, c4_llm_manager, other, trial=True)
    assert not (empty / ".chunkhound").exists()


async def test_r23_pruning_keeps_reused_items(tmp_path, c4_llm_manager, scripted):
    from chunkhound.code_mapper.c4.decisions import prune_decision_cache

    docs = documents(tmp_path)
    scripted.answers["c4_element"] = answer
    await run(tmp_path, c4_llm_manager, docs)
    hit = cache_files(tmp_path)[0]
    old = hit.parent / "unused.json"
    temporary = hit.parent / ".expired.tmp"
    recent = hit.parent / ".recent.tmp"
    for path in (old, temporary, recent):
        path.write_text("{}")
    month = time.time() - 31 * 86_400
    for path in (*cache_files(tmp_path), temporary):
        os.utime(path, (month, month))
    before = snapshot(tmp_path)
    await run(tmp_path, c4_llm_manager, docs, trial=True)
    assert snapshot(tmp_path) == before
    await run(tmp_path, c4_llm_manager, docs)
    prune_decision_cache(tmp_path)
    assert hit.exists() and hit.stat().st_mtime > month
    assert not old.exists() and not temporary.exists()
    assert recent.exists()


def table_documents(root, rows=("| OpenCode CLI | command-line provider |",)):
    (root / "README.md").write_text(
        "# Shop\n\n## Providers\n\n| Service | Purpose |\n| --- | --- |\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    return DocumentedOutcome([], [], {"README.md": "raw-hash"}, False)


def decisions_value(value):
    return lambda prompt: {
        "decisions": [
            {"id": item["id"], "value": value} for item in decision_items(prompt)
        ]
    }


@pytest.mark.parametrize(
    ("kind", "term", "expected"),
    [
        ("external", "OpenCode CLI", "external:opencode-cli"),
        ("person", "AI assistant", "person:ai-assistant"),
        ("neither", "LLM provider", None),
        ("external", "", None),
    ],
)
async def test_r21_service_row_adds_element_and_uses_relation(
    tmp_path, c4_llm_manager, scripted, kind, term, expected
):
    raw = f"| {term} | command-line provider |"
    docs = table_documents(tmp_path, [raw])
    before = deepcopy(docs)
    scripted.answers["c4_table"] = decisions_value("service_list")
    scripted.answers["c4_row"] = decisions_value(kind)
    result, _ = await run(tmp_path, c4_llm_manager, docs)
    elements, relations, evidence, _ = assembled(tmp_path, result.documented)
    assert docs == before
    assert scripted.question_calls["c4_element"] == 0
    if expected is None:
        assert result.added == []
        assert relations == []
        assert [e.id for e in elements] == ["system:shop"]
        return
    actor = next(e for e in elements if e.id == expected)
    assert actor.name == term
    citation = next(c for c in evidence.citations if c.target == expected)
    assert (citation.file, citation.start_line, citation.end_line) == (
        "README.md",
        7,
        7,
    )
    assert citation.source == "documentation" and citation.verified
    assert (tmp_path / citation.file).read_text().splitlines()[
        citation.start_line - 1
    ] == raw
    relation = relations[0]
    endpoints = (
        ("system:shop", expected) if kind == "external" else (expected, "system:shop")
    )
    assert (relation.from_id, relation.to_id, relation.title) == (*endpoints, "uses")
    assert [e.term for e in result.added] == [term]
    assert "service tables" in "\n".join(result.report_lines)


def test_r21_visible_cells_keep_source_lines(tmp_path):
    from chunkhound.code_mapper.c4.tables import read_tables

    raw = (
        r"| Open**Code** CLI | [Tool](https://example.test) | `cli` | "
        r"*agent* | a\|b | Café 🐍 |"
    )
    source = (
        "# Shop\n\n## **Integrations**\n\n### Providers\n\n"
        "| Name | Link | Code | Role | Pipe | Unicode |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        + raw
        + "\n\n```\n| Fake | Service |\n| --- | --- |\n| Ghost | none |\n```\n"
        "\nOther section\n=============\n\n"
        "| Name | Use |\n| --- | --- |\n| Next | next |\n"
    )
    (tmp_path / "README.md").write_text(source, encoding="utf-8")
    (tmp_path / "unselected.md").write_text(source, encoding="utf-8")
    first, second = read_tables(tmp_path, ["README.md"])
    assert first.path == "README.md"
    assert first.headings == ("Shop", "Integrations", "Providers")
    assert first.header == ("Name", "Link", "Code", "Role", "Pipe", "Unicode")
    assert first.rows[0].cells == (
        "OpenCode CLI",
        "Tool",
        "cli",
        "agent",
        "a|b",
        "Café 🐍",
    )
    assert first.rows[0].line == 9
    assert first.rows[0].raw == raw
    assert second.headings == ("Other section",)
    assert [r.cells[0] for r in second.rows] == ["Next"]


async def test_r21_other_table_adds_nothing(tmp_path, c4_llm_manager, scripted):
    docs = table_documents(tmp_path, ["| --verbose | verbose output |"])
    scripted.answers["c4_table"] = decisions_value("other")
    result, _ = await run(tmp_path, c4_llm_manager, docs)
    assert scripted.question_calls["c4_table"] == 1
    assert scripted.question_calls["c4_row"] == 0
    assert result.added == []
    assert result.documented.elements == [] and result.documented.relations == []


@pytest.mark.parametrize(
    ("checked", "row_kind", "added"),
    [
        ("external", "external", False),
        ("neither", "external", True),
        ("person", "external", True),
        ("person", "person", False),
    ],
)
async def test_r21_deduplicates_after_element_check(
    tmp_path, c4_llm_manager, scripted, checked, row_kind, added
):
    docs = table_documents(tmp_path)
    citation = Citation(
        target=None,
        file="README.md",
        start_line=1,
        end_line=1,
        source="documentation",
        verified=True,
    )
    original = DocElement("external", "opencode-cli", citation)
    own_relation = DocRelation("Shop", "opencode-cli", "configured for", citation)
    docs = replace(docs, elements=[original], relations=[own_relation])
    scripted.answers["c4_table"] = decisions_value("service_list")
    scripted.answers["c4_row"] = decisions_value(row_kind)
    scripted.answers["c4_element"] = decisions_value(checked)
    result, _ = await run(tmp_path, c4_llm_manager, docs)
    assert [e.term for e in result.added] == (["OpenCode CLI"] if added else [])
    assert own_relation in result.documented.relations
    assert [r.title for r in result.documented.relations] == (
        ["configured for", "uses"] if added else ["configured for"]
    )
    if added:
        assert result.added[0].kind == row_kind
    else:
        assert result.documented.elements == [replace(original, kind=checked)]


async def test_r23_only_changed_late_row_is_asked_again(
    tmp_path, c4_llm_manager, scripted
):
    rows = [f"| Tool {n} | provider |" for n in range(1, 6)]
    docs = table_documents(tmp_path, rows)
    seen = []

    def record(prompt):
        seen.extend(item["row"] for item in decision_items(prompt))
        return decisions_value("external")(prompt)

    scripted.answers["c4_table"] = decisions_value("service_list")
    scripted.answers["c4_row"] = record
    await run(tmp_path, c4_llm_manager, docs)
    seen.clear()
    tables = scripted.question_calls["c4_table"]
    await run(tmp_path, c4_llm_manager, docs)
    assert seen == []
    rows[3] = "| Changed tool | provider |"
    table_documents(tmp_path, rows)
    result, _ = await run(tmp_path, c4_llm_manager, docs)
    assert scripted.question_calls["c4_table"] == tables
    assert seen == ["| Changed tool | provider |"]
    assert "Changed tool" in [e.term for e in result.added]
    assert "Tool 4" not in [e.term for e in result.added]
    path = tmp_path / "README.md"
    for old, new in (
        ("## Providers", "## Services"),
        ("| Service | Purpose |", "| Name | Purpose |"),
        ("| Tool 1 | provider |", "| Tool 1 | changed |"),
    ):
        path.write_text(path.read_text().replace(old, new))
        await run(tmp_path, c4_llm_manager, docs)
        tables += 1
        assert scripted.question_calls["c4_table"] == tables


async def test_r21_tables_with_same_preview_keep_both_late_rows(
    tmp_path, c4_llm_manager, scripted
):
    rows = [f"| Tool {n} | provider |" for n in range(1, 4)]
    docs = table_documents(tmp_path, [*rows, "| First late tool | provider |"])
    path = tmp_path / "README.md"
    path.write_text(
        path.read_text()
        + "\n| Service | Purpose |\n| --- | --- |\n"
        + "\n".join([*rows, "| Second late tool | provider |"])
        + "\n"
    )
    scripted.answers["c4_table"] = decisions_value("service_list")
    scripted.answers["c4_row"] = decisions_value("external")
    result, _ = await run(tmp_path, c4_llm_manager, docs)
    assert {item.term for item in result.added} == {
        "Tool 1",
        "Tool 2",
        "Tool 3",
        "First late tool",
        "Second late tool",
    }


@pytest.mark.parametrize(
    ("heading", "expected_headings"),
    [
        ("#", ("",)),
        ("##", ("Shop", "")),
        ("###", ("Shop", "Obsolete", "")),
        ("####", ("Shop", "Obsolete", "Retired", "")),
        ("#####", ("Shop", "Obsolete", "Retired", "")),
        ("######", ("Shop", "Obsolete", "Retired", "")),
    ],
)
async def test_r21_empty_heading_keeps_scope_and_service_actor(
    tmp_path, c4_llm_manager, scripted, heading, expected_headings
):
    from chunkhound.code_mapper.c4.tables import read_tables

    raw = "| Open**Code** CLI | command-line provider |"
    (tmp_path / "README.md").write_text(
        "# Shop\n\n## Obsolete\n\n### Retired\n\n"
        + heading
        + "\n\n| Service | Purpose |\n| --- | --- |\n"
        + raw
        + "\n",
        encoding="utf-8",
    )
    (table,) = read_tables(tmp_path, ["README.md"])
    assert table.headings == expected_headings
    assert table.rows[0].raw == raw and table.rows[0].line == 11
    scripted.answers["c4_table"] = decisions_value("service_list")
    scripted.answers["c4_row"] = decisions_value("external")
    docs = DocumentedOutcome([], [], {"README.md": "raw-hash"}, False)
    result, _ = await run(tmp_path, c4_llm_manager, docs)
    elements, relations, evidence, _ = assembled(tmp_path, result.documented)
    actor = next(e for e in elements if e.id == "external:opencode-cli")
    assert actor.name == "OpenCode CLI"
    citation = next(c for c in evidence.citations if c.target == actor.id)
    assert (citation.file, citation.start_line, citation.end_line) == (
        "README.md",
        11,
        11,
    )
    assert citation.source == "documentation" and citation.verified
    assert [
        (relation.from_id, relation.to_id, relation.title) for relation in relations
    ] == [("system:shop", "external:opencode-cli", "uses")]


async def test_r21_empty_headings_without_tables_add_no_actors(
    tmp_path, c4_llm_manager
):
    from chunkhound.code_mapper.c4.tables import read_tables

    (tmp_path / "README.md").write_text("#\n\n##\n\n###\n\n####\n\n#####\n\n######\n")
    assert read_tables(tmp_path, ["README.md"]) == []
    docs = DocumentedOutcome([], [], {"README.md": "raw-hash"}, False)
    result, llm = await run(tmp_path, c4_llm_manager, docs)
    elements, relations, _, _ = assembled(tmp_path, result.documented)
    assert result.added == [] and result.documented == docs
    assert [element.id for element in elements] == ["system:shop"]
    assert relations == []
    assert llm.calls == 0


def actor_state(root, *, extra=()):
    from chunkhound.code_mapper.c4.curation import CurationState
    from chunkhound.code_mapper.c4.model import Coverage, Element, Reference, Relation

    names = {
        "system:shop": ("system", "Shop"),
        "person:agents": ("person", "agents"),
        "person:ai-assistant": ("person", "AI assistant"),
        "external:google": ("external", "Google"),
        "external:google-gemini": ("external", "Google Gemini"),
        **dict(extra),
    }
    (root / "README.md").write_text("\n".join(name for _, name in names.values()))
    elements = {
        id: Element(
            id=id,
            kind=kind,
            name=name,
            description=None,
            parent=None,
            status="found" if id == "external:google" else "documented",
            markers=[],
            coverage=Coverage(status="none", topics=[]),
        )
        for id, (kind, name) in names.items()
    }
    relations = {}
    citations = []
    for line, (id, element) in enumerate(elements.items(), 1):
        citations.append(
            Citation(
                target=id,
                file="README.md",
                start_line=line,
                end_line=line,
                source="code" if id == "external:google" else "documentation",
                verified=True,
            )
        )
        if element.kind == "system":
            continue
        source, target = (
            (id, "system:shop") if element.kind == "person" else ("system:shop", id)
        )
        rid = f"{source}->{target}"
        relations[rid] = Relation(
            id=rid,
            from_id=source,
            to_id=target,
            title="uses",
            status=element.status,
            reference_counts={"import": 1} if id == "external:google" else {},
            markers=[],
        )
    reference = Reference(
        relation="system:shop->external:google",
        from_file="client.py",
        line=1,
        to="google",
        kind="import",
        status="counts",
    )
    return CurationState(
        elements, relations, citations, [reference], {id: [] for id in elements}
    )


async def consolidate_state(root, manager, state, *, overrides=None, trial=False):
    from chunkhound.code_mapper.c4.consolidation import consolidate

    llm = C4Llm(manager, concurrency=2, trial=trial)
    outcome = await consolidate(
        state=state,
        overrides=overrides or Overrides(),
        project_root=root,
        llm=llm,
        retries=RetryQueue(),
    )
    return outcome, llm


def actor_answers(scripted, pair="same"):
    from tests.code_mapper.c4.conftest import (
        actor_groups,
        actor_survivors,
        neutral_decisions,
    )

    scripted.answers.update(
        {
            "c4_group": actor_groups,
            "c4_survivor": actor_survivors,
            "c4_pair": neutral_decisions(pair),
        }
    )


@pytest.mark.parametrize("pair", ["same", "different", "unsure"])
async def test_r18_r19_only_same_merges_into_existing_survivor(
    tmp_path, c4_llm_manager, scripted, pair
):
    from chunkhound.code_mapper.c4.curation import curate

    state = actor_state(tmp_path)
    before = deepcopy(state)
    actor_answers(scripted, pair)
    outcome, _ = await consolidate_state(tmp_path, c4_llm_manager, state)
    expected = (
        {
            "person:agents": "person:ai-assistant",
            "external:google": "external:google-gemini",
        }
        if pair == "same"
        else {}
    )
    assert outcome.merges == expected
    result = curate(state, {}, Overrides(merge=outcome.merges))
    assert state == before
    assert result.elements["external:google-gemini"].name == "Google Gemini"
    assert result.references[0].to == "google"
    if pair == "same":
        assert "external:google" not in result.elements
        assert result.elements["external:google-gemini"].status == "found"
        assert result.relations[
            "system:shop->external:google-gemini"
        ].reference_counts == {"import": 1}
        assert result.references[0].relation == "system:shop->external:google-gemini"
        assert sum(c.target == "external:google-gemini" for c in result.citations) == 2
    assert not (tmp_path / ".chunkhound/map.lock.json").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "mixed",
        "duplicate",
        "overlap",
        "survivor",
    ],
)
async def test_group_answers_retry_then_fall_back(
    tmp_path, c4_llm_manager, scripted, fault
):
    state = actor_state(tmp_path)
    actor_answers(scripted)

    def invalid(prompt):
        members = decision_items(prompt)[0]["members"]
        ids = [m["id"] for m in members]
        if fault == "unknown":
            ids.append("unknown")
        elif fault == "mixed":
            ids.append(
                "person:agents" if members[0]["name"] == "Google" else "external:google"
            )
        elif fault == "duplicate":
            ids.append(ids[0])
        groups = [{"members": ids}]
        if fault == "overlap":
            groups.append({"members": ids[:1]})
        return {"groups": groups}

    if fault == "survivor":
        scripted.answers["c4_survivor"] = lambda prompt: {
            "decisions": [
                {"id": i["id"], "value": "unknown"} for i in decision_items(prompt)
            ]
        }
    else:
        scripted.answers["c4_group"] = invalid
    outcome, llm = await consolidate_state(tmp_path, c4_llm_manager, state)
    assert outcome.merges == {}
    assert ", fallback" in "\n".join(llm.report_lines())
    question = "c4_survivor" if fault == "survivor" else "c4_group"
    assert not list(
        (tmp_path / ".chunkhound/extraction/decisions" / question).glob("*.json")
    )
    assert scripted.question_calls[question] == (2 if fault == "survivor" else 4)
    assert scripted.question_calls["c4_pair"] == 0


@pytest.mark.parametrize("singleton", [False, True])
async def test_empty_and_singleton_groups_are_cached_without_closed_questions(
    tmp_path, c4_llm_manager, scripted, singleton
):
    state = actor_state(tmp_path)
    scripted.answers["c4_group"] = lambda prompt: {
        "groups": [{"members": [decision_items(prompt)[0]["members"][0]["id"]]}]
        if singleton
        else []
    }
    outcome, _ = await consolidate_state(tmp_path, c4_llm_manager, state)
    assert outcome.merges == {}
    scripted.calls.clear()
    replay, _ = await consolidate_state(tmp_path, c4_llm_manager, state)
    assert replay.merges == {} and not scripted.calls
    assert not scripted.question_calls["c4_survivor"]


@pytest.mark.parametrize(
    "pair,expected",
    [
        (
            ("person:ai-assistant", "person:agents"),
            {"person:teams": "person:ai-assistant"},
        ),
        (("person:agents", "person:teams"), {"person:agents": "person:ai-assistant"}),
        (
            ("person:teams", "person:ai-assistant"),
            {"person:agents": "person:ai-assistant"},
        ),
    ],
)
async def test_r22_keep_apart_blocks_direct_and_shared_target_merges(
    tmp_path, c4_llm_manager, scripted, pair, expected
):
    state = actor_state(tmp_path, extra=(("person:teams", ("person", "teams")),))
    actor_answers(scripted)

    def pair_answer(prompt):
        items = decision_items(prompt)
        assert {(i["survivor"]["name"], i["other"]["name"]) for i in items} == {
            ("AI assistant", "agents"),
            ("AI assistant", "teams"),
        }
        return {"decisions": [{"id": i["id"], "value": "same"} for i in items]}

    scripted.answers["c4_pair"] = pair_answer
    scripted.answers["c4_group"] = lambda prompt: {
        "groups": [{"members": [m["id"] for m in decision_items(prompt)[0]["members"]]}]
        if decision_items(prompt)[0]["kind"] == "person"
        else []
    }
    outcome, _ = await consolidate_state(
        tmp_path, c4_llm_manager, state, overrides=Overrides(keep_apart=[pair])
    )
    assert outcome.merges == expected
    assert "keep_apart" in "\n".join(outcome.report_lines)
    assert scripted.question_calls["c4_pair"] == 1  # one bundle, two independent pairs


async def test_r22_two_member_block_precedes_survivor_and_reports_invalid_ids(
    tmp_path, c4_llm_manager, scripted
):
    state = actor_state(tmp_path)
    actor_answers(scripted)
    normal = scripted.answers["c4_survivor"]

    def external_survivor_only(prompt):
        names = {m["name"] for i in decision_items(prompt) for m in i["members"]}
        assert names == {"Google", "Google Gemini"}
        return normal(prompt)

    scripted.answers["c4_survivor"] = external_survivor_only
    overrides = Overrides(
        keep_apart=[
            ("person:ai-assistant", "person:agents"),
            ("system:shop", "person:agents"),
            ("person:missing", "person:agents"),
        ]
    )
    outcome, _ = await consolidate_state(
        tmp_path, c4_llm_manager, state, overrides=overrides
    )
    assert outcome.merges == {"external:google": "external:google-gemini"}
    report = "\n".join(outcome.report_lines)
    assert "not on the map" in report and "not an external system or person" in report
    assert "keep_apart" in report


async def test_oversized_group_does_not_call_provider(
    tmp_path, c4_llm_manager, scripted
):
    state = actor_state(tmp_path)
    state.elements["person:agents"].description = "x" * 20_000
    actor_answers(scripted)
    config = {
        **c4_llm_manager.role_config("utility"),
        "max_input_chars": 12_000,
        "max_input_tokens": 4_000,
    }
    manager = LLMManager(utility_config=config, synthesis_config=config)
    outcome, llm = await consolidate_state(tmp_path, manager, state)
    assert outcome.merges == {"external:google": "external:google-gemini"}
    assert scripted.question_calls["c4_group"] == 1
    assert "budget" in "\n".join(outcome.report_lines)
    assert "fallback" in "\n".join(llm.report_lines())


async def test_r23_consolidation_reuses_and_invalidates_per_kind(
    tmp_path, c4_llm_manager, scripted
):
    state = actor_state(tmp_path)
    actor_answers(scripted)
    first, _ = await consolidate_state(tmp_path, c4_llm_manager, state)
    scripted.calls.clear()
    replay, _ = await consolidate_state(tmp_path, c4_llm_manager, state)
    assert replay.merges == first.merges and not scripted.calls
    scripted.question_calls.clear()
    added = actor_state(tmp_path, extra=(("person:teams", ("person", "teams")),))
    await consolidate_state(tmp_path, c4_llm_manager, added)
    assert dict(scripted.question_calls) == {"c4_group": 1}
    # Changing one group's choice invalidates only the pairs that depend on it.
    for path in (tmp_path / ".chunkhound/extraction/decisions/c4_survivor").glob(
        "*.json"
    ):
        data = json.loads(path.read_text())
        if "person:agents" in str(data["key_parts"]["item"]):
            data["answer"]["decisions"][0]["value"] = "person:agents"
            path.write_text(json.dumps(data))
    scripted.question_calls.clear()
    changed, _ = await consolidate_state(tmp_path, c4_llm_manager, state)
    assert changed.merges["person:ai-assistant"] == "person:agents"
    assert dict(scripted.question_calls) == {"c4_pair": 1}
    config = {**c4_llm_manager.role_config("utility"), "reasoning_effort": "high"}
    manager = LLMManager(utility_config=config, synthesis_config=config)
    scripted.question_calls.clear()
    await consolidate_state(tmp_path, manager, state)
    assert set(scripted.question_calls) == {"c4_group", "c4_survivor", "c4_pair"}


async def test_r23_partial_failure_preserves_cached_decisions(
    tmp_path, c4_llm_manager, scripted
):
    state = actor_state(tmp_path)
    actor_answers(scripted)
    await consolidate_state(tmp_path, c4_llm_manager, state)
    state.elements["person:agents"].description = "Changed evidence"
    for question in ("c4_group", "c4_survivor", "c4_pair"):
        scripted.answers[question] = TimeoutError("unavailable")
    outcome, _ = await consolidate_state(tmp_path, c4_llm_manager, state)
    assert outcome.merges == {"external:google": "external:google-gemini"}
    scripted.question_calls.clear()
    await consolidate_state(tmp_path, c4_llm_manager, state)
    assert dict(scripted.question_calls) == {"c4_group": 2}


async def test_r23_trial_consolidates_only_cached_answers(
    tmp_path, c4_llm_manager, scripted
):
    state = actor_state(tmp_path)
    actor_answers(scripted)
    await consolidate_state(tmp_path, c4_llm_manager, state)
    state.elements["person:agents"].description = "Changed evidence"
    before = snapshot(tmp_path)
    outcome, llm = await consolidate_state(tmp_path, c4_llm_manager, state, trial=True)
    assert outcome.merges == {"external:google": "external:google-gemini"}
    assert llm.calls == 0 and snapshot(tmp_path) == before
    assert "trial" in "\n".join(outcome.report_lines)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "unknown", "value", "extra"])
async def test_pair_answers_fail_closed_without_caching(
    tmp_path, c4_llm_manager, scripted, fault
):
    from tests.code_mapper.c4.conftest import neutral_decisions

    state = actor_state(tmp_path)
    actor_answers(scripted)

    def invalid(prompt):
        result = neutral_decisions("same")(prompt)
        rows = result["decisions"]
        if fault == "missing":
            rows.pop()
        elif fault == "duplicate":
            rows.append(dict(rows[0]))
        elif fault == "unknown":
            rows[0]["id"] = "unknown"
        elif fault == "value":
            rows[0]["value"] = "equal"
        else:
            rows[0]["explanation"] = "not allowed"
        return result

    scripted.answers["c4_pair"] = invalid
    outcome, _ = await consolidate_state(tmp_path, c4_llm_manager, state)
    assert outcome.merges == {}
    assert scripted.question_calls["c4_pair"] == 2
    assert not list(
        (tmp_path / ".chunkhound/extraction/decisions/c4_pair").glob("*.json")
    )
    scripted.question_calls.clear()
    await consolidate_state(tmp_path, c4_llm_manager, state)
    assert dict(scripted.question_calls) == {"c4_pair": 2}


@pytest.mark.parametrize("question", ["c4_survivor", "c4_pair"])
async def test_consolidation_bundles_retry_independently_within_budget(
    tmp_path, c4_llm_manager, scripted, question
):
    from chunkhound.code_mapper.c4.decisions import DecisionAnswer

    state = actor_state(tmp_path)
    for element in state.elements.values():
        element.description = "evidence " * 250
    actor_answers(scripted)
    normal = scripted.answers[question]
    attempts = {}
    config = {
        **c4_llm_manager.role_config("utility"),
        "max_input_chars": 12_000,
        "max_input_tokens": 4_000,
    }
    manager = LLMManager(utility_config=config, synthesis_config=config)
    meter = C4Llm(manager, concurrency=2, trial=False)

    def bounded(prompt):
        schema = DecisionAnswer.model_json_schema()
        assert fits(prompt, schema, meter.input_limit("utility"), meter.estimate_tokens)
        assert measure_request(prompt, schema, []) <= effective_target(
            meter.input_limit("utility")
        )
        items = decision_items(prompt)
        names = tuple(
            sorted(
                member["name"]
                for item in items
                for member in (
                    item["members"]
                    if question == "c4_survivor"
                    else [item["survivor"], item["other"]]
                )
            )
        )
        attempts[names] = attempts.get(names, 0) + 1
        return {"decisions": []} if attempts[names] == 1 else normal(prompt)

    scripted.answers[question] = bounded
    first, _ = await consolidate_state(tmp_path, manager, state)
    assert first.merges == {
        "person:agents": "person:ai-assistant",
        "external:google": "external:google-gemini",
    }
    assert len(attempts) == 2 and set(attempts.values()) == {2}
    # Larger bundles and reversed input order must not reinterpret cached aliases.
    state = replace(state, elements=dict(reversed(list(state.elements.items()))))
    scripted.calls.clear()
    replay, _ = await consolidate_state(tmp_path, c4_llm_manager, state)
    assert replay.merges == first.merges and not scripted.calls


@pytest.mark.parametrize("missing", ["c4_survivor", "c4_pair"])
async def test_trial_with_warm_groups_and_missing_dependents_is_read_only(
    tmp_path, c4_llm_manager, scripted, missing
):
    state = actor_state(tmp_path)
    actor_answers(scripted)
    await consolidate_state(tmp_path, c4_llm_manager, state)
    directory = tmp_path / ".chunkhound/extraction/decisions" / missing
    for path in directory.glob("*.json"):
        if "person:agents" in path.read_text():
            path.unlink()
    before = snapshot(tmp_path)
    outcome, llm = await consolidate_state(tmp_path, c4_llm_manager, state, trial=True)
    assert outcome.merges == {"external:google": "external:google-gemini"}
    assert llm.calls == 0 and snapshot(tmp_path) == before
    assert "trial" in "\n".join(outcome.report_lines)


async def test_cached_groups_reject_removed_member_ids(
    tmp_path, c4_llm_manager, scripted
):
    state = actor_state(tmp_path)
    actor_answers(scripted)
    await consolidate_state(tmp_path, c4_llm_manager, state)
    for path in (tmp_path / ".chunkhound/extraction/decisions/c4_group").glob("*.json"):
        data = json.loads(path.read_text())
        if data["key_parts"]["item"]["kind"] == "person":
            data["answer"]["groups"][0]["members"].append("person:removed")
            path.write_text(json.dumps(data))
    scripted.question_calls.clear()
    outcome, _ = await consolidate_state(tmp_path, c4_llm_manager, state)
    assert outcome.merges == {
        "person:agents": "person:ai-assistant",
        "external:google": "external:google-gemini",
    }
    assert dict(scripted.question_calls) == {"c4_group": 1}
