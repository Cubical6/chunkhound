"""Progress contracts through shared handlers and real MCP transports."""

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import anyio
import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.server.session import ServerSession
from mcp.shared.memory import create_client_server_memory_streams

from chunkhound.core.config.config import Config
from chunkhound.mcp_server.base import MCPServerBase
from chunkhound.mcp_server.http_server import HttpMCPServer
from chunkhound.mcp_server.progress import (
    MIN_PROGRESS_INTERVAL_SECONDS,
    McpProgressReporter,
)
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
async def slow_research_tool(monkeypatch):
    finished = asyncio.Event()
    may_finish = asyncio.Event()
    may_finish.set()
    monkeypatch.setattr(
        "chunkhound.mcp_server.progress.HEARTBEAT_INTERVAL_SECONDS", 0.05
    )
    monkeypatch.setattr(
        "chunkhound.mcp_server.progress.MIN_PROGRESS_INTERVAL_SECONDS", 0.02
    )

    async def slow_research(query: str, progress=None):
        if progress is not None:
            await asyncio.gather(
                progress.emit_event("phase", "Exploring sources", node_id=1, depth=0),
                progress.emit_event("phase", "Synthesizing answer", metadata={}),
            )
        await asyncio.sleep(0.18)
        await may_finish.wait()
        finished.set()
        return {"answer": ANSWER}

    monkeypatch.setitem(
        TOOL_REGISTRY,
        "code_research",
        replace(TOOL_REGISTRY["code_research"], implementation=slow_research),
    )
    return finished, may_finish


@pytest.fixture
async def progress_client(slow_research_tool, tmp_path):
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


@pytest.fixture
async def progress_http_url(slow_research_tool, monkeypatch, tmp_path):
    server = HttpMCPServer(
        Config(target_dir=tmp_path, database={"path": str(tmp_path / "http.db")})
    )
    server.services = MagicMock()
    server.embedding_manager = MagicMock()
    server.llm_manager = MagicMock()
    # Only replace database/provider startup; use the production HTTP app,
    # session lifecycle, handler registration and socket transport.
    monkeypatch.setattr(server, "initialize", AsyncMock())
    monkeypatch.setattr(server, "cleanup", AsyncMock())
    monkeypatch.setattr(
        server, "ensure_tool_services", AsyncMock(return_value=server.services)
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        host, port = listener.getsockname()
        http_server = uvicorn.Server(
            uvicorn.Config(server._build_app(), log_level="error", lifespan="on")
        )
        task = asyncio.create_task(http_server.serve(sockets=[listener]))
        try:
            with anyio.fail_after(5):
                while not http_server.started:
                    if task.done():
                        await task
                        pytest.fail("HTTP server exited before startup")
                    await asyncio.sleep(0.01)
            yield f"http://{host}:{port}/mcp"
        finally:
            http_server.should_exit = True
            try:
                await asyncio.wait_for(task, timeout=5)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


async def test_http_request_sse_stream_delivers_progress_before_result(
    progress_http_url, slow_research_tool
):
    finished, may_finish = slow_research_tool
    may_finish.clear()  # Keep research alive until the client sees a heartbeat.
    headers = {"Accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient(headers=headers, timeout=5, trust_env=False) as client:
        initialized = await client.post(
            progress_http_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "progress-test", "version": "1"},
                },
            },
        )
        initialized.raise_for_status()
        client.headers["Mcp-Session-Id"] = initialized.headers["Mcp-Session-Id"]
        client.headers["MCP-Protocol-Version"] = "2025-11-25"
        notified = await client.post(
            progress_http_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        notified.raise_for_status()
        frames = []
        async with client.stream(
            "POST",
            progress_http_url,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "code_research",
                    "arguments": {"query": "architecture"},
                    "_meta": {"progressToken": "http-research"},
                },
            },
        ) as response:
            response.raise_for_status()
            assert "text/event-stream" in response.headers["content-type"]
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                frame = json.loads(line.removeprefix("data:").strip())
                if not frames:
                    # Prove live delivery, not merely ordered frames buffered
                    # until the research call has finished.
                    assert frame.get("method") == "notifications/progress"
                    assert not finished.is_set()
                frames.append(frame)
                if "still running" in frame.get("params", {}).get("message", ""):
                    may_finish.set()

        progress = frames[:-1]
        assert len(progress) >= 2  # Latest research phase plus an idle heartbeat.
        assert all(frame["method"] == "notifications/progress" for frame in progress)
        params = [frame["params"] for frame in progress]
        assert all(p["progressToken"] == "http-research" for p in params)
        values = [p["progress"] for p in params]
        assert all(a < b for a, b in zip(values, values[1:]))
        messages = [p["message"] for p in params]
        assert "Synthesizing answer" in messages
        assert any("code_research still running" in message for message in messages)
        assert frames[-1]["id"] == 2
        result = frames[-1]["result"]
        assert not result.get("isError", False)
        assert result["content"][0]["text"] == ANSWER
        terminated = await client.delete(progress_http_url)
        terminated.raise_for_status()


