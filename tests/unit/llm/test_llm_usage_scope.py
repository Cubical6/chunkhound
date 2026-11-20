"""Per-run accounting contracts, with fakes only at SDK/subprocess boundaries."""

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from chunkhound.core.llm_usage_scope import llm_usage_scope
from chunkhound.interfaces.llm_provider import LLMProvider
from chunkhound.providers.llm.anthropic_llm_provider import AnthropicLLMProvider
from chunkhound.providers.llm.gemini_llm_provider import GeminiLLMProvider
from chunkhound.providers.llm.openai_compatible_provider import OpenAICompatibleProvider
from chunkhound.providers.llm.openai_llm_provider import OpenAILLMProvider
from chunkhound.providers.llm.pi_cli_provider import PiCLIProvider


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,operation",
    [
        (kind, operation)
        for kind in ("openai", "compatible", "gemini", "anthropic", "cli")
        for operation in ("text", "structured")
    ]
    + [("anthropic", "tools")],
)
async def test_provider_usage_is_scoped_without_changing_lifetime_stats(
    kind: str,
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content = '{"answer":"ok"}'
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        prompt_tokens=10,
        completion_tokens=20,
    )
    client = MagicMock()
    provider: LLMProvider
    if kind in ("openai", "compatible"):
        monkeypatch.setattr(
            "chunkhound.providers.llm.openai_compatible_provider.AsyncOpenAI",
            lambda **kwargs: client,
        )
        client.responses.create = AsyncMock(
            return_value=SimpleNamespace(
                usage=usage,
                status="completed",
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", text=content)],
                    )
                ],
            )
        )
        client.chat.completions.create = AsyncMock(
            return_value=SimpleNamespace(
                usage=usage,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content, refusal=None),
                        finish_reason="stop",
                    )
                ],
            )
        )
        if kind == "openai":
            provider = OpenAILLMProvider(api_key="test-key", model="gpt-5")
        else:
            provider = OpenAICompatibleProvider(
                api_key="test-key",
                model="test-model",
                base_url="https://provider.invalid/v1",
                supports_structured_outputs=False,
            )
    elif kind == "anthropic":
        monkeypatch.setattr(
            "chunkhound.providers.llm.anthropic_llm_provider.AsyncAnthropic",
            lambda **kwargs: client,
        )
        response = SimpleNamespace(
            usage=usage,
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=content)],
        )
        client.messages.create = AsyncMock(return_value=response)
        client.beta.messages.create = AsyncMock(return_value=response)
        provider = AnthropicLLMProvider(api_key="test-key", model="test-model")
    elif kind == "gemini":
        monkeypatch.setattr(
            "chunkhound.providers.llm.gemini_llm_provider.genai.Client",
            lambda **kwargs: client,
        )
        client.aio.__aenter__.return_value.models.generate_content = AsyncMock(
            return_value=SimpleNamespace(
                text=content,
                candidates=[SimpleNamespace(finish_reason="STOP")],
                usage_metadata=SimpleNamespace(
                    prompt_token_count=10,
                    candidates_token_count=20,
                    total_token_count=30,
                ),
            )
        )
        provider = GeminiLLMProvider(api_key="test-key", model="test-model")
    else:
        # Exercise BaseCLIProvider through a concrete CLI, not a stub of complete.
        binary = tmp_path / "fake-pi"
        binary.touch()
        monkeypatch.setenv("CHUNKHOUND_PI_BIN", str(binary))
        stream = (
            json.dumps(
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "stopReason": "stop",
                        "content": [{"type": "text", "text": content}],
                    },
                }
            ).encode()
            + b"\n"
        )
        process = MagicMock(returncode=0, pid=None)
        process.communicate = AsyncMock(return_value=(stream, b""))
        process.wait = AsyncMock(return_value=0)
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
        )
        provider = PiCLIProvider(model="test/model")

    prompt = "question"
    system = "system"
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}

    async def invoke() -> Any:
        if operation == "structured":
            return await provider.complete_structured(prompt, schema, system=system)
        if operation == "tools":
            assert isinstance(provider, AnthropicLLMProvider)
            return await provider.complete_with_tools(prompt, [], system=system)
        return await provider.complete(prompt, system=system)

    # A pre-existing lifetime counter must never be mistaken for run usage.
    await invoke()
    expected = {
        "requests_made": 1,
        "total_tokens": 30,
        "prompt_tokens": 10,
        "completion_tokens": 20,
    }
    if kind == "cli":
        wire_prompt = process.communicate.call_args.args[0].decode("utf-8")
        prompt_tokens = provider.estimate_tokens(
            wire_prompt
        ) + provider.estimate_tokens(system)
        completion_tokens = provider.estimate_tokens(content)
        expected = {
            "requests_made": 1,
            "total_tokens_estimated": prompt_tokens + completion_tokens,
            "prompt_tokens_estimated": prompt_tokens,
            "completion_tokens_estimated": completion_tokens,
        }

    expected_stats = dict(expected)
    if kind == "anthropic":
        expected_stats["thinking_tokens"] = 0
    assert provider.get_usage_stats() == expected_stats
    with llm_usage_scope() as scope:
        await asyncio.create_task(invoke())
        assert scope.for_provider(provider) == expected
    # The closed scope must not collect subsequent requests either.
    await invoke()
    assert scope.for_provider(provider) == expected
    assert provider.get_usage_stats() == {
        key: value * 3 for key, value in expected_stats.items()
    }
    with llm_usage_scope() as next_scope:
        assert next_scope.for_provider(provider) == {}


def test_all_llm_providers_use_central_usage_accounting() -> None:
    """New/synced provider modules must not silently bypass run accounting."""
    root = Path(__file__).resolve().parents[3] / "chunkhound/providers/llm"
    counters = {"_requests_made", "_tokens_used", "_estimated_tokens_used"}
    violations = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.AugAssign):
                if (
                    isinstance(node.target, ast.Attribute)
                    and node.target.attr in counters
                ):
                    violations.append(f"{path.name}:{node.lineno}")
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.BinOp):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr in counters:
                        if any(
                            isinstance(child, ast.Attribute)
                            and child.attr == target.attr
                            for child in ast.walk(node.value)
                        ):
                            violations.append(f"{path.name}:{node.lineno}")
    assert not violations, "Use LLMProvider._record_usage: " + ", ".join(violations)
