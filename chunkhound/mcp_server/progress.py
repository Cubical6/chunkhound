"""Best-effort, request-scoped MCP progress and idle heartbeats."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

from loguru import logger

HEARTBEAT_INTERVAL_SECONDS = 30.0
SEND_TIMEOUT_SECONDS = 5.0


class McpProgressReporter:
    """Adapt research events to serialized, strictly increasing MCP progress."""

    def __init__(
        self,
        send: Callable[[float, float | None, str | None], Awaitable[None]],
    ) -> None:
        self._send = send
        self._lock = asyncio.Lock()
        self._counter = 0
        self._last_progress = time.monotonic()

    async def _report_locked(self, message: str) -> None:
        self._counter += 1
        try:
            await asyncio.wait_for(
                self._send(float(self._counter), None, message),
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.opt(exception=True).debug("Unable to send MCP progress")
        finally:
            self._last_progress = time.monotonic()

    async def report(self, message: str) -> None:
        """Send a message without allowing transport errors to affect the tool."""
        async with self._lock:
            await self._report_locked(message)

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
        """Report only during idle periods; stop on completion or cancellation."""
        started = time.monotonic()

        async def run() -> None:
            while True:
                delay = (
                    self._last_progress + HEARTBEAT_INTERVAL_SECONDS - time.monotonic()
                )
                await asyncio.sleep(max(0.0, delay))
                async with self._lock:
                    idle = time.monotonic() - self._last_progress
                    if idle >= HEARTBEAT_INTERVAL_SECONDS:
                        elapsed = int(time.monotonic() - started)
                        await self._report_locked(
                            f"{tool_name} still running ({elapsed}s)"
                        )

        task = asyncio.create_task(run())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
