"""Contracts for configuring MCP search independently of code research."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from chunkhound.core.config.config import Config
from chunkhound.core.config.mcp_config import MCPConfig
from chunkhound.mcp_server.tools import TOOL_REGISTRY, execute_tool, search_impl


@pytest.fixture
def search_dependencies():
    search_service = SimpleNamespace(
        search_semantic=AsyncMock(return_value=([], {"has_more": False})),
    )
    services = SimpleNamespace(search_service=search_service)
    embedding_manager = Mock()
    embedding_manager.list_providers.return_value = ["test"]
    embedding_manager.get_provider.return_value = SimpleNamespace(
        name="test", model="test-model"
    )
    return services, embedding_manager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        (None, None),
        ("auto", None),
        ("single_hop", "single_hop"),
        ("multi_hop", "multi_hop"),
    ],
)
@pytest.mark.parametrize("dispatch", [False, True], ids=["direct", "execute_tool"])
async def test_mcp_search_uses_configured_strategy(
    search_dependencies, strategy, expected, dispatch
):
    services, embedding_manager = search_dependencies
    config = (
        Config(
            mcp={"search_strategy": strategy},
            skip_layers={"env", "global", "local_config", "config_file", "cli"},
        )
        if strategy is not None
        else None
    )
    arguments = {"type": "semantic", "query": "retry logic"}
    if dispatch:
        await execute_tool(
            "search", services, embedding_manager, arguments, config=config
        )
    else:
        await search_impl(services, embedding_manager, **arguments, config=config)

    assert (
        services.search_service.search_semantic.await_args.kwargs["force_strategy"]
        == expected
    )


def test_search_schema_does_not_expose_config():
    schema = TOOL_REGISTRY["search"].parameters
    assert "config" not in schema["properties"]
    assert "config" not in schema.get("required", [])


def test_mcp_search_strategy_defaults_to_auto():
    assert MCPConfig().search_strategy == "auto"


@pytest.mark.parametrize("strategy", ["auto", "single_hop", "multi_hop"])
def test_mcp_search_strategy_from_env(monkeypatch, strategy):
    monkeypatch.setenv("CHUNKHOUND_MCP__SEARCH_STRATEGY", strategy)
    config = Config(skip_layers={"global", "local_config", "config_file", "cli"})
    assert config.mcp.search_strategy == strategy


@pytest.mark.parametrize(
    ("env_var", "field"),
    [
        ("CHUNKHOUND_MCP__SEARCH_STRATEGY", "search_strategy"),
        ("CHUNKHOUND_MCP__TRANSPORT", "transport"),
    ],
)
def test_invalid_mcp_env_literal_is_rejected(monkeypatch, env_var, field):
    monkeypatch.setenv(env_var, "invalid")
    with pytest.raises(ValidationError, match=field):
        Config(skip_layers={"global", "local_config", "config_file", "cli"})


def test_mcp_search_strategy_from_json(tmp_path):
    (tmp_path / ".chunkhound.json").write_text(
        json.dumps({"mcp": {"search_strategy": "single_hop"}})
    )
    config = Config(
        target_dir=tmp_path,
        skip_layers={"env", "global", "config_file", "cli"},
    )
    assert config.mcp.search_strategy == "single_hop"
