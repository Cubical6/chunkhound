"""Provider-boundary fake for structured extraction calls.

`complete_structured` is the real provider seam: the inherited
`complete_structured_typed` validates the returned dict exactly like real
providers do, and handlers may raise genuine provider error texts.
"""

import re
from collections.abc import Callable
from typing import Any

from tests.fixtures.fake_providers import FakeLLMProvider

Handler = Callable[[str, int], dict[str, Any]]

_HEADER = re.compile(r"^=== (F\d+) · ")
_LINE = re.compile(r"^(\d+)\| ?(.*)$")


def prompt_fragments(prompt: str) -> dict[str, list[tuple[int, str]]]:
    """Fragment id -> [(line number as shown, text)] parsed from a prompt."""
    fragments: dict[str, list[tuple[int, str]]] = {}
    current: list[tuple[int, str]] | None = None
    for line in prompt.splitlines():
        if header := _HEADER.match(line):
            current = fragments.setdefault(header.group(1), [])
        elif current is not None and (numbered := _LINE.match(line)):
            current.append((int(numbered.group(1)), numbered.group(2)))
    return fragments


class ScriptedStructuredLLM(FakeLLMProvider):
    """Calls `handler(prompt, call_number)`; records every prompt and schema."""

    def __init__(self, handler: Handler) -> None:
        super().__init__()
        self.handler = handler
        self.prompts: list[str] = []
        self.schemas: list[dict[str, Any]] = []

    @property
    def calls(self) -> int:
        return len(self.prompts)

    async def complete_structured(
        self,
        prompt: str,
        json_schema: dict[str, Any],
        system: str | None = None,
        max_completion_tokens: int = 4096,
    ) -> dict[str, Any]:
        self.prompts.append(prompt)
        self.schemas.append(json_schema)
        self._requests_made += 1
        return self.handler(prompt, len(self.prompts))
