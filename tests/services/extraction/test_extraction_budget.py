"""Contract: declared input limits bound every extraction request."""

import pytest

from chunkhound.core.config.config import Config
from chunkhound.services.extraction.budget import (
    effective_target,
    resolve_input_limit,
)


def _utility_role(monkeypatch, tmp_path, **env: str) -> dict:
    for name in (
        "CHUNKHOUND_LLM_UTILITY_MAX_INPUT_CHARS",
        "CHUNKHOUND_LLM_UTILITY_MAX_INPUT_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    config = Config(target_dir=tmp_path)
    assert config.llm is not None
    return config.llm.get_provider_config_for_role("utility")


@pytest.fixture
def codex_env(monkeypatch):
    monkeypatch.setenv("CHUNKHOUND_LLM_PROVIDER", "codex-cli")


def test_input_limit_override_from_config(monkeypatch, tmp_path, codex_env):
    overridden = resolve_input_limit(
        _utility_role(
            monkeypatch, tmp_path, CHUNKHOUND_LLM_UTILITY_MAX_INPUT_CHARS="50000"
        )
    )
    assert overridden.max_chars == 50_000
    assert effective_target(overridden) == 48_000

    known = resolve_input_limit(_utility_role(monkeypatch, tmp_path))
    assert known.max_chars == 1_048_576

    assert resolve_input_limit({"provider": "unknown"}).max_chars == 400_000

    by_tokens = resolve_input_limit(
        _utility_role(
            monkeypatch, tmp_path, CHUNKHOUND_LLM_UTILITY_MAX_INPUT_TOKENS="10000"
        )
    )
    assert by_tokens.max_tokens == 10_000
    assert effective_target(by_tokens) <= 31_332
