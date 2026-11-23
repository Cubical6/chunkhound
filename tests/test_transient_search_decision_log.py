"""Decision-log contracts for commit-scoped semantic searches."""

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chunkhound.core import decision_log
from chunkhound.core.config.decision_log_config import DecisionLogConfig
from chunkhound.services.transient_search_service import TransientSearchService
from tests.unit.transient_search_helpers import (
    keyed_embedding_manager,
    make_chunk,
    make_original,
    stream_chunks,
)


@pytest.fixture(autouse=True)
def reset_log(tmp_path: Path) -> Iterator[None]:
    decision_log.configure(None, tmp_path)
    yield
    decision_log.configure(None, tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("empty", [False, True])
async def test_commit_search_records_once_per_query_without_changing_results(
    tmp_path: Path, bulk: bool, empty: bool
) -> None:
    chunks = [] if empty else [make_chunk("target", code="private source")]
    manager = keyed_embedding_manager([1.0, 0.0], chunks, [[1.0, 0.0]])
    manager.get_provider.return_value = SimpleNamespace(name="test", model="test-model")
    service = TransientSearchService(
        make_original(),
        stream_chunks(chunks),
        "diff",
        manager,
        source_revision="abc123",
    )
    log_path = tmp_path / ".chunkhound" / "decisions.jsonl"

    async def search() -> Any:
        if bulk:
            return await service.search_semantic_many(
                ["query", "other"], page_size=3, path_filter="src/"
            )
        return await service.search_semantic("query", page_size=3, path_filter="src/")

    disabled_result = await search()
    assert not log_path.parent.exists()
    decision_log.configure(
        SimpleNamespace(decision_log=DecisionLogConfig(enabled=True)), tmp_path
    )
    with decision_log.trace() as parent:
        enabled_result = await search()
    assert enabled_result == disabled_result
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(records) == (2 if bulk else 1)
    assert [record["query"] for record in records] == (
        ["query", "other"] if bulk else ["query"]
    )
    for record in records:
        assert record["event"] == "single_hop_search"
        assert record["vector_source"] == "diff"
        assert record["strategy_reason"] == "diff"
        assert record["page_size"] == 3
        assert record["has_path_filter"] is True
        assert record["provider"] == "test"
        assert record["model"] == "test-model"
        assert record["n_returned"] == (0 if empty else 1)
        assert record["elapsed_s"] >= 0
        assert record["parent_trace_id"] == parent
    assert "private source" not in log_path.read_text()

    before = log_path.read_bytes()
    decision_log.configure(None, tmp_path)
    assert await search() == disabled_result
    assert log_path.read_bytes() == before