async def test_progress_arrives_before_unchanged_result(
    progress_client, slow_research_tool
):
    _, may_finish = slow_research_tool
    may_finish.clear()
    received = []
    finished = False

    async def on_progress(progress, total, message):
        received.append((progress, message, finished))
        if "still running" in message:
            may_finish.set()

    async with progress_client() as client:
        tools = await client.list_tools()
        research = next(tool for tool in tools.tools if tool.name == "code_research")
        assert "progress" not in research.input_schema["properties"]
        assert "progress_reporter" not in research.input_schema["properties"]
        with anyio.fail_after(5):
            result = await client.call_tool(
                "code_research",
                {"query": "architecture"},
                progress_callback=on_progress,
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
    assert "Synthesizing answer" in messages  # Concurrent events are latest-wins.


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
    assert attempts  # A closed transport does not affect the tool result.


async def test_hung_progress_send_does_not_stall_research(progress_client, monkeypatch):
    monkeypatch.setattr("chunkhound.mcp_server.progress.SEND_TIMEOUT_SECONDS", 60.0)
    never = asyncio.Event()
    send_started = asyncio.Event()

    async def hung_send(self, progress, total=None, message=None):
        send_started.set()
        await never.wait()

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
            timeout=5.0,
        )
    assert not result.is_error
    assert result.content[0].text == ANSWER
    assert send_started.is_set()  # Research finished without waiting for the 60 s send.


async def test_emit_event_returns_while_transport_is_hung(monkeypatch):
    monkeypatch.setattr("chunkhound.mcp_server.progress.SEND_TIMEOUT_SECONDS", 60.0)
    sending = anyio.Event()
    send_stopped = anyio.Event()

    async def hung_send(progress, total, message):
        sending.set()
        try:
            await anyio.sleep_forever()
        finally:
            send_stopped.set()

    reporter = McpProgressReporter(hung_send)
    async with reporter.heartbeat("code_research"):
        await reporter.report("Starting")
        with anyio.fail_after(5):
            await sending.wait()
            # Model the shared research lock, including concurrent emitters.
            lock = asyncio.Lock()

            async def emit(index):
                async with lock:
                    await reporter.emit_event("phase", f"Phase {index}")

            await asyncio.gather(*(emit(index) for index in range(100)))
        assert not send_stopped.is_set()
    assert send_stopped.is_set()


async def test_event_burst_is_throttled_and_latest_message_wins():
    frames = []
    delivered = asyncio.Queue()

    async def send(progress, total, message):
        frame = (anyio.current_time(), progress, total, message)
        frames.append(frame)
        delivered.put_nowait(frame)

    reporter = McpProgressReporter(send)
    async with reporter.heartbeat("code_research"):
        await reporter.report("Starting")
        with anyio.fail_after(5):
            first = await delivered.get()
        for index in range(100):
            await reporter.emit_event("phase", f"Phase {index}")
        with anyio.fail_after(5):
            second = await delivered.get()
        await anyio.sleep(0.1)
        assert len(frames) == 2
        assert second[0] - first[0] >= MIN_PROGRESS_INTERVAL_SECONDS * 0.95
        assert first[1] < second[1]
        assert first[2] is second[2] is None
        assert second[3] == "Phase 99"


