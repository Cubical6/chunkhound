"""Progress contracts through the shared handler and an in-memory MCP session."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import MagicMock

import anyio
import pytest
from mcp import ClientSession
from mcp.server.session import ServerSession
from mcp.shared.memory import create_client_server_memory_streams

from chunkhound.core.config.config import Config
from chunkhound.mcp_server.base import MCPServerBase
from chunkhound.mcp_server.tools import TOOL_REGISTRY

ANSWER = "Research answer unchanged"


class InMemoryServer(MCPServerBase):
    def _register_tools(self):
        self._register_common_tool_handlers()

    async def run(self):
        raise NotImplementedError

    async def ensure_tool_services(self, tool_name):
        # The slow research replacement does not access the database.
        return self.services


@pytest.fixture
async def progress_client(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chunkhound.mcp_server.progress.HEARTBEAT_INTERVAL_SECONDS", 0.05
    )

    async def slow_research(query: str, progress=None):
        if progress is not None:
            await asyncio.gather(
                progress.emit_event("phase", "Exploring sources", node_id=1, depth=0),
                progress.emit_event("phase", "Synthesizing answer", metadata={}),
            )
        await asyncio.sleep(0.18)
        return {"answer": ANSWER}

    monkeypatch.setitem(
        TOOL_REGISTRY,
        "code_research",
        replace(TOOL_REGISTRY["code_research"], implementation=slow_research),
    )
    server = InMemoryServer(
        Config(target_dir=tmp_path, database={"path": str(tmp_path / "test.db")})
    )
    server.services = MagicMock()
    server.embedding_manager = MagicMock()
    server.llm_manager = MagicMock()
    server._initialization_complete.set()
    server._register_tools()
    assert server.server is not None

    @asynccontextmanager
    async def connect(message_handler=None):
        async with create_client_server_memory_streams() as (
            client_streams,
            server_streams,
        ):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(
                    server.server.run,
                    *server_streams,
                    server.server.create_initialization_options(),
                )
                async with ClientSession(
                    *client_streams, message_handler=message_handler
                ) as client:
                    await client.initialize()
                    yield client
                tasks.cancel_scope.cancel()

    return connect


async def test_progress_arrives_before_unchanged_result(progress_client):
    received = []
    finished = False

    async def on_progress(progress, total, message):
        received.append((progress, message, finished))

    async with progress_client() as client:
        tools = await client.list_tools()
        research = next(tool for tool in tools.tools if tool.name == "code_research")
        assert "progress" not in research.input_schema["properties"]
        assert "progress_reporter" not in research.input_schema["properties"]
        result = await client.call_tool(
            "code_research", {"query": "architecture"}, progress_callback=on_progress
        )
        finished = True
        snapshot = list(received)
        await asyncio.sleep(0.12)
        assert received == snapshot  # No heartbeat after tool completion.
    assert not result.is_error
    assert result.content[0].text == ANSWER
    values = [value for value, _, _ in received]
    assert values and all(a < b for a, b in zip(values, values[1:]))
    assert all(not done for _, _, done in received)
    assert any("code_research still running" in message for _, message, _ in received)


async def test_research_events_become_progress_messages(progress_client):
    messages = []

    async def on_progress(progress, total, message):
        messages.append(message)

    async with progress_client() as client:
        result = await client.call_tool(
            "code_research", {"query": "architecture"}, progress_callback=on_progress
        )
    assert result.content[0].text == ANSWER
    assert "Exploring sources" in messages
    assert "Synthesizing answer" in messages


async def test_no_token_means_no_progress_or_heartbeat(progress_client, monkeypatch):
    notifications = []

    async def receive(message):
        notifications.append(message)

    def unexpected_reporter(*args, **kwargs):
        pytest.fail("Requests without a token must not create a progress reporter")

    monkeypatch.setattr(
        "chunkhound.mcp_server.base.McpProgressReporter", unexpected_reporter
    )
    async with progress_client(message_handler=receive) as client:
        result = await client.call_tool("code_research", {"query": "architecture"})
    assert not result.is_error
    assert result.content[0].text == ANSWER
    assert not notifications


async def test_progress_send_failure_does_not_change_tool_result(
    progress_client, monkeypatch
):
    attempts = []

    async def broken_send(self, progress, total=None, message=None):
        attempts.append(progress)
        raise RuntimeError("Session closed")

    monkeypatch.setattr(ServerSession, "report_progress", broken_send)

    async def on_progress(progress, total, message):
        pytest.fail("A failed send cannot deliver progress")

    async with progress_client() as client:
        result = await client.call_tool(
            "code_research", {"query": "architecture"}, progress_callback=on_progress
        )
    assert not result.is_error
    assert result.content[0].text == ANSWER
    assert len(attempts) >= 3  # Events and heartbeat all tolerate a closed transport.


async def test_hung_progress_send_does_not_stall_research(progress_client, monkeypatch):
    monkeypatch.setattr("chunkhound.mcp_server.progress.SEND_TIMEOUT_SECONDS", 0.1)
    never = asyncio.Event()
    attempts = []

    async def hung_send(self, progress, total=None, message=None):
        started = asyncio.get_running_loop().time()
        try:
            await never.wait()
        finally:
            attempts.append((message, asyncio.get_running_loop().time() - started))

    monkeypatch.setattr(ServerSession, "report_progress", hung_send)

    async def on_progress(progress, total, message):
        pass

    async with progress_client() as client:
        result = await asyncio.wait_for(
            client.call_tool(
                "code_research",
                {"query": "architecture"},
                progress_callback=on_progress,
            ),
            timeout=1.0,
        )
    assert not result.is_error
    assert result.content[0].text == ANSWER
    # Both concurrent research events finish after their send times out,
    # releasing the shared lock so research can continue.
    for phase in ("Exploring sources", "Synthesizing answer"):
        elapsed = next(duration for message, duration in attempts if message == phase)
        assert 0.08 <= elapsed < 0.5
    assert any("code_research still running" in message for message, _ in attempts)
