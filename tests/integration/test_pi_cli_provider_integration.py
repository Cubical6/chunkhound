"""Opt-in integration test for an installed and authenticated pi CLI."""

import os
import shutil

import pytest

from chunkhound.providers.llm.pi_cli_provider import PiCLIProvider


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pi_cli_completion() -> None:
    model = os.environ.get("CHUNKHOUND_TEST_PI_MODEL")
    if not model:
        pytest.skip("Set CHUNKHOUND_TEST_PI_MODEL to opt in to a real pi model call")
    binary = os.environ.get("CHUNKHOUND_PI_BIN") or "pi"
    if not shutil.which(binary):
        pytest.skip(f"Pi CLI binary not found: {binary}")

    provider = PiCLIProvider(model=model, timeout=60, max_retries=1)
    response = await provider.complete("Reply with exactly: OK")
    assert response.content.strip() == "OK"
