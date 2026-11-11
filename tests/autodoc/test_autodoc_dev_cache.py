"""Development-cache contracts through the real AutoDoc CLI and pipeline."""

import argparse
import hashlib
from pathlib import Path
from typing import Any

import pytest

from chunkhound.api.cli.commands.autodoc import autodoc_command
from chunkhound.api.cli.parsers.autodoc_parser import add_autodoc_subparser
from chunkhound.core.config.config import Config
from chunkhound.interfaces.llm_provider import LLMProvider, LLMResponse
from chunkhound.llm_manager import LLMManager


class _Provider(LLMProvider):
    calls: list[str] = []
    fail_second_topic = False

    def __init__(self, **kwargs: Any) -> None:
        self._model = kwargs["model"]

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    @property
    def timeout(self) -> int:
        return 1

    def _response(self, prompt: str) -> LLMResponse:
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        return LLMResponse(
            content=f"## Overview\nContent {digest}.",
            tokens_used=0,
            model=self.model,
            finish_reason="stop",
        )

    async def batch_complete(self, prompts, **kwargs):
        self.calls.extend(["cleanup"] * len(prompts))
        if self.fail_second_topic and (
            len(prompts) > 1 or "Original two." in prompts[0]
        ):
            raise ValueError("Provider rejected this cleanup request")
        return [self._response(prompt) for prompt in prompts]

    async def complete(self, prompt, **kwargs):
        self.calls.append("homepage")
        return self._response(prompt)

    async def complete_structured(self, prompt, **kwargs):
        self.calls.append("site_ia")
        return {
            "nav": {"groups": [{"title": "Topics", "slugs": ["01-one", "02-two"]}]},
            "glossary": [
                {"term": "Term", "definition": "Definition.", "pages": ["01-one"]}
            ],
        }

    def estimate_tokens(self, text: str) -> int:
        return 0

    async def health_check(self) -> dict[str, Any]:
        return {}

    def get_usage_stats(self) -> dict[str, Any]:
        return {}


@pytest.fixture
def run_autodoc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_Provider, "calls", [])
    monkeypatch.setattr(_Provider, "fail_second_topic", False)
    monkeypatch.setitem(LLMManager._providers, "openai", _Provider)
    map_dir = tmp_path / "map"
    map_dir.mkdir()
    (map_dir / "scope_code_mapper_index.md").write_text(
        "# AutoDoc Topics (/repo)\n\n1. [One](one.md)\n2. [Two](two.md)\n"
    )
    for name in ("one", "two"):
        (map_dir / f"{name}.md").write_text(f"# {name.title()}\n\nOriginal {name}.\n")
    config = Config(
        target_dir=tmp_path,
        llm={"provider": "openai", "api_key": "fake", "model": "fake"},
    )
    parser = argparse.ArgumentParser()
    add_autodoc_subparser(parser.add_subparsers(dest="command"))

    async def run(*flags: str) -> list[str]:
        _Provider.calls.clear()
        args = parser.parse_args(
            [
                "autodoc",
                str(map_dir),
                "--out-dir",
                str(tmp_path / "site"),
                "--force",
                *flags,
            ]
        )
        await autodoc_command(args, config)
        return list(_Provider.calls)

    return run


def _pages(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "src" / "pages").rglob("*.md")
    }


@pytest.mark.asyncio
async def test_autodoc_dev_cache_second_run_makes_no_llm_calls(
    run_autodoc, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run_autodoc("--dev-cache") == [
        "cleanup",
        "cleanup",
        "homepage",
        "site_ia",
    ]
    first_pages = _pages(tmp_path / "site")
    assert first_pages
    assert await run_autodoc("--dev-cache") == []
    assert _pages(tmp_path / "site") == first_pages
    output = capsys.readouterr().out
    assert "cleanup 2 reused / 0 new" in output
    assert "homepage 1 reused / 0 new" in output
    assert "site_ia 1 reused / 0 new" in output

    (tmp_path / "map" / "one.md").write_text("# One\n\nChanged topic.\n")
    assert await run_autodoc("--dev-cache") == ["cleanup", "homepage", "site_ia"]
    assert await run_autodoc("--dev-cache") == []


@pytest.mark.asyncio
async def test_autodoc_without_dev_cache_neither_reads_nor_writes_cache(
    run_autodoc, tmp_path: Path
) -> None:
    expected = ["cleanup", "cleanup", "homepage", "site_ia"]
    assert await run_autodoc() == expected
    cache_root = tmp_path / ".chunkhound" / "extraction" / "decisions"
    assert not cache_root.exists()
    assert await run_autodoc("--dev-cache") == expected
    cached = {path: path.stat().st_mtime_ns for path in cache_root.rglob("*.json")}
    assert cached
    assert await run_autodoc() == expected
    assert {
        path: path.stat().st_mtime_ns for path in cache_root.rglob("*.json")
    } == cached


@pytest.mark.asyncio
async def test_autodoc_cache_keeps_successful_fallback_topics_after_failure(
    run_autodoc, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_Provider, "fail_second_topic", True)
    with pytest.raises(SystemExit) as exc:
        await run_autodoc("--dev-cache")
    assert exc.value.code == 1
    monkeypatch.setattr(_Provider, "fail_second_topic", False)
    assert await run_autodoc("--dev-cache") == ["cleanup", "homepage", "site_ia"]
    assert await run_autodoc("--dev-cache") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["model", "prompt", "tokens", "schema"])
async def test_autodoc_cache_invalidates_changed_generation_inputs(
    run_autodoc, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from chunkhound.autodoc import cleanup, ia

    await run_autodoc("--dev-cache")
    flags = ["--dev-cache"]
    if change == "model":
        monkeypatch.setattr(_Provider, "model", property(lambda self: "other-model"))
    elif change == "prompt":
        monkeypatch.setattr(
            cleanup, "_build_cleanup_system_prompt", lambda config: "New system prompt"
        )
    elif change == "tokens":
        flags.extend(["--cleanup-max-tokens", "1024"])
    else:
        original = ia._site_ia_schema

        def changed_schema():
            return {**original(), "description": "New schema"}

        monkeypatch.setattr(ia, "_site_ia_schema", changed_schema)
    calls = await run_autodoc(*flags)
    if change == "model":
        assert calls == ["cleanup", "cleanup", "homepage", "site_ia"]
    elif change == "schema":
        assert calls == ["site_ia"]
    else:
        # The fake returns the same text when only system/tokens change, so IA hits.
        assert calls == ["cleanup", "cleanup"]
