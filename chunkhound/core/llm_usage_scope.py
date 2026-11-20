"""Fork-only, task-local LLM accounting shared by a research run's child tasks."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class LLMUsageScope:
    # Retain the provider as well as its id: identity must not depend on hashing,
    # equality overrides, or an id being reused during a run.
    _providers: dict[int, tuple[object, dict[str, int]]] = field(default_factory=dict)
    _active: bool = True

    def add(self, provider: object, counters: Mapping[str, int]) -> None:
        if not self._active:
            return
        _, totals = self._providers.setdefault(id(provider), (provider, {}))
        for key, value in counters.items():
            totals[key] = totals.get(key, 0) + value

    def for_provider(self, provider: object) -> dict[str, int]:
        entry = self._providers.get(id(provider))
        return dict(entry[1]) if entry is not None else {}


_current_scope: ContextVar[LLMUsageScope | None] = ContextVar(
    "llm_usage_scope", default=None
)


def record_usage(provider: object, counters: Mapping[str, int]) -> None:
    """Mirror a provider's deltas only when a research scope is active."""
    scope = _current_scope.get()
    if scope is not None:
        scope.add(provider, counters)


@contextmanager
def llm_usage_scope() -> Iterator[LLMUsageScope]:
    """Isolate a run while letting gather/create_task/to_thread share its totals."""
    scope = LLMUsageScope()
    token = _current_scope.set(scope)
    try:
        yield scope
    finally:
        # A detached child retaining this context must not extend a finished run.
        scope._active = False
        _current_scope.reset(token)
