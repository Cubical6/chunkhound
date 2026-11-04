"""Shared typed LLM boundary and delayed, single-attempt recovery for C4 steps."""

import asyncio
import importlib.resources
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from chunkhound.code_mapper.service import _is_retryable_poi_error
from chunkhound.llm_manager import LLMManager
from chunkhound.services.extraction.budget import InputLimit, resolve_input_limit
from chunkhound.services.extraction.errors import ProviderInputRefusedError
from chunkhound.services.extraction.store import ProviderIdentity

T = TypeVar("T")
ResponseT = TypeVar("ResponseT", bound=BaseModel)


class TransientStepError(RuntimeError):
    """A step may be tried once more after the other steps finish."""


class AnswerRejectedError(TransientStepError):
    """The provider answered, but its answer violates the step's contract."""


# Only application-owned rule names may reach the public report. Never include
# validation inputs, provider exceptions, paths or model-controlled values.
_REJECTION_RULES = frozenset(
    {
        "invalid answer schema",
        "every candidate key must occur exactly once",
        "invalid candidate vote",
        "answer places no group",
        "every fingerprint must occur exactly once",
        "no proposed item has a literal quote",
        "every fragment id must occur exactly once",
        "exactly one nonblank label per supplied key required",
    }
)


def public_rule(rule: str | None) -> str:
    """Only application-owned rule names reach the report."""
    return rule if rule in _REJECTION_RULES else "answer validation"


def rejection_rule(exc: BaseException) -> str:
    return public_rule(str(exc).partition(": ")[2])


@dataclass
class StepReport:
    """Runtime-only operation report, shared by its initial and delayed attempts."""

    reason: str
    outcomes: list[str] = field(default_factory=list)

    @contextmanager
    def attempt(self) -> Iterator[None]:
        index = len(self.outcomes)
        self.outcomes.append("running")
        try:
            yield
        except AnswerRejectedError as exc:
            self.outcomes[index] = f"rejected ({rejection_rule(exc)})"
            raise
        except TransientStepError:
            self.outcomes[index] = "transient error"
            raise
        except ProviderInputRefusedError:
            self.outcomes[index] = "input refused"
            raise
        except Exception:
            self.outcomes[index] = "error"
            raise
        else:
            self.outcomes[index] = "accepted"

    def record(self, outcome: str) -> None:
        """Record one finished call whose outcome was decided elsewhere."""
        self.outcomes.append(outcome)

    def mark_fallback(self) -> None:
        if self.outcomes and not self.outcomes[-1].endswith(", fallback"):
            self.outcomes[-1] += ", fallback"


class C4Llm:
    """Share the jobs limit across utility and synthesis requests."""

    def __init__(
        self, llm_manager: LLMManager | None, *, concurrency: int, trial: bool
    ) -> None:
        if concurrency < 1:
            raise ValueError("C4 concurrency must be at least one")
        self._manager = llm_manager
        self._trial = trial or llm_manager is None
        self.concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self.calls = 0
        self._reports: dict[str, list[StepReport]] = {
            step: []
            for step in ("classify", "merge", "titles", "documented", "summaries")
        }

    def report(self, step: str, reason: str) -> StepReport:
        report = StepReport(reason)
        self._reports[step].append(report)
        return report

    def report_lines(self) -> Iterator[str]:
        for step, reports in self._reports.items():
            count = sum(len(report.outcomes) for report in reports)
            details = "; ".join(
                f"{report.reason}: "
                + ", ".join(
                    f"#{number} {outcome}"
                    for number, outcome in enumerate(report.outcomes, 1)
                )
                for report in reports
            )
            yield f"C4 {step}: {count} attempts" + (f"; {details}" if details else "")

    @property
    def trial(self) -> bool:
        return self._trial

    def _role_config(self, role: Literal["utility", "synthesis"]) -> dict[str, object]:
        return {} if self._manager is None else self._manager.role_config(role)

    def provider_identity(
        self, role: Literal["utility", "synthesis"]
    ) -> ProviderIdentity:
        config = self._role_config(role)

        def text(key: str) -> str | None:
            value = config.get(key)
            return None if value is None else str(value)

        return ProviderIdentity(
            provider=text("provider") or "none",
            model=text("model") or "",
            reasoning_effort=text("reasoning_effort"),
            base_url=text("base_url"),
        )

    def input_limit(self, role: Literal["utility", "synthesis"]) -> InputLimit:
        return resolve_input_limit(self._role_config(role))

    def estimate_tokens(self, text: str) -> int:
        if self._manager is None:
            return len(text) // 4
        return self._manager.get_utility_provider().estimate_tokens(text)

    async def call(
        self,
        step: str,
        response_model: type[ResponseT],
        prompt: str,
        *,
        provider: Literal["utility", "synthesis"],
        max_completion_tokens: int | None = None,
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
                if max_completion_tokens is None:
                    return await selected.complete_structured_typed(
                        prompt=prompt, response_model=response_model
                    )
                return await selected.complete_structured_typed(
                    prompt=prompt,
                    response_model=response_model,
                    max_completion_tokens=max_completion_tokens,
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
        *,
        report: StepReport | None = None,
    ) -> None:
        async def run() -> bool:
            try:
                result = await attempt()
            except TransientStepError:
                if report is not None:
                    report.mark_fallback()
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
