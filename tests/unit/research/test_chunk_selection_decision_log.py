"""Content-free rerank and elbow records preserve research selections."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from chunkhound.core import decision_log
from chunkhound.services.research.shared import decision_records
from chunkhound.services.research.shared.models import ResearchContext
from tests.unit.research.shared.exploration.test_parallel_strategy import (
    TestParallelExplorationStrategy as _ParallelTests,
)
from tests.unit.research.test_research_decision_log import (
    enable_log,
    records,
    reset_decision_log,  # noqa: F401 - reuse the log isolation fixture
)
from tests.unit.research.test_unified_search_bulk import make_search


@pytest.fixture
def mock_strategy():
    return _ParallelTests.mock_strategy.__wrapped__(None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["rerank", "compound_rerank", "similarity", "skipped", "failed"]
)
async def test_rerank_records_preserve_pool_and_trace(tmp_path, method):
    semantic = [
        {"chunk_id": "one", "content": "SECRET", "similarity": 0.3},
        {"chunk_id": "two", "code": "SECRET", "similarity": 0.9},
    ]
    regex = [{"chunk_id": "three", "content": "SECRET", "similarity": 0.5}]
    service = MagicMock()
    service.search_semantic_many = AsyncMock(
        side_effect=lambda *args, **kwargs: [(deepcopy(semantic), {"total": 2})]
    )
    search = make_search(service)
    search.extract_symbols_from_chunks = AsyncMock(return_value=["symbol"])
    search.search_by_symbols = AsyncMock(
        side_effect=lambda *args, **kwargs: deepcopy(regex)
    )
    provider = search._embedding_manager.get_provider()
    provider.supports_reranking.return_value = method != "skipped"
    provider.rerank = AsyncMock(
        return_value=[SimpleNamespace(index=i, score=i / 3) for i in range(3)]
    )
    if method == "failed":
        provider.rerank.side_effect = RuntimeError("offline failure")

    async def run():
        return await search.unified_search(
            "root",
            ResearchContext(root_query="root"),
            expanded_queries=["root"],
            rerank_queries=["root", "other"] if method == "compound_rerank" else None,
            skip_rerank=method == "similarity",
            node_id=7,
            depth=2,
            path_filter="src/",
        )

    without_log = await run()
    assert not (tmp_path / ".chunkhound/decisions.jsonl").exists()
    enable_log(tmp_path)
    with decision_log.trace() as trace_id:
        with_log = await run()
    assert with_log == without_log
    logged = records(tmp_path)
    assert len(logged) == 1
    record = logged[0]
    assert record["event"] == "chunk_rerank"
    assert record["schema_version"] == 1
    assert record["trace_id"] == trace_id
    assert record["method"] == method
    assert record["n_rerank_queries"] == (
        2
        if method == "compound_rerank"
        else 0
        if method in {"similarity", "skipped"}
        else 1
    )
    assert (record["n_semantic"], record["n_regex"], record["n_pool"]) == (2, 1, 3)
    assert (record["node_id"], record["depth"], record["has_path_filter"]) == (
        7,
        2,
        True,
    )
    assert [c["chunk_id"] for c in record["chunks"]] == [
        c["chunk_id"] for c in with_log
    ]
    for reference, chunk in zip(record["chunks"], with_log):
        assert reference == {
            "chunk_id": chunk["chunk_id"],
            "file_path": None,
            "start_line": None,
            "end_line": None,
            "source": "regex" if chunk["chunk_id"] == "three" else "semantic",
            "rerank_score": chunk.get("rerank_score"),
            "similarity": chunk.get("similarity"),
        }
    assert "SECRET" not in str(record)


@pytest.mark.asyncio
async def test_parallel_elbow_records_partition_without_changing_results(
    tmp_path, mock_strategy
):
    chunks = [
        {
            "chunk_id": str(i),
            "file_path": "src/test.py",
            "start_line": i + 1,
            "end_line": i + 2,
            "content": "SECRET",
            "similarity": score,
        }
        for i, score in enumerate([0.95, 0.94, 0.93, 0.92, 0.1, 0.09, 0.08, 0.07])
    ]
    before = deepcopy(chunks)
    mock_strategy._bfs.explore_raw = AsyncMock(return_value=(chunks, {}))
    mock_strategy._wide.explore_raw = AsyncMock(return_value=([], {}))
    mock_strategy._file_reader.read_files_with_budget = AsyncMock(return_value={})

    async def run():
        return await mock_strategy.explore(
            root_query="root", initial_chunks=chunks, phase1_threshold=0.5
        )

    without_log = await run()
    enable_log(tmp_path)
    with decision_log.trace() as trace_id:
        with_log = await run()
    assert with_log == without_log
    assert chunks == before
    (record,) = records(tmp_path)
    assert record["event"] == "elbow_filter"
    assert record["trace_id"] == trace_id
    assert record["stage"] == "parallel"
    assert record["score_key"] == "unified"
    stats = with_log[1]["elbow_filter"]
    for key in ("method", "reason", "cutoff_score", "elbow_index"):
        assert record[key] == stats.get(key)
    kept = {c["chunk_id"] for c in record["kept"]}
    dropped = {c["chunk_id"] for c in record["dropped"]}
    assert kept and dropped
    assert not kept & dropped
    assert kept | dropped == {c["chunk_id"] for c in chunks}
    assert record["n_candidates"] == len(chunks)
    assert record["n_kept"] == len(with_log[0])
    for partition in ("kept", "dropped"):
        assert [c["score"] for c in record[partition]] == sorted(
            [c["score"] for c in record[partition]], reverse=True
        )
        for reference in record[partition]:
            original = chunks[int(reference["chunk_id"])]
            assert reference == {
                **{
                    key: original[key]
                    for key in ("chunk_id", "file_path", "start_line", "end_line")
                },
                "score": original["similarity"],
            }
    assert "SECRET" not in str(record)


def test_disabled_records_do_not_build_payload_or_create_file(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Disabled logging must not inspect chunks or build payloads")

    monkeypatch.setattr(decision_records, "_chunk_reference", unexpected)
    monkeypatch.setattr(decision_log, "record", unexpected)
    decision_records.record_chunk_rerank(
        query="root",
        node_id=None,
        depth=None,
        path_filter=None,
        method="skipped",
        n_rerank_queries=0,
        semantic_results=None,
        regex_results=None,
        chunks=None,
    )
    decision_records.record_elbow_filter("parallel", None, None, None)
    assert not (tmp_path / ".chunkhound/decisions.jsonl").exists()
