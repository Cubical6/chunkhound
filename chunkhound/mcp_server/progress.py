"""Best-effort, request-scoped MCP progress and idle heartbeats."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import anyio
from loguru import logger

HEARTBEAT_INTERVAL_SECONDS = 30.0
SEND_TIMEOUT_SECONDS = 5.0
MIN_PROGRESS_INTERVAL_SECONDS = 1.0
HEARTBEAT_IDLE_LIMIT_SECONDS = 600.0


class McpProgressReporter:
    """Adapt research events to serialized, strictly increasing MCP progress."""

    def __init__(
        self,
        send: Callable[[float, float | None, str | None], Awaitable[None]],
    ) -> None:
        self._send = send
        self._counter = 0
        self._last_progress = time.monotonic()
        self._last_real_progress = self._last_progress
        self._pending_message: str | None = None
        self._changed = anyio.Event()

    async def report(self, message: str) -> None:
        """Queue the latest message without awaiting transport or yielding."""
        self._pending_message = message
        self._last_real_progress = time.monotonic()
        self._changed.set()

    async def emit_event(
        self,
        event_type: str,
        message: str,
        node_id: int | None = None,
        depth: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Accept the research service's TreeProgressDisplay event contract."""
        await self.report(message)

    @asynccontextmanager
    async def heartbeat(self, tool_name: str) -> AsyncIterator[None]:
        """Send throttled progress and bounded heartbeats in the request scope."""
        started = time.monotonic()

        async def run() -> None:
            next_send = started
            while True:
                now = time.monotonic()
                if self._pending_message is not None:
                    deadline = next_send
                elif now - self._last_real_progress >= HEARTBEAT_IDLE_LIMIT_SECONDS:
                    # Only a real event can restart heartbeats after the idle cap.
                    await self._changed.wait()
                    self._changed = anyio.Event()
                    continue
                else:
                    deadline = max(
                        next_send, self._last_progress + HEARTBEAT_INTERVAL_SECONDS
                    )
                if now < deadline:
                    with anyio.move_on_after(deadline - now):
                        await self._changed.wait()
                    self._changed = anyio.Event()
                    continue

                message = self._pending_message
                self._pending_message = None
                if message is None:
                    message = f"{tool_name} still running ({int(now - started)}s)"
                self._counter += 1
                try:
                    with anyio.fail_after(SEND_TIMEOUT_SECONDS):
                        await self._send(float(self._counter), None, message)
                except Exception:
                    logger.opt(exception=True).debug("Unable to send MCP progress")
                finally:
                    self._last_progress = time.monotonic()
                    next_send = self._last_progress + MIN_PROGRESS_INTERVAL_SECONDS

        tool_error: Exception | None = None
        async with anyio.create_task_group() as tg:
            tg.start_soon(run)
            try:
                yield
            except Exception as exc:
                # Keep tool failures out of AnyIO's task-group exception wrapping.
                tool_error = exc
            finally:
                tg.cancel_scope.cancel()
        if tool_error is not None:
            raise tool_error
