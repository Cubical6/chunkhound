"""Provider-neutral failure kinds at the extraction call boundary (spec §6.4)."""

import json
from collections.abc import Callable, Iterator

import jsonschema
from pydantic import ValidationError

# The complete known list for now; other providers have no known marker yet.
INPUT_REJECTED_MARKERS = ("input_too_large",)
UNREADABLE_MARKERS = (
    "invalid json in structured output",
    "structured output truncated",
    "structured completion truncated",
    "response truncated",
    "incomplete - token limit",
)
DEFAULT_UNREADABLE_RULE = "invalid answer schema"


class InputRejectedError(RuntimeError):
    """Fatal: the provider refused a request the declared limit allowed."""

    def __init__(self, provider: str, chars: int, limit: int) -> None:
        super().__init__(
            f"Invoer geweigerd door provider {provider}: aanvraag {chars} tekens, "
            f"opgegeven grens {limit} tekens. Pas de invoerlimiet aan."
        )
        self.provider = provider
        self.chars = chars
        self.limit = limit


class ProviderInputRefusedError(RuntimeError):
    """Raised by call adapters; the runner adds size and limit."""


class UnreadableAnswerError(RuntimeError):
    """The answer is not valid JSON or not the schema: bisect, never fatal."""

    def __init__(self, rule: str = DEFAULT_UNREADABLE_RULE) -> None:
        super().__init__(rule)
        self.rule = rule


class TransientCallError(RuntimeError):
    """A temporary provider failure; the application decides on recovery."""


def exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def has_marker(exc: BaseException, markers: tuple[str, ...]) -> bool:
    return any(
        marker in str(link).lower()
        for link in exception_chain(exc)
        for marker in markers
    )


def is_unreadable(exc: BaseException) -> bool:
    return has_marker(exc, UNREADABLE_MARKERS) or any(
        isinstance(
            link, (json.JSONDecodeError, ValidationError, jsonschema.ValidationError)
        )
        for link in exception_chain(exc)
    )


def translate_call_error(
    exc: BaseException, is_transient: Callable[[BaseException], bool]
) -> BaseException | None:
    """Map a provider failure to a layer kind; None means: re-raise as fatal.

    Unreadable comes first: parse and schema errors quote model output, which
    can mention a refusal marker. Refusal precedes transient, because wrappers
    may also look transient.
    """
    if is_unreadable(exc):
        return UnreadableAnswerError()
    if has_marker(exc, INPUT_REJECTED_MARKERS):
        return ProviderInputRefusedError(str(exc))
    if is_transient(exc):
        return TransientCallError(str(exc))
    return None
