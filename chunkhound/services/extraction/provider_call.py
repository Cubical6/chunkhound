"""Structured call adapter directly on an LLMProvider (used by research later)."""

from collections.abc import Callable
from typing import Protocol, TypeVar

from pydantic import BaseModel

from chunkhound.interfaces.llm_provider import LLMProvider
from chunkhound.services.extraction.errors import translate_call_error

ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredCall(Protocol):
    """Raises only ProviderInputRefusedError, UnreadableAnswerError,
    TransientCallError, or a fatal exception."""

    async def __call__(
        self, prompt: str, response_model: type[ModelT], max_completion_tokens: int
    ) -> ModelT: ...

    def estimate_tokens(self, text: str) -> int: ...


class ProviderStructuredCall:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        is_transient: Callable[[BaseException], bool],
    ) -> None:
        self._provider = provider
        self._is_transient = is_transient

    async def __call__(
        self, prompt: str, response_model: type[ModelT], max_completion_tokens: int
    ) -> ModelT:
        try:
            return await self._provider.complete_structured_typed(
                prompt=prompt,
                response_model=response_model,
                max_completion_tokens=max_completion_tokens,
            )
        except Exception as exc:
            translated = translate_call_error(exc, self._is_transient)
            if translated is None:
                raise
            raise translated from exc

    def estimate_tokens(self, text: str) -> int:
        return self._provider.estimate_tokens(text)