async def test_heartbeats_stop_at_idle_cap_and_real_progress_restarts_them(monkeypatch):
    monkeypatch.setattr(
        "chunkhound.mcp_server.progress.HEARTBEAT_INTERVAL_SECONDS", 0.02
    )
    idle_cap = 1.0
    monkeypatch.setattr(
        "chunkhound.mcp_server.progress.HEARTBEAT_IDLE_LIMIT_SECONDS", idle_cap
    )
    monkeypatch.setattr(
        "chunkhound.mcp_server.progress.MIN_PROGRESS_INTERVAL_SECONDS", 0.01
    )
    frames = []
    delivered = asyncio.Queue()

    async def send(progress, total, message):
        frames.append(message)
        delivered.put_nowait(message)

    reporter = McpProgressReporter(send)
    async with reporter.heartbeat("code_research"):
        with anyio.fail_after(5):
            assert "code_research still running" in await delivered.get()
        await anyio.sleep(idle_cap + 0.25)  # Scheduling delays only extend this wait.
        snapshot = list(frames)
        await anyio.sleep(0.1)
        assert frames == snapshot
        while not delivered.empty():
            delivered.get_nowait()

        await reporter.emit_event("phase", "Research resumed")
        with anyio.fail_after(5):
            assert await delivered.get() == "Research resumed"
            assert "code_research still running" in await delivered.get()
        await anyio.sleep(idle_cap + 0.25)
        snapshot = list(frames)
        await anyio.sleep(0.1)
        assert frames == snapshot  # Heartbeats themselves do not reset the cap.


async def test_heartbeat_preserves_tool_exception():
    async def send(progress, total, message):
        pass

    error = ValueError("boom")
    reporter = McpProgressReporter(send)
    with pytest.raises(ValueError, match="^boom$") as caught:
        async with reporter.heartbeat("code_research"):
            try:
                raise error
            except ValueError:
                original_traceback = error.__traceback__
                raise
    assert caught.value is error
    traceback = caught.value.__traceback__
    while traceback.tb_next is not None:
        traceback = traceback.tb_next
    assert traceback is original_traceback


async def test_request_cancellation_stops_progress_during_tool_unwind(monkeypatch):
    monkeypatch.setattr(
        "chunkhound.mcp_server.progress.HEARTBEAT_INTERVAL_SECONDS", 0.02
    )
    monkeypatch.setattr(
        "chunkhound.mcp_server.progress.MIN_PROGRESS_INTERVAL_SECONDS", 0.01
    )
    frames = []
    delivered = anyio.Event()

    async def send(progress, total, message):
        await anyio.sleep(0)  # A cancellable transport boundary.
        frames.append(message)
        delivered.set()

    reporter = McpProgressReporter(send)
    with anyio.fail_after(5):
        with anyio.CancelScope() as request:
            async with reporter.heartbeat("code_research"):
                await delivered.wait()
                request.cancel()
                snapshot = list(frames)
                # The tool may take time to unwind before heartbeat().__aexit__.
                with anyio.CancelScope(shield=True):
                    await anyio.sleep(0.15)
                    assert frames == snapshot
                await anyio.sleep(0)
        await anyio.sleep(0.1)
        assert frames == snapshot


async def test_progress_send_timeout_allows_later_progress(monkeypatch):
    monkeypatch.setattr("chunkhound.mcp_server.progress.SEND_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        "chunkhound.mcp_server.progress.MIN_PROGRESS_INTERVAL_SECONDS", 0.01
    )
    timed_out = anyio.Event()
    recovered = anyio.Event()
    values = []

    async def send(progress, total, message):
        values.append(progress)
        if message == "Hung send":
            try:
                await anyio.sleep_forever()
            finally:
                timed_out.set()
        else:
            assert message == "Recovered"
            recovered.set()

    reporter = McpProgressReporter(send)
    async with reporter.heartbeat("code_research"):
        await reporter.report("Hung send")
        with anyio.fail_after(5):
            await timed_out.wait()
            await reporter.report("Recovered")
            await recovered.wait()
    assert len(values) == 2 and values[0] < values[1]
