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
