"""Request budget: declared input limits measured before anything is sent.

Start values are uncalibrated proposals (spec §6.1); they are named here so a
later calibration changes one place.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_TARGET_CHARS = 150_000
DEFAULT_MAX_INPUT_CHARS = 400_000
# Known only from one reproduction's refusal message (actual vs max characters).
KNOWN_MAX_INPUT_CHARS: Mapping[str, int] = {"codex-cli": 1_048_576}
TOKEN_SAFETY = 1.2
CHARS_PER_TOKEN_ESTIMATE = 4
FRAGMENT_DIVISOR = 4
ENVELOPE_MARGIN_CHARS = 2_000


@dataclass(frozen=True)
class InputLimit:
    max_chars: int
    max_tokens: int | None = None


def resolve_input_limit(role_config: Mapping[str, Any]) -> InputLimit:
    """Configured override first, then a known provider limit, then the default."""
    configured = role_config.get("max_input_chars")
    if configured is not None:
        max_chars = int(configured)
    else:
        provider = str(role_config.get("provider", ""))
        max_chars = KNOWN_MAX_INPUT_CHARS.get(provider, DEFAULT_MAX_INPUT_CHARS)
    tokens = role_config.get("max_input_tokens")
    return InputLimit(max_chars, int(tokens) if tokens is not None else None)


def effective_target(limit: InputLimit) -> int:
    """Bundle target that stays inside both the character and token limits."""
    target = min(DEFAULT_TARGET_CHARS, limit.max_chars - ENVELOPE_MARGIN_CHARS)
    if limit.max_tokens is not None:
        by_tokens = int(limit.max_tokens / TOKEN_SAFETY) * CHARS_PER_TOKEN_ESTIMATE
        target = min(target, by_tokens - ENVELOPE_MARGIN_CHARS)
    if target <= 0:
        raise ValueError(f"Input limit {limit} leaves no room for a request")
    return target


def max_fragment_chars(target: int) -> int:
    """Leave room to bisect: no fragment may fill a bundle on its own."""
    return target // FRAGMENT_DIVISOR


def schema_text(schema: Mapping[str, Any]) -> str:
    """The schema as CLI providers inline it into the prompt."""
    return json.dumps(schema, indent=2)


def measure_request(
    instructions: str, schema: Mapping[str, Any], rendered: Sequence[str]
) -> int:
    """Upper bound of the provider request, including the inlined schema."""
    return (
        len(instructions)
        + len(schema_text(schema))
        + sum(len(part) + 2 for part in rendered)
        + ENVELOPE_MARGIN_CHARS
    )


def fits(
    prompt: str,
    schema: Mapping[str, Any],
    limit: InputLimit,
    estimate_tokens: Callable[[str], int],
) -> bool:
    """Final check of a built prompt against the declared limit."""
    size = len(prompt) + len(schema_text(schema)) + ENVELOPE_MARGIN_CHARS
    if size > limit.max_chars:
        return False
    if limit.max_tokens is None:
        return True
    tokens = estimate_tokens(prompt) + estimate_tokens(schema_text(schema))
    return tokens * TOKEN_SAFETY <= limit.max_tokens
