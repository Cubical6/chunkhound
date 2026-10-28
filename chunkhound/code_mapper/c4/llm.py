"""Shared typed LLM boundary and delayed, single-attempt recovery for C4 steps."""

import asyncio
import importlib.resources
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from chunkhound.code_mapper.service import _is_retryable_poi_error
from chunkhound.llm_manager import LLMManager

T = TypeVar("T")
ResponseT = TypeVar("ResponseT", bound=BaseModel)


class TransientStepError(RuntimeError):
    """A step may be tried once more after the other steps finish."""


class AnswerRejectedError(TransientStepError):
    """The provider answered, but its answer violates the step's contract."""


class C4Llm:
    """Share the jobs limit across utility and synthesis requests."""

    def __init__(
        self, llm_manager: LLMManager | None, *, concurrency: int, trial: bool
    ) -> None:
        if concurrency < 1:
            raise ValueError("C4 concurrency must be at least one")
        self._manager = llm_manager
        self._trial = trial or llm_manager is None
        self._semaphore = asyncio.Semaphore(concurrency)
        self.calls = 0

    @property
    def trial(self) -> bool:
        return self._trial

    async def call(
        self,
        step: str,
        response_model: type[ResponseT],
        prompt: str,
        *,
        provider: Literal["utility", "synthesis"],
    ) -> ResponseT:
        if self.trial or self._manager is None:
            raise RuntimeError("C4 LLM call in trial mode")
        # Provider configuration errors are fatal, not retryable step failures.
        selected = (
            self._manager.get_utility_provider()
            if provider == "utility"
            else self._manager.get_synthesis_provider()
        )
        async with self._semaphore:
            self.calls += 1
            try:
                return await selected.complete_structured_typed(
                    prompt=prompt, response_model=response_model
                )
            except ValidationError as exc:
                raise AnswerRejectedError(f"{step}: invalid answer schema") from exc
            except Exception as exc:
                if _is_retryable_poi_error(exc):
                    raise TransientStepError(f"{step}: {exc}") from exc
                raise


class RetryQueue:
    """Apply each deferred operation once; only transient errors use a fallback."""

    def __init__(self) -> None:
        self._pending: dict[str, Callable[[], Awaitable[bool]]] = {}

    def defer(
        self,
        key: str,
        attempt: Callable[[], Awaitable[T]],
        fallback: Callable[[], T],
        apply: Callable[[T, bool], None],
    ) -> None:
        async def run() -> bool:
            try:
                result = await attempt()
            except TransientStepError:
                apply(fallback(), True)
                return True
            apply(result, False)
            return False

        self._pending[key] = run

    async def drain(self) -> int:
        pending, self._pending = self._pending, {}
        fallback_count = 0
        for run in pending.values():
            fallback_count += await run()
        return fallback_count


def load_c4_prompt(step: str) -> str:
    """Load a packaged prompt using the same convention as HyDE."""
    return (
        importlib.resources.files("chunkhound.code_mapper.prompts")
        .joinpath(f"c4_{step}.md")
        .read_text(encoding="utf-8")
        .strip()
    )
