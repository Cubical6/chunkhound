"""Topic reuse contracts on the real map/research pipeline and a fixture index."""

import json
from types import SimpleNamespace

import pytest

import chunkhound.code_mapper.service as mapper_service
from chunkhound.code_mapper.service import run_code_mapper_pipeline
from chunkhound.core.types.common import Language
from chunkhound.database_factory import DatabaseServices
from chunkhound.embeddings import EmbeddingManager
from chunkhound.interfaces.embedding_provider import RerankResult
from chunkhound.interfaces.llm_provider import LLMResponse
from chunkhound.llm_manager import LLMManager
from chunkhound.parsers.parser_factory import create_parser_for_language
from chunkhound.providers.database.duckdb_provider import DuckDBProvider
from chunkhound.services.embedding_service import EmbeddingService
from chunkhound.services.extraction.dev_cache import DevCache
from chunkhound.services.indexing_coordinator import IndexingCoordinator
from chunkhound.services.search_service import SearchService
from tests.fixtures.fake_providers import FakeEmbeddingProvider, FakeLLMProvider


class TopicEmbeddings(FakeEmbeddingProvider):
    """Orthogonal topics at the external embedding/reranking boundary."""

    base_url = "https://unused.invalid"

    def _generate_deterministic_vector(self, text):
        sign = -1.0 if "beta" in text.lower() else 1.0
        return [sign, *([0.0] * (self._dims - 1))]

    async def rerank(self, query, documents, top_k=None):
        topic = "beta" if "beta" in query.lower() else "alpha"
        results = [
            RerankResult(index=i, score=0.99 if topic in doc.lower() else 0.0)
            for i, doc in enumerate(documents)
        ]
        return sorted(results, key=lambda r: -r.score)[:top_k]


class TopicProvider(FakeLLMProvider):
    def __init__(self, model):
        super().__init__(model=model)
        self.calls = []

    async def complete(self, prompt, system=None, **kwargs):
        self.calls.append((prompt, system))
        if "HyDE objective (override for Code Mapper)" in prompt:
            if "architectural areas first" in prompt:
                text = "1. **Alpha implementation overview** — Explain alpha."
            else:
                text = "1. **Quickstart beta workflow** — Run beta."
        elif system and "atomic facts" in system.lower():
            text = "[]"
        else:
            text = (
                "# Implementation\n\nThe function returns its configured value [1]. "
                "The workflow uses a single return statement without external "
                "dependencies or additional configuration [1]."
            )
        return LLMResponse(content=text, tokens_used=20, model=self.model)

    async def complete_structured(self, prompt, json_schema, system=None, **kwargs):
        self.calls.append((prompt, system))
        # The fixture has no further questions; all research/synthesis is real.
        return {"questions": []}


@pytest.fixture
async def mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("CHUNKHOUND_RESEARCH_ALGORITHM", "v1")
    monkeypatch.setenv("CHUNKHOUND_RESEARCH_QUERY_EXPANSION_ENABLED", "false")
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("alpha", "beta"):
        (repo / f"{name}.py").write_text(
            f'def {name}_value():\n    """Return the {name} workflow value."""\n'
            f'    return "{name} configured value"\n'
        )
    embedding = TopicEmbeddings()
    embeddings = EmbeddingManager()
    embeddings.register_provider(embedding, set_default=True)
    utility = TopicProvider("utility-v1")
    synthesis = TopicProvider("synthesis-v1")
    plan = TopicProvider("plan-v1")
    monkeypatch.setattr(
        LLMManager,
        "_create_provider",
        lambda self, config: utility if config["model"] == "utility" else synthesis,
    )
    manager = LLMManager({"model": "utility"}, {"model": "synthesis"})
    db = DuckDBProvider(":memory:", base_directory=repo)
    db.connect()
    coordinator = IndexingCoordinator(
        db,
        repo,
        embedding,
        {Language.PYTHON: create_parser_for_language(Language.PYTHON)},
    )
    await coordinator.process_directory(repo, patterns=["**/*.py"], exclude_patterns=[])
    await coordinator.generate_missing_embeddings()
    services = DatabaseServices(
        provider=db,
        indexing_coordinator=coordinator,
        search_service=SearchService(db, embedding),
        embedding_service=EmbeddingService(db, embedding),
    )

    async def run(*, enabled=True, **overrides):
        kwargs = dict(
            services=services,
            embedding_manager=embeddings,
            llm_manager=manager,
            target_dir=repo,
            scope_path=repo,
            scope_label="/",
            path_filter=None,
            comprehensiveness="minimal",
            max_points=2,
            out_dir=None,
            map_hyde_provider=plan,
            poi_jobs=2,
            dev_cache=DevCache(repo, enabled=enabled),
        )
        kwargs.update(overrides)
        return await run_code_mapper_pipeline(**kwargs)

    fixture = SimpleNamespace(
        run=run,
        db=db,
        repo=repo,
        utility=utility,
        synthesis=synthesis,
        plan=plan,
        services=services,
    )
    try:
        yield fixture
    finally:
        db.disconnect()


def calls(mapping):
    return tuple(
        len(p.calls) for p in (mapping.plan, mapping.utility, mapping.synthesis)
    )


async def test_dev_cache_second_run_makes_no_llm_calls(mapping):
    first = await mapping.run()
    assert len(first.poi_sections) == 2, first.failed_poi_sections
    assert not first.failed_poi_sections
    assert [set(r["metadata"]["sources"]["files"]) for _, r in first.poi_sections] == [
        {"alpha.py"},
        {"beta.py"},
    ]
    cold_calls = calls(mapping)
    assert all(cold_calls)
    second = await mapping.run()
    assert calls(mapping) == cold_calls
    assert second.poi_sections == first.poi_sections
    assert (
        "topics 2 reused / 0 re-researched (evidence changed) / 0 new"
        in second.topic_cache_report
    )
    assert "run chunkhound index after code changes" in second.topic_cache_report


