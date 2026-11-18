"""MCP path diagnostics against a real indexed DuckDB, without API keys."""

from types import SimpleNamespace

import pytest

from chunkhound.core.types.common import Language
from chunkhound.database_factory import DatabaseServices
from chunkhound.mcp_server.tools import execute_tool, search_impl
from chunkhound.parsers.parser_factory import create_parser_for_language
from chunkhound.providers.database.duckdb_provider import DuckDBProvider
from chunkhound.services.indexing_coordinator import IndexingCoordinator
from chunkhound.services.search_service import SearchService


@pytest.fixture
async def indexed_scope(tmp_path):
    db = DuckDBProvider(":memory:", base_directory=tmp_path)
    db.connect()
    coordinator = IndexingCoordinator(
        db,
        tmp_path,
        None,
        {Language.PYTHON: create_parser_for_language(Language.PYTHON)},
    )
    try:
        for relative in ("alpha/tests/test_scope.py", "beta/tests/test_scope.py"):
            file = tmp_path / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("def scope_marker():\n    return 42\n")
            result = await coordinator.process_file(file)
            assert result["status"] == "success"
        yield DatabaseServices(db, coordinator, SearchService(db), None)
    finally:
        db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["search", "code_research"])
async def test_unmatched_path_is_invalid_before_search_or_research(
    indexed_scope, tool, monkeypatch
):
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
async def test_both_source_allows_no_database_match(indexed_scope):
    response = await search_impl(
        indexed_scope,
        None,
        "regex",
        "scope_marker",
        path="missing",
        vector_source="both",
    )
    assert response["results"] == []


@pytest.mark.asyncio
async def test_diff_source_skips_database_scope_check(indexed_scope):
    response = await search_impl(
        indexed_scope,
        None,
        "regex",
        "scope_marker",
        path="missing",
        vector_source="diff",
        commit_range="HEAD~1..HEAD",
    )
    assert response["results"] == []
