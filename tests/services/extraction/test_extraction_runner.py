"""Contracts of the shared extraction layer, seen through a minimal goal.

The fake sits at the provider boundary (`complete_structured`); errors use the
texts real providers raise.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from chunkhound.code_mapper.service import _is_retryable_poi_error
from chunkhound.services.extraction.budget import (
    InputLimit,
    effective_target,
    max_fragment_chars,
)
from chunkhound.services.extraction.errors import InputRejectedError
from chunkhound.services.extraction.fragments import Fragment, fragment_document
from chunkhound.services.extraction.provider_call import ProviderStructuredCall
from chunkhound.services.extraction.runner import Rejected, Valid, run_extraction
from chunkhound.services.extraction.sources import read_source
from chunkhound.services.extraction.store import ExtractionStore, ProviderIdentity
from tests.fixtures.scripted_structured import ScriptedStructuredLLM, prompt_fragments

PROVIDER = ProviderIdentity(provider="fake", model="fake-gpt")
SOURCE_BYTES = 941_516  # size of the enlarged reproduction source set


class _LinesPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: int


class LineCountGoal:
    """Each fragment answers with its own line count; validation checks it."""

    name = "linecount"
    version = hashlib.sha256(b"linecount-v1").hexdigest()
    line_numbering = "relative"

    def instructions(self) -> str:
        return "Count the lines of every fragment."

    def part_model(self) -> type[BaseModel]:
        return _LinesPart

    def max_completion_tokens(self, bundle_chars: int) -> int:
        return 2_048

    def validate(self, fragment: Fragment, part: Any) -> int | Rejected:
        if part.lines != len(fragment.lines):
            return Rejected("wrong line count")
        return part.lines

    def dump(self, fragment: Fragment, part: int) -> dict[str, Any]:
        return {"lines": part}

    def recheck(self, fragment: Fragment, stored: dict[str, Any]) -> int | Rejected:
        if stored.get("lines") != len(fragment.lines):
            return Rejected("wrong line count")
        return int(stored["lines"])


def honest(prompt: str, call: int) -> dict[str, Any]:
    return {
        "fragments": [
            {"id": fid, "part": {"lines": len(lines)}}
            for fid, lines in prompt_fragments(prompt).items()
        ]
    }


def _corpus(root: Path, *, files: int, total_bytes: int | None = None) -> list[str]:
    names = []
    paragraph = "Deze component schrijft naar de opslag en leest de index. " * 4
    for number in range(files):
        sections = [f"# Document {number}"]
        for section in range(20):
            sections.append(f"## Sectie {section}")
            sections.extend([paragraph, ""] * 6)
        name = f"docs/doc{number:02d}.md"
        (root / "docs").mkdir(exist_ok=True)
        (root / name).write_text("\n".join(sections) + "\n", encoding="utf-8")
        names.append(name)
    if total_bytes is not None:
        current = sum((root / name).stat().st_size for name in names)
        assert current <= total_bytes
        filler = total_bytes - current
        last = root / names[-1]
        lines = [paragraph[: min(len(paragraph), 199)]] * (filler // 200)
        tail = "x" * (filler - 200 * len(lines))
        with last.open("a", encoding="utf-8") as stream:
            stream.write("".join(line + "\n" for line in lines))
            stream.write(tail)
        assert sum((root / name).stat().st_size for name in names) == total_bytes
    return names


def _fragments(root: Path, names: list[str], limit: InputLimit) -> list[Fragment]:
    max_chars = max_fragment_chars(effective_target(limit))
    return [
        fragment
        for name in names
        for fragment in fragment_document(
            read_source(root, name, strict=True), max_chars=max_chars, markdown=True
        )
    ]


def _call(llm: ScriptedStructuredLLM) -> ProviderStructuredCall:
    return ProviderStructuredCall(llm, is_transient=_is_retryable_poi_error)


@pytest.mark.parametrize("max_chars", [1_048_576, 60_000])
async def test_requests_never_exceed_limit(tmp_path, max_chars):
    names = _corpus(tmp_path, files=20, total_bytes=SOURCE_BYTES)
    limit = InputLimit(max_chars)
    fragments = _fragments(tmp_path, names, limit)
    llm = ScriptedStructuredLLM(honest)

    result = await run_extraction(
        LineCountGoal(),
        fragments,
        call=_call(llm),
        provider=PROVIDER,
        limit=limit,
        store=None,
        concurrency=4,
    )

    assert llm.calls > 1
    for prompt, schema in zip(llm.prompts, llm.schemas, strict=True):
        assert len(prompt) + len(json.dumps(schema, indent=2)) <= max_chars
    assert all(isinstance(part, Valid) for part in result.parts.values())
    covered = {
        (f.source.path, line)
        for index, f in enumerate(fragments)
        if isinstance(result.parts[index], Valid)
        for line in range(f.start_line, f.end_line + 1)
    }
    expected = {
        (name, line)
        for name in names
        for line in range(1, len(read_source(tmp_path, name, strict=True).lines) + 1)
    }
    assert covered == expected


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError(
            "codex exec failed (exit 1): error: input_too_large "
            "actual_chars: 1100748, max_chars: 1048576"
        ),
        RuntimeError("LLM structured completion failed: input_too_large"),
    ],
)
async def test_input_refusal_is_fatal_configuration_error(tmp_path, error):
    names = _corpus(tmp_path, files=1)
    limit = InputLimit(1_048_576)
    fragments = _fragments(tmp_path, names, limit)

    def refuse(prompt: str, call: int) -> dict[str, Any]:
        raise error

    with pytest.raises(InputRejectedError) as raised:
        await run_extraction(
            LineCountGoal(),
            fragments,
            call=_call(ScriptedStructuredLLM(refuse)),
            provider=PROVIDER,
            limit=limit,
            store=None,
            concurrency=1,
        )

    assert raised.value.limit == 1_048_576
    assert raised.value.chars > 0
    assert "1048576 tekens" in str(raised.value)
    # The wrapped variant also looks transient: refusal must be checked first.
    assert _is_retryable_poi_error(
        RuntimeError("LLM structured completion failed: input_too_large")
    )


async def test_unreadable_answer_bisects_and_keeps_valid_parts(tmp_path):
    for number in range(4):
        (tmp_path / f"n{number}.md").write_text(f"# Notitie {number}\nTekst.\n")
    names = [f"n{number}.md" for number in range(4)]
    limit = InputLimit(1_048_576)
    fragments = _fragments(tmp_path, names, limit)
    assert len(fragments) == 4

    def first_call_broken(prompt: str, call: int) -> dict[str, Any]:
        if call == 1:
            raise RuntimeError(
                "Invalid JSON in structured output: Expecting value: line 1 column 1"
            )
        return honest(prompt, call)

    llm = ScriptedStructuredLLM(first_call_broken)
    result = await run_extraction(
        LineCountGoal(),
        fragments,
        call=_call(llm),
        provider=PROVIDER,
        limit=limit,
        store=None,
        concurrency=1,
    )

    assert all(isinstance(result.parts[index], Valid) for index in range(4))
    assert result.counts.split >= 1
    assert llm.calls == 3


def _nine_fragment_setup(tmp_path: Path) -> tuple[list[Fragment], InputLimit]:
    limit = InputLimit(20_000)
    per_fragment = max_fragment_chars(effective_target(limit)) - 400
    names = []
    for number in range(9):
        body = ("woord " * (per_fragment // 6)).strip()
        (tmp_path / f"part{number}.md").write_text(f"{body}\n", encoding="utf-8")
        names.append(f"part{number}.md")
    fragments = _fragments(tmp_path, names, limit)
    assert len(fragments) == 9
    return fragments, limit


async def test_valid_bundles_survive_fatal_error_and_are_reused(tmp_path):
    fragments, limit = _nine_fragment_setup(tmp_path)
    store = ExtractionStore(tmp_path / ".cache", "linecount", read_only=False)

    def fatal_on_second(prompt: str, call: int) -> dict[str, Any]:
        if call == 2:
            raise ValueError("provider configuration broke")
        return honest(prompt, call)

    first = ScriptedStructuredLLM(fatal_on_second)
    with pytest.raises(ValueError):
        await run_extraction(
            LineCountGoal(),
            fragments,
            call=_call(first),
            provider=PROVIDER,
            limit=limit,
            store=store,
            concurrency=1,
        )
    stored = list(store.candidates())
    assert len(stored) == 1

    second = ScriptedStructuredLLM(honest)
    result = await run_extraction(
        LineCountGoal(),
        fragments,
        call=_call(second),
        provider=PROVIDER,
        limit=limit,
        store=store,
        concurrency=1,
    )
    # Three bundles: the fatal error stops at the second, so the first call is
    # the only stored outcome and run two calls just the other two bundles.
    assert first.calls == 2
    assert result.counts.reused == 1
    assert second.calls == 2
    assert all(isinstance(part, Valid) for part in result.parts.values())
    cached = {i for i, part in result.parts.items() if part.from_cache}  # type: ignore[union-attr]
    assert len(cached) == len(stored[0].parts)


async def test_corrupt_cache_is_a_miss_and_changes_only_cost(tmp_path):
    fragments, limit = _nine_fragment_setup(tmp_path)
    store = ExtractionStore(tmp_path / ".cache", "linecount", read_only=False)

    async def run(llm: ScriptedStructuredLLM, with_store: bool):
        return await run_extraction(
            LineCountGoal(),
            fragments,
            call=_call(llm),
            provider=PROVIDER,
            limit=limit,
            store=store if with_store else None,
            concurrency=1,
        )

    baseline_llm = ScriptedStructuredLLM(honest)
    baseline = await run(baseline_llm, with_store=False)
    await run(ScriptedStructuredLLM(honest), with_store=True)

    entries = sorted(store.directory.glob("*.json"))
    assert len(entries) >= 2
    entries[0].write_text(entries[0].read_text()[:40], encoding="utf-8")
    forged = json.loads(entries[1].read_text())
    forged["key_parts"]["goal_version"] = "forged"
    entries[1].write_text(json.dumps(forged), encoding="utf-8")
    (store.directory / "garbage.json").write_text("{not json", encoding="utf-8")

    llm = ScriptedStructuredLLM(honest)
    result = await run(llm, with_store=True)

    def values(outcome):
        return {i: part.part for i, part in outcome.parts.items()}  # type: ignore[union-attr]

    assert values(result) == values(baseline)
    assert 0 < llm.calls < baseline_llm.calls


async def test_supplied_oversized_bundle_is_split_not_truncated(tmp_path):
    fragments, limit = _nine_fragment_setup(tmp_path)
    llm = ScriptedStructuredLLM(honest)

    result = await run_extraction(
        LineCountGoal(),
        fragments,
        call=_call(llm),
        provider=PROVIDER,
        limit=limit,
        store=None,
        concurrency=1,
        bundles=[list(range(len(fragments)))],
    )

    assert llm.calls >= 2
    assert all(isinstance(part, Valid) for part in result.parts.values())
    for fragment in fragments:
        body = "\n".join(
            f"{number}| {line}" for number, line in enumerate(fragment.lines, 1)
        )
        assert any(body in prompt for prompt in llm.prompts)
