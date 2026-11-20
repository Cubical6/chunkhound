"""Opt-in research logging preserves results and failures with real orchestration."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from chunkhound.core import decision_log
from chunkhound.core.config.decision_log_config import DecisionLogConfig
from chunkhound.interfaces.llm_provider import LLMProvider, LLMResponse
from chunkhound.llm_manager import LLMManager
from chunkhound.services.research.factory import ResearchServiceFactory
from chunkhound.services.research.shared.gap_detection import GapDetectionService
from chunkhound.services.research.shared.gap_models import UnifiedGap
from chunkhound.services.research.shared.models import ResearchContext
from chunkhound.services.research.v1.pluggable_research_service import (
    PluggableResearchService,
)
from chunkhound.services.research.v1.question_generator import QuestionGenerator
from tests.fixtures.fake_providers import FakeLLMProvider
from tests.unit.research.test_source_provenance import _research_service


@pytest.fixture(autouse=True)
def reset_decision_log(tmp_path):
    decision_log.configure(None, tmp_path)
    yield
    decision_log.configure(None, tmp_path)


def enable_log(tmp_path):
    decision_log.configure(
        SimpleNamespace(decision_log=DecisionLogConfig(enabled=True)), tmp_path
    )


def records(tmp_path):
    return [
        json.loads(line)
        for line in (tmp_path / ".chunkhound/decisions.jsonl").read_text().splitlines()
    ]


def factory_service(tmp_path, llm_manager, branch, algorithm):
    # Reuse the existing database/embedding stack and real research pipeline.
    base = _research_service(tmp_path, llm_manager, branch)
    config = base._config.model_copy(
        update={"algorithm": algorithm, "import_resolution_enabled": False}
    )
    return ResearchServiceFactory.create(
        SimpleNamespace(research=config),
        base._db_services,
        base._embedding_manager,
        llm_manager,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "branch,mode", [("single", "single_pass"), ("reduce", "map_reduce")]
)
async def test_research_log_preserves_results(
    tmp_path, capturing_llm_manager, monkeypatch, branch, mode
):
    llm_manager, provider = capturing_llm_manager
    provider._responses = {
        "extract atomic facts": "[]",
        "": (
            "The API delegates storage to the store implementation [1]. "
            "The store persists the request and returns a concrete result [2]. "
            "Both modules participate in the request path [1][2]."
        ),
    }
    service = factory_service(tmp_path, llm_manager, branch, "v1")
    original_usage = llm_manager.get_usage_stats
    usage_calls = []

    def unexpected_usage():
        usage_calls.append(True)
        raise AssertionError("Disabled logging must not request usage stats")

    # No counters should be collected when logging is disabled.
    with monkeypatch.context() as patch:
        patch.setattr(llm_manager, "get_usage_stats", unexpected_usage)
        without_log = await service.deep_research("Explain the API")
    assert usage_calls == []
    assert not (tmp_path / ".chunkhound").exists()

    before = original_usage()
    enable_log(tmp_path)
    with_log = await service.deep_research("Explain the API")
    after = original_usage()
    assert with_log == without_log
    runs = [record for record in records(tmp_path) if record["event"] == "research_run"]
    assert len(runs) == 1
    run = runs[0]
    assert run["algorithm"] == "v1"
    assert run["synthesis_mode"] == mode
    assert run["num_clusters"] == (1 if mode == "single_pass" else 2)
    assert run["success"] is True
    assert run["error_type"] is None
    assert run["answer_chars"] == len(with_log["answer"])
    assert run["is_follow_up"] is False
    assert run["has_path_filter"] is False
    assert run["elapsed_s"] >= 0
    for key in ("depth_reached", "nodes_explored", "chunks_analyzed"):
        assert run[key] == with_log["metadata"][key]
    expected_usage = {}
    for role in ("utility", "synthesis"):
        counters = {
            key: value - before[role].get(key, 0)
            for key, value in after[role].items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if counters:
            expected_usage[role] = counters
    assert run["llm_usage"] == expected_usage
    # The fake bypasses SearchService, but research selection is still recorded.
    logged = records(tmp_path)
    assert [record["event"] for record in logged] == [
        "chunk_rerank",
        "elbow_filter",
        "research_run",
    ]
    assert all(record["trace_id"] == run["trace_id"] for record in logged)


@pytest.mark.asyncio
@pytest.mark.parametrize("overlapping", [False, True])
@pytest.mark.parametrize("shared_roles", [False, True])
async def test_research_runs_log_only_their_own_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overlapping: bool,
    shared_roles: bool,
) -> None:
    enable_log(tmp_path)
    utility_provider = FakeLLMProvider()
    provider = utility_provider if shared_roles else FakeLLMProvider()

    def create_provider(self: LLMManager, config: dict[str, Any]) -> LLMProvider:
        return utility_provider if config["model"] == "utility" else provider

    monkeypatch.setattr(LLMManager, "_create_provider", create_provider)
    llm_manager = LLMManager(
        {"provider": "fake", "model": "utility"},
        {"provider": "fake", "model": "synthesis"},
    )
    service = PluggableResearchService(
        database_services=MagicMock(),
        embedding_manager=MagicMock(),
        llm_manager=llm_manager,
        exploration_strategy=MagicMock(),
        algorithm="v1",
    )
    own_tokens = {"query A": 100, "query B": 7, "unrelated": 13}
    a_started = asyncio.Event()
    b_done = asyncio.Event()

    async def complete(prompt: str, **kwargs: Any) -> LLMResponse:
        # Fake only the provider boundary; use its production accounting API.
        tokens = own_tokens[prompt]
        provider._record_usage(requests=1, tokens=tokens)
        return LLMResponse(content=prompt, tokens_used=tokens, model="fake-gpt")

    async def research(
        query: str,
        previous_query: str | None,
        decision_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Real map/reduce uses child tasks too: their accounting must be shared
        # with their run, not with concurrently executing runs on this manager.
        await asyncio.gather(asyncio.create_task(provider.complete(query)))
        if overlapping:
            if query == "query A":
                a_started.set()
                await b_done.wait()
            else:
                b_done.set()
        return {"answer": query, "metadata": {}}

    monkeypatch.setattr(provider, "complete", complete)
    monkeypatch.setattr(service, "_deep_research_impl", research)
    # Lifetime usage before/after a run, including an unrelated overlapping
    # request, must not be attributed to that run.
    await provider.complete("unrelated")
    if overlapping:

        async def run_b() -> dict[str, Any]:
            await a_started.wait()
            await provider.complete("unrelated")
            return await service.deep_research("query B")

        await asyncio.wait_for(
            asyncio.gather(service.deep_research("query A"), run_b()), timeout=5
        )
    else:
        await service.deep_research("query A")
        await service.deep_research("query B")
    await provider.complete("unrelated")

    run_records = [
        record for record in records(tmp_path) if record["event"] == "research_run"
    ]
    assert len(run_records) == 2
    runs = {record["query"]: record for record in run_records}
    assert set(runs) == {"query A", "query B"}
    for query in runs:
        synthesis_usage = {
            "requests_made": 1,
            "total_tokens": own_tokens[query],
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
        assert runs[query]["llm_usage"] == {
            "synthesis": synthesis_usage,
            "utility": (
                synthesis_usage if shared_roles else {key: 0 for key in synthesis_usage}
            ),
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("algorithm", ["v1", "v2", "v3", "unknown"])
async def test_research_failure_is_logged_and_propagated(
    tmp_path, llm_manager, monkeypatch, algorithm
):
    service = factory_service(tmp_path, llm_manager, "single", algorithm)
    failure = RuntimeError("external database unavailable")

    async def failed_search(**kwargs):
        # Mirror SearchService's per-search trace because the fake replaces it.
        with decision_log.trace():
            decision_log.record("search_probe", {})
        raise failure

    def failed_usage():
        raise RuntimeError("provider usage unavailable")

    monkeypatch.setattr(
        service._db_services.search_service, "search_semantic", failed_search
    )
    monkeypatch.setattr(llm_manager, "get_usage_stats", failed_usage)
    enable_log(tmp_path)
    with pytest.raises(RuntimeError) as caught:
        await service.deep_research(
            "Explain the API", previous_query="private prior topic"
        )
    assert caught.value is failure
    logged = records(tmp_path)
    probes = [record for record in logged if record["event"] == "search_probe"]
    (run,) = [record for record in logged if record["event"] == "research_run"]
    assert probes
    assert all(probe["parent_trace_id"] == run["trace_id"] for probe in probes)
    assert all(probe["trace_id"] != run["trace_id"] for probe in probes)
    assert run["parent_trace_id"] is None
    assert run["algorithm"] == ("v1" if algorithm == "unknown" else algorithm)
    assert run["success"] is False
    assert run["error_type"] == "RuntimeError"
    assert run["is_follow_up"] is True
    assert "private prior topic" not in json.dumps(run)
    assert run["llm_usage"] == {}
    for key in (
        "answer_chars",
        "depth_reached",
        "nodes_explored",
        "chunks_analyzed",
        "num_clusters",
        "synthesis_mode",
    ):
        assert run[key] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,scores",
    [
        ("3, 1, 99", [0.1, 0.9, 0.8, 0.2]),
        ("invalid output", [0.5, 0.5, 0.5]),
        ("failure", [0.0] * 5),
        ("2", []),
        ("2", [0.7]),
        ("2", [0.9, 0.8, 0.7, 0.6, 0.5]),
    ],
)
async def test_decisions_share_run_trace_and_preserve_selections(
    tmp_path, capturing_llm_manager, monkeypatch, response, scores
):
    manager, provider = capturing_llm_manager
    provider._responses = {
        "extract atomic facts": "[]",
        "": (
            "The API delegates storage to the store implementation [1]. "
            "The store persists the request and returns a concrete result [2]. "
            "Both modules participate in the request path [1][2]."
        ),
    }
    service = factory_service(tmp_path, manager, "single", "v1")
    generator = QuestionGenerator(manager)
    selector = GapDetectionService(
        llm_manager=manager,
        embedding_manager=service._embedding_manager,
        db_services=service._db_services,
        config=service._config.model_copy(update={"min_gaps": 1, "max_gaps": 4}),
    )
    questions = ["How is storage called?", "Where is validation?", "Who owns the API?"]
    gaps = [
        UnifiedGap(query=f"Gap {i}", sources=[], vote_count=1, score=score)
        for i, score in enumerate(scores)
    ]
    selections = []
    original_search = service._db_services.search_service.search_semantic

    async def failed_filter(*args, **kwargs):
        raise RuntimeError("utility provider unavailable")

    async def search_with_decisions(**kwargs):
        # The existing fake replaces the search boundary. Execute the real
        # selectors here so deep_research owns the trace, not the test.
        with monkeypatch.context() as patch:
            if response == "failure":
                patch.setattr(provider, "complete", failed_filter)
            else:
                patch.setattr(provider, "_responses", {"": response})
            kept = await generator.filter_relevant_followups(
                questions,
                "Explain the API",
                "Explain storage",
                ResearchContext(root_query="Explain the API", ancestors=[]),
            )
        selected = selector._select_gaps_by_elbow(gaps)
        selections.append((kept, selected))
        return await original_search(**kwargs)

    monkeypatch.setattr(
        service._db_services.search_service, "search_semantic", search_with_decisions
    )
    without_log = await service.deep_research("Explain the API")
    assert not (tmp_path / ".chunkhound").exists()
    disabled_selections = selections[:]
    selections.clear()
    enable_log(tmp_path)
    with_log = await service.deep_research("Explain the API")
    assert with_log == without_log
    assert selections == disabled_selections
    assert selections

    logged = records(tmp_path)
    (run,) = [r for r in logged if r["event"] == "research_run"]
    followups = [r for r in logged if r["event"] == "followup_filter"]
    gap_records = [r for r in logged if r["event"] == "gap_selection"]
    assert len(followups) == len(gap_records) == len(selections)
    common = {
        "schema_version",
        "ts",
        "event",
        "trace_id",
        "parent_trace_id",
        "chunkhound_version",
    }
    for followup, gap_record, (kept, selected) in zip(
        followups, gap_records, selections, strict=True
    ):
        for record in (followup, gap_record):
            assert record["schema_version"] == 1
            assert record["ts"]
            assert record["chunkhound_version"]
            assert record["trace_id"] == run["trace_id"]
            assert record["parent_trace_id"] == run["parent_trace_id"]
        assert set(followup) == common | {
            "n_candidates",
            "n_kept",
            "candidates",
            "kept",
            "fallback",
        }
        assert followup["n_candidates"] == len(questions)
        assert followup["n_kept"] == len(kept)
        assert followup["candidates"] == questions
        assert [questions[i] for i in followup["kept"]] == kept
        assert followup["fallback"] is (response in ("invalid output", "failure"))
        assert set(gap_record) == common | {
            "n_candidates",
            "n_selected",
            "scores",
            "elbow_index",
            "selected",
        }
        assert gap_record["n_candidates"] == len(gaps)
        assert gap_record["n_selected"] == len(selected)
        assert gap_record["scores"] == sorted(scores, reverse=True)
        # Gap indices address the descending score list, not the input order.
        sorted_gaps = sorted(gaps, key=lambda gap: gap.score, reverse=True)
        assert [sorted_gaps[i] for i in gap_record["selected"]] == selected
        assert gap_record["elbow_index"] is None or isinstance(
            gap_record["elbow_index"], int
        )