async def test_changed_evidence_file_reresearches_only_that_topic(mapping):
    await mapping.run()
    previous = calls(mapping)
    file = mapping.db.get_file_by_path("alpha.py")
    mapping.db.update_file(file["id"], content_hash="changed-indexed-hash")
    second = await mapping.run()
    assert len(mapping.plan.calls) == previous[0]
    assert len(mapping.synthesis.calls) == previous[2] + 1
    assert (
        "topics 1 reused / 1 re-researched (evidence changed) / 0 new"
        in second.topic_cache_report
    )
    assert calls(mapping)[1] > previous[1]
    previous = calls(mapping)
    await mapping.run()
    assert calls(mapping) == previous


@pytest.mark.parametrize("provider", ["utility", "synthesis"])
async def test_prompt_or_provider_change_misses(mapping, provider):
    await mapping.run()
    getattr(mapping, provider)._model = "different-model"
    previous = calls(mapping)
    result = await mapping.run()
    assert calls(mapping)[0] == previous[0]  # HyDE provider did not change.
    assert calls(mapping)[2] == previous[2] + 2
    assert (
        "topics 0 reused / 0 re-researched (evidence changed) / 2 new"
        in result.topic_cache_report
    )


@pytest.mark.parametrize("change", ["prompt", "missing_source"])
async def test_research_source_changes_invalidate_topics(
    mapping, tmp_path, monkeypatch, change
):
    # Simulate an installed source tree at the filesystem boundary; the actual
    # map/research code and the manifest hashing implementation stay in use.
    installation = tmp_path / "installation"
    source = installation / "chunkhound/services/prompts/inline.py"
    for relative in (
        "chunkhound/services/prompts/inline.py",
        "chunkhound/services/research/inline.py",
        "chunkhound/services/deep_research_service.py",
    ):
        path = installation / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# research version one\n")
    monkeypatch.setattr(
        mapper_service,
        "__file__",
        str(installation / "chunkhound/code_mapper/service.py"),
    )
    await mapping.run()
    previous = calls(mapping)
    if change == "prompt":
        source.write_text("# research version two\n")
    else:
        source.unlink()
    result = await mapping.run()
    assert calls(mapping)[0] == previous[0]
    assert calls(mapping)[2] == previous[2] + 2
    if change == "missing_source":
        assert "topic cache disabled" in result.topic_cache_report
        previous = calls(mapping)
        await mapping.run()
        assert calls(mapping)[2] == previous[2] + 2
    else:
        assert "topics 0 reused" in result.topic_cache_report


async def test_deleted_indexed_evidence_is_not_reused(mapping):
    await mapping.run()
    mapping.db.delete_file_completely("alpha.py")
    previous = calls(mapping)
    result = await mapping.run()
    assert calls(mapping)[0] == previous[0]
    assert len(result.failed_poi_sections) == 1
    assert len(result.poi_sections) == 1
    assert "beta" in result.poi_sections[0][0].text.lower()
    assert "topics 1 reused / 1 re-researched" in result.topic_cache_report


async def test_dev_cache_off_never_reads_or_writes_topics(mapping):
    await mapping.run(enabled=False)
    assert not (mapping.repo / ".chunkhound" / "extraction").exists()
    await mapping.run()
    previous = calls(mapping)
    await mapping.run(enabled=False)
    assert all(after > before for after, before in zip(calls(mapping), previous))


async def test_unrelated_disk_changes_reuse_last_indexed_evidence(mapping):
    await mapping.run()
    previous = calls(mapping)
    (mapping.repo / "alpha.py").write_text("# changed but not indexed yet\n")
    (mapping.repo / "unrelated.py").write_text("# unrelated new code\n")
    await mapping.run()
    assert calls(mapping) == previous


@pytest.mark.parametrize("content_hash", [None, ""])
async def test_missing_evidence_hash_never_reuses_or_stores_topic(
    mapping, content_hash
):
    await mapping.run()
    file = mapping.db.get_file_by_path("alpha.py")
    mapping.db.execute_query(
        "UPDATE files SET content_hash = ? WHERE id = ?", [content_hash, file["id"]]
    )
    previous = calls(mapping)
    result = await mapping.run()
    assert calls(mapping)[2] == previous[2] + 1
    assert "topics 1 reused / 1 re-researched" in result.topic_cache_report
    previous = calls(mapping)
    await mapping.run()
    assert calls(mapping)[2] == previous[2] + 1


async def test_absolute_evidence_paths_are_normalized(mapping):
    await mapping.run()
    # Exercise the on-disk public cache format with absolute source paths, which
    # some research readers return. Evidence must still use index-relative paths.
    entries = list(
        (mapping.repo / ".chunkhound/extraction/decisions/topic_research").glob(
            "*.json"
        )
    )
    assert len(entries) == 2
    for path in entries:
        payload = json.loads(path.read_text())
        # DecisionStore wraps the DevCache envelope in its answer field.
        envelope = payload["answer"]["answer"]
        result = envelope["result"]
        files = result["metadata"]["sources"]["files"]
        result["metadata"]["sources"]["files"] = [str(mapping.repo / f) for f in files]
        path.write_text(json.dumps(payload))
    previous = calls(mapping)
    await mapping.run()
    assert calls(mapping) == previous
