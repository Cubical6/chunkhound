"""Research provenance must describe synthesized context, not retrieval breadth."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from chunkhound.api.cli.commands.code_mapper import _topic_sources
from chunkhound.code_mapper.c4.topic_coverage import compute_coverage
from chunkhound.code_mapper.models import CodeMapperPOI
from chunkhound.code_mapper.public_utils import (
    is_empty_research_result,
    merge_sources_metadata,
)
from chunkhound.code_mapper.service import CodeMapperPipelineResult
from chunkhound.core.config.research_config import ResearchConfig
from chunkhound.database_factory import DatabaseServices
from chunkhound.embeddings import EmbeddingManager
from chunkhound.interfaces.embedding_provider import RerankResult
from chunkhound.services.research.shared.exploration import BFSExplorationStrategy
from chunkhound.services.research.v1.pluggable_research_service import (
    PluggableResearchService,
)
from tests.fixtures.fake_providers import FakeEmbeddingProvider


class _SearchResults:
    """External database search boundary; no real index is opened."""

    def __init__(self, chunks):
        self.chunks = chunks

    async def search_semantic(self, **kwargs):
        return [dict(chunk) for chunk in self.chunks], {}


class _EqualRelevanceEmbedding(FakeEmbeddingProvider):
    async def rerank(self, query, documents, top_k=None):
        # All retrieved candidates are equally relevant; an unreadable file
        # must still be excluded by the real synthesis source selection.
        return [RerankResult(index=index, score=1.0) for index in range(len(documents))]


def _research_service(tmp_path, llm_manager, branch):
    chunks = []
    if branch != "empty":
        for chunk_id, file_path, start, end in [
            (1, "src/store.py", 3, 4),
            (2, "src/api.py", 7, 8),
            (3, "unreadable.py", 1, 2),
            (4, "src/api.py", 2, 3),
        ]:
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                    "content": f"private source payload {chunk_id}",
                    "metadata": {},
                    "similarity": 1.0,
                }
            )
        (tmp_path / "src").mkdir()
        for name in ("api", "store"):
            content = f"# private whole-file payload {name}\n" * 10
            if branch == "reduce":
                # Real bounded clustering splits the >50k-token combined input
                # into two clusters, without mocking clustering or synthesis.
                content += f"# {name} padding\n" * 11_000
            (tmp_path / "src" / f"{name}.py").write_text(content)

    embeddings = cast(
        EmbeddingManager,
        SimpleNamespace(get_provider=lambda: _EqualRelevanceEmbedding(dims=8)),
    )
    services = cast(
        DatabaseServices,
        SimpleNamespace(
            search_service=_SearchResults(chunks),
            provider=SimpleNamespace(get_base_directory=lambda: tmp_path),
        ),
    )
    config = ResearchConfig(query_expansion_enabled=False)
    strategy = BFSExplorationStrategy(
        llm_manager, embeddings, services, config=config, max_depth=0
    )
    return PluggableResearchService(
        services, embeddings, llm_manager, strategy, config=config
    )


def _consumer_results(result):
    files, chunks, total_files, total_chunks = merge_sources_metadata([result])
    poi = CodeMapperPOI(mode="architectural", text="Provenance")
    pipeline = CodeMapperPipelineResult(
        overview_result={},
        poi_sections=[(poi, result)],
        poi_sections_indexed=[(1, poi, result)],
        failed_poi_sections=[],
        total_points_of_interest=1,
        unified_source_files=files,
        unified_chunks_dedup=chunks,
        total_files_global=total_files,
        total_chunks_global=total_chunks,
        scope_total_files=3,
        scope_total_chunks=4,
    )
    topics = _topic_sources("fixture", pipeline)
    coverage = compute_coverage(
        element_files={
            "component:api": ["src/api.py"],
            "component:store": ["src/store.py"],
            "component:unreadable": ["unreadable.py"],
        },
        direct_files={},
        topics=topics,
    )
    return files, chunks, topics, coverage


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["single", "reduce"])
async def test_research_sources_drive_legacy_counts_and_c4_coverage(
    tmp_path: Path, capturing_llm_manager, branch: str
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
    service = _research_service(tmp_path, manager, branch)

    result = await service.deep_research("provenance")
    files, chunks, topics, coverage = _consumer_results(result)

    expected_chunks = [
        {"file_path": "src/api.py", "start_line": 2, "end_line": 3},
        {"file_path": "src/api.py", "start_line": 7, "end_line": 8},
        {"file_path": "src/store.py", "start_line": 3, "end_line": 4},
    ]
    assert result["metadata"]["sources"] == {
        "files": ["src/api.py", "src/store.py"],
        "chunks": expected_chunks,
    }
    assert files == {"src/api.py": "", "src/store.py": ""}
    assert chunks == expected_chunks
    assert len(files) == 2 and len(chunks) == 3
    assert "**Files**: 2 | **Chunks**: 3" in result["answer"]
    assert "unreadable.py" not in result["answer"]
    assert result["metadata"]["chunks_analyzed"] == 4
    assert topics[0].files == ("src/api.py", "src/store.py")
    assert coverage["component:api"].status == "covered"
    assert coverage["component:api"].topics == ["fixture_arch_topic_01_provenance.md"]
    assert coverage["component:store"].topics == ["fixture_arch_topic_01_provenance.md"]
    assert coverage["component:unreadable"].status == "undescribed"
    assert coverage["component:unreadable"].topics == []


@pytest.mark.asyncio
async def test_no_context_skips_synthesis_without_inventing_provenance(
    tmp_path: Path, capturing_llm_manager
):
    manager, provider = capturing_llm_manager
    service = _research_service(tmp_path, manager, "empty")

    result = await service.deep_research("provenance")
    files, chunks, topics, coverage = _consumer_results(result)

    assert is_empty_research_result(result)
    assert result["metadata"]["skipped_synthesis"] is True
    assert result["metadata"]["chunks_analyzed"] == 0
    assert result["metadata"]["files_analyzed"] == 0
    assert "Try a more code-specific question" in result["answer"]
    assert files == {} and chunks == []
    assert topics[0].files == ()
    assert coverage["component:api"].status == "undescribed"
    assert provider.calls == []
