"""Shared, network-free inputs for the C4 contract tests."""

import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from chunkhound.llm_manager import LLMManager
from tests.fixtures.fake_providers import FakeLLMProvider

Answer = dict[str, Any] | Callable[[str], dict[str, Any]] | Exception


class ScriptedLLM(FakeLLMProvider):
    """Dispatch structured answers by the explicit C4 step in a prompt."""

    def __init__(self, answers: Mapping[str, Answer]) -> None:
        super().__init__()
        self.answers = dict(answers)
        self.calls: Counter[str] = Counter()

    async def complete_structured(
        self,
        prompt: str,
        json_schema: dict[str, Any],
        system: str | None = None,
        max_completion_tokens: int = 4096,
    ) -> dict[str, Any]:
        match = re.search(r"C4 step: ([a-z]+)\b", prompt)
        if match is None:
            raise ValueError("Structured C4 prompt must contain 'C4 step: <step>'")
        step = match.group(1)
        self.calls[step] += 1
        self._requests_made += 1
        answer = self.answers[step]
        if isinstance(answer, Exception):
            raise answer
        return answer(prompt) if callable(answer) else deepcopy(answer)


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Give each test an independent, committed copy of the mini-repository."""
    source = Path(__file__).parent / "fixture_repo"
    repo = tmp_path / "shop"
    shutil.copytree(source, repo, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for args in (
        ["init", "--initial-branch=main"],
        ["add", "."],
        [
            "-c",
            "user.name=C4 Fixture",
            "-c",
            "user.email=c4@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-m",
            "Initial C4 fixture",
        ],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


# Fixture response shapes follow spec §8, not yet-defined step Pydantic models.
# classify: dependency votes; merge: group placement and relation titles;
# titles: relation titles; documented: elements/relations with literal citations;
# summaries: labels for merged arrows. Step tasks may align their entry with
# their response model when it is introduced (coordinator ruling for task 4).
def default_answers() -> dict[str, Answer]:
    """Return fresh, deterministic answers for the five steps on the mini-repo."""
    quote = "Een beheerder gebruikt de webwinkel via Stripe."
    citation = {"file": "README.md", "start_line": 3, "end_line": 3, "quote": quote}
    return {
        "classify": {"classifications": [{"key": "requests", "value": "library"}]},
        "merge": {
            "components": [
                {
                    "name": "Orders",
                    "description": "Coordinates orders, payment and storage.",
                    "groups": ["shop"],
                }
            ],
            "direct": [],
            "titles": [],
        },
        "titles": {"titles": []},
        "documented": {
            "elements": [
                {
                    "kind": "person",
                    "term": "beheerder",
                    "citation": deepcopy(citation),
                },
                {
                    "kind": "external",
                    "term": "Stripe",
                    "citation": deepcopy(citation),
                },
            ],
            "relations": [
                {
                    "from_term": "beheerder",
                    "to_term": "webwinkel",
                    "title": "gebruikt",
                    "citation": deepcopy(citation),
                },
                {
                    "from_term": "webwinkel",
                    "to_term": "Stripe",
                    "title": "betaalt via",
                    "citation": deepcopy(citation),
                },
            ],
        },
        "summaries": {"labels": []},
    }


@pytest.fixture
def scripted() -> ScriptedLLM:
    return ScriptedLLM(default_answers())


@pytest.fixture
def c4_llm_manager(
    monkeypatch: pytest.MonkeyPatch, scripted: ScriptedLLM
) -> LLMManager:
    """Use the same scripted provider for utility and synthesis without a network."""
    monkeypatch.setattr(LLMManager, "_create_provider", lambda self, config: scripted)
    config = {"provider": "fake", "model": "fake-gpt"}
    return LLMManager(utility_config=config, synthesis_config=config)
