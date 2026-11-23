"""MCP path diagnostics against a real indexed DuckDB, without API keys."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from chunkhound.core.types.common import Language
from chunkhound.database_factory import DatabaseServices
from chunkhound.embeddings import EmbeddingManager
from chunkhound.mcp_server.tools import execute_tool, search_impl
from chunkhound.parsers.parser_factory import create_parser_for_language
from chunkhound.providers.database.duckdb_provider import DuckDBProvider
from chunkhound.providers.database.lancedb_provider import LanceDBProvider
from chunkhound.services.indexing_coordinator import IndexingCoordinator
from chunkhound.services.search_service import SearchService
from tests.fixtures.fake_providers import FakeEmbeddingProvider


@pytest.fixture(params=["duckdb", "lancedb"])
async def indexed_scope(tmp_path, request):
    embeddings = EmbeddingManager()
    embeddings.register_provider(FakeEmbeddingProvider(), set_default=True)
    if request.param == "duckdb":
        db = DuckDBProvider(":memory:", base_directory=tmp_path)
    else:
        db = LanceDBProvider(
            tmp_path / "lance", base_directory=tmp_path, embedding_manager=embeddings
        )
    db.connect()
    coordinator = IndexingCoordinator(
        db,
        tmp_path,
        embeddings.get_provider(),
        {Language.PYTHON: create_parser_for_language(Language.PYTHON)},
    )
    try:
        for relative in ("alpha/tests/test_scope.py", "beta/tests/test_scope.py"):
            file = tmp_path / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("def scope_marker():\n    return 42\n")
            result = await coordinator.process_file(file)
            assert result["status"] == "success"
            assert not result.get("embedding_error")
        yield DatabaseServices(
            db, coordinator, SearchService(db, embeddings.get_provider()), None
        )
    finally:
        db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["search", "code_research"])
async def test_unmatched_path_is_invalid_before_search_or_research(
    indexed_scope, tool, monkeypatch
):
    # A slow database read must leave the loop free to service other requests.
    released = threading.Event()
    read_paths = indexed_scope.provider.get_scope_file_paths

    def slow_read_paths(prefix):
        assert released.wait(2), "Path validation blocked the event loop"
        return read_paths(prefix)

    monkeypatch.setattr(indexed_scope.provider, "get_scope_file_paths", slow_read_paths)
    asyncio.get_running_loop().call_later(0.02, released.set)

    def unexpected_call(*args, **kwargs):
        pytest.fail("Unmatched path must be rejected before any search or LLM call")

    monkeypatch.setattr(
        indexed_scope.search_service, "search_regex_async", unexpected_call
    )
    monkeypatch.setattr(
        indexed_scope.search_service, "search_semantic", unexpected_call
    )
    embedding_manager = SimpleNamespace(
        list_providers=lambda: ["fake"],
        get_provider=lambda: SimpleNamespace(supports_reranking=lambda: True),
    )
    llm_manager = SimpleNamespace(
        is_configured=lambda: True,
        get_utility_provider=unexpected_call,
        get_synthesis_provider=unexpected_call,
    )
    arguments = {"query": "scope_marker", "path": "missing"}
    if tool == "search":
        arguments["type"] = "regex"
    with pytest.raises(ValueError) as error:
        await execute_tool(
            tool, indexed_scope, embedding_manager, arguments, llm_manager=llm_manager
        )
    message = str(error.value)
    assert "path 'missing' matches no indexed file" in message
    assert "path segment anywhere" in message
    assert "Top-level directories: alpha/, beta/" in message


@pytest.mark.asyncio
async def test_cross_repository_search_warns_in_dict_and_mcp_text(
    indexed_scope, tmp_path
):
    (tmp_path / "alpha/.git").mkdir()
    # Worktrees have a .git file rather than a directory.
    (tmp_path / "beta/.git").write_text("gitdir: /unused/worktree\n")
    response = await search_impl(
        indexed_scope, None, "regex", "scope_marker", path="tests"
    )
    assert len(response["results"]) == 2
    warning = response["warnings"][0]
    assert "path 'tests' matches files in 2 repositories (alpha, beta)" in warning
    assert "Start the path with one repository directory" in warning
    text = await execute_tool(
        "search",
        indexed_scope,
        None,
        {"type": "regex", "query": "scope_marker", "path": "tests"},
    )
    assert text.startswith(warning + "\n\n")
    scoped = await search_impl(
        indexed_scope, None, "regex", "scope_marker", path="alpha/tests"
    )
    assert len(scoped["results"]) == 1
    assert not scoped.get("warnings")


@pytest.mark.asyncio
async def test_single_repository_layout_does_not_warn(indexed_scope, tmp_path):
    (tmp_path / ".git").mkdir()
    response = await search_impl(
        indexed_scope, None, "regex", "scope_marker", path="tests"
    )
    assert len(response["results"]) == 2
    assert not response.get("warnings")


@pytest.mark.asyncio
@pytest.mark.parametrize("vector_source", ["diff", "both", "db"])
@pytest.mark.parametrize("commit_range", [None, "HEAD~1..HEAD"])
async def test_regex_checks_database_path_on_every_route(
    indexed_scope, vector_source, commit_range
):
    with pytest.raises(ValueError, match="matches no indexed file"):
        await search_impl(
            indexed_scope,
            None,
            "regex",
            "scope_marker",
            path="missing",
            vector_source=vector_source,
            commit_range=commit_range,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_class", [DuckDBProvider, LanceDBProvider])
async def test_path_search_on_empty_index_returns_no_results(tmp_path, provider_class):
    db = provider_class(tmp_path / "empty", base_directory=tmp_path)
    db.connect()
    try:
        services = DatabaseServices(db, None, SearchService(db), None)
        response = await search_impl(
            services, None, "regex", "scope_marker", path="missing"
        )
        assert response["results"] == []
        assert not response.get("warnings")
    finally:
        db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["tests", "alpha/tests", "test_scope.py"])
async def test_semantic_path_matches_the_same_files_as_regex(indexed_scope, path):
    embeddings = EmbeddingManager()
    embeddings.register_provider(FakeEmbeddingProvider(), set_default=True)
    regex = await search_impl(
        indexed_scope, None, "regex", "scope_marker", path=path
    )
    semantic = await search_impl(
        indexed_scope, embeddings, "semantic", "scope_marker", path=path
    )
    assert semantic["results"]
    assert {row["file_path"] for row in semantic["results"]} == {
        row["file_path"] for row in regex["results"]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("indexed_scope", ["lancedb"], indirect=True)
async def test_semantic_path_is_preserved_with_threshold(indexed_scope):
    embedding_provider = FakeEmbeddingProvider()
    regex = await search_impl(indexed_scope, None, "regex", "scope_marker")
    # Identical indexed content in both repositories makes both eligible at
    # this distance threshold; only the path should exclude beta's file.
    vector = (await embedding_provider.embed_query([regex["results"][0]["content"]]))[0]
    results, _ = indexed_scope.provider.search_semantic(
        query_embedding=vector,
        provider=embedding_provider.name,
        model=embedding_provider.model,
        path_filter="alpha/tests",
        threshold=4.0,
    )
    assert {row["file_path"] for row in results} == {"alpha/tests/test_scope.py"}
