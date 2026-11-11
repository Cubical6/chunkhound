"""User-facing Pi contracts, faking only the subprocess boundary."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from chunkhound.core.exceptions.core import ConfigurationError
from chunkhound.providers.llm.pi_cli_provider import PiCLIProvider


def assistant(text="BANANA", stop="stop", error=None):
    message = {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "not part of the answer"},
            {"type": "text", "text": text},
        ],
        "stopReason": stop,
        "usage": {"input": 53, "output": 6, "totalTokens": 59},
    }
    if error is not None:
        message["errorMessage"] = error
    return json.dumps({"type": "message_end", "message": message}).encode() + b"\n"


SUCCESS = assistant()
ERROR = assistant("", "error", "Model is not supported")
LENGTH = assistant("Partial answer", "length")
NO_ASSISTANT = b'{"type":"message_end","message":{"role":"user"}}\n'
NOISY_SUCCESS = b"Pi diagnostic\nnot json\n[]\nnull\n" + SUCCESS


@pytest.fixture
def fake_pi(monkeypatch, tmp_path):
    """Capture argv/stdin/cwd while the real provider manages each call."""
    binary = tmp_path / "custom-pi"
    binary.touch()
    monkeypatch.setenv("CHUNKHOUND_PI_BIN", str(binary))
    fake = SimpleNamespace(binary=binary, responses=[{}], calls=[], processes=[])

    async def spawn(*argv, **kwargs):
        cwd = Path(kwargs["cwd"])
        assert cwd.is_dir()
        system = None
        if "--append-system-prompt" in argv:
            path = Path(argv[argv.index("--append-system-prompt") + 1])
            assert path.parent == cwd
            system = path.read_bytes().decode("utf-8")
        call = SimpleNamespace(argv=argv, cwd=cwd, system=system, stdin=None)
        fake.calls.append(call)
        response = fake.responses.pop(0)
        process = MagicMock(returncode=None, pid=None)

        async def communicate(data=None):
            call.stdin = data
            if "exception" in response:
                raise response["exception"]
            process.returncode = response.get("returncode", 0)
            return response.get("stdout", SUCCESS), response.get("stderr", b"")

        def kill():
            process.returncode = -9

        process.communicate = AsyncMock(side_effect=communicate)
        process.kill.side_effect = kill
        process.wait = AsyncMock(return_value=-9)
        fake.processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    yield fake
    # Covers success, parsing failures, process failures, timeout and cancellation.
    assert all(not call.cwd.exists() for call in fake.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("noisy", [False, True])
async def test_pi_cli_returns_final_assistant_text(fake_pi, noisy):
    stream = (
        assistant("Earlier answer")
        + assistant("", "error", "429 rate limit (Pi will retry internally)")
        + b'{"type":"message_update","message":{"role":"assistant"}}\n'
        + (NOISY_SUCCESS if noisy else SUCCESS)
        + b'{"type":"agent_end","willRetry":false}\n'
    )
    fake_pi.responses = [{"stdout": stream}]
    provider = PiCLIProvider(model="openai-codex/test")
    response = await provider.complete("Question")
    assert response.content == "BANANA"
    assert response.model == "openai-codex/test"
    assert provider.name == "pi-cli"
    assert provider.get_usage_stats()["requests_made"] == 1


@pytest.mark.asyncio
async def test_pi_cli_runs_isolated(fake_pi):
    # Larger than Linux's per-argument limit; must never be sent in argv.
    prompt = "user text €\n" * 16000
    system = "  Exact system instructions\r\nwith Unicode: λ\n"
    provider = PiCLIProvider(model="openai-codex/test")
    await provider.complete(prompt, system=system, max_completion_tokens=123)
    call = fake_pi.calls[0]
    argv = call.argv
    assert argv[0] == str(fake_pi.binary)
    assert argv[1:6] == ("-p", "--mode", "json", "--model", "openai-codex/test")
    for flag in (
        "--no-tools",
        "--no-mcp",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-session",
        "--no-approve",
        "--offline",
    ):
        assert flag in argv
    assert "--system-prompt" in argv
    assert argv[argv.index("--system-prompt") + 1].strip()
    assert call.system == system
    assert call.stdin == prompt.encode("utf-8")
    assert prompt not in argv and system not in argv
    assert "123" not in argv
    assert call.cwd != Path.cwd()
    assert not call.cwd.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["error", "aborted"])
async def test_pi_cli_error_stop_reason_raises(fake_pi, stop):
    fake_pi.responses = [{"stdout": assistant("", stop, "Invalid credentials")}]
    with pytest.raises(RuntimeError, match="Invalid credentials"):
        await PiCLIProvider(model="p/m").complete("Question")
    assert len(fake_pi.calls) == 1


@pytest.mark.asyncio
async def test_pi_cli_nonzero_exit_raises_with_stderr(fake_pi):
    stderr = "\n".join(f"error line {i}" for i in range(30)).encode()
    # Exit status takes priority over even a transient JSON error.
    fake_pi.responses = [
        {
            "stdout": assistant("", "error", "429 rate limit"),
            "stderr": stderr,
            "returncode": 1,
        }
    ]
    with pytest.raises(RuntimeError, match="exit 1") as caught:
        await PiCLIProvider(model="p/m").complete("Question")
    assert "error line 29" in str(caught.value)
    assert "error line 9\n" not in str(caught.value)
    assert "429" not in str(caught.value)
    assert len(fake_pi.calls) == 1


@pytest.mark.asyncio
async def test_pi_cli_timeout_terminates_process(fake_pi):
    fake_pi.responses = [{"exception": asyncio.TimeoutError()} for _ in range(2)]
    with pytest.raises(RuntimeError, match="timed out after 2 attempts"):
        await PiCLIProvider(model="p/m", max_retries=2).complete("Question", timeout=1)
    assert len(fake_pi.calls) == 2
    assert fake_pi.calls[0].cwd != fake_pi.calls[1].cwd
    for process in fake_pi.processes:
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_pi_cli_cancellation_terminates_process(fake_pi):
    fake_pi.responses = [{"exception": asyncio.CancelledError()}]
    with pytest.raises(asyncio.CancelledError):
        await PiCLIProvider(model="p/m").complete("Question")
    fake_pi.processes[0].kill.assert_called_once()
    fake_pi.processes[0].wait.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("effort", [None, "minimal", "low", "medium", "high", "xhigh"])
async def test_pi_cli_forwards_reasoning_effort_as_thinking(fake_pi, effort):
    await PiCLIProvider(model="p/m", reasoning_effort=effort).complete("Question")
    argv = fake_pi.calls[0].argv
    if effort is None:
        assert "--thinking" not in argv
    else:
        assert argv[argv.index("--thinking") + 1] == effort
    assert "--append-system-prompt" not in argv


@pytest.mark.parametrize("model", ["", "model", "/model", "provider/", " /m", "p/ "])
def test_pi_cli_rejects_model_without_provider_segment(model):
    with pytest.raises(ConfigurationError, match="pi-cli.*provider/id"):
        PiCLIProvider(model=model)


def test_pi_cli_rejects_invalid_reasoning_effort():
    with pytest.raises(ConfigurationError, match="reasoning_effort"):
        PiCLIProvider(model="p/m", reasoning_effort="invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", ["429", "rate limit", "overloaded", "timeout", "503", "5xx"]
)
async def test_pi_cli_retries_transient_error_then_succeeds(fake_pi, error):
    fake_pi.responses = [{"stdout": assistant("", "error", error)}, {}]
    response = await PiCLIProvider(model="p/m", max_retries=2).complete("Question")
    assert response.content == "BANANA"
    assert len(fake_pi.calls) == 2


@pytest.mark.asyncio
async def test_pi_cli_does_not_retry_model_error(fake_pi):
    fake_pi.responses = [{"stdout": ERROR}]
    with pytest.raises(RuntimeError, match="Model is not supported"):
        await PiCLIProvider(model="p/m").complete("Question")
    assert len(fake_pi.calls) == 1


@pytest.mark.asyncio
async def test_pi_cli_transient_error_obeys_total_attempt_budget(fake_pi):
    fake_pi.responses = [{"stdout": assistant("", "error", "429")} for _ in range(2)]
    with pytest.raises(RuntimeError, match="429"):
        await PiCLIProvider(model="p/m", max_retries=2).complete("Question")
    assert len(fake_pi.calls) == 2


@pytest.mark.asyncio
async def test_pi_cli_length_stop_returns_text_and_warns(fake_pi):
    from loguru import logger

    fake_pi.responses = [{"stdout": LENGTH}]
    warnings = []
    sink = logger.add(lambda message: warnings.append(str(message)), level="WARNING")
    try:
        response = await PiCLIProvider(model="p/m").complete("Question")
    finally:
        logger.remove(sink)
    assert response.content == "Partial answer"
    assert any("length limit" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_pi_cli_missing_assistant_raises(fake_pi):
    fake_pi.responses = [{"stdout": NO_ASSISTANT}]
    with pytest.raises(RuntimeError, match="no assistant message"):
        await PiCLIProvider(model="p/m").complete("Question")
    assert len(fake_pi.calls) == 1


@pytest.mark.asyncio
async def test_pi_cli_empty_assistant_raises(fake_pi):
    fake_pi.responses = [{"stdout": assistant("")}]
    with pytest.raises(RuntimeError, match="empty response"):
        await PiCLIProvider(model="p/m").complete("Question")


@pytest.mark.asyncio
@pytest.mark.parametrize("returncode", [0, 1])
async def test_pi_cli_health_check_only_requests_version(fake_pi, returncode):
    fake_pi.responses = [{"stdout": b"1.0.8", "returncode": returncode}]
    health = await PiCLIProvider(model="p/m").health_check()
    assert health["status"] == ("healthy" if returncode == 0 else "unhealthy")
    assert fake_pi.calls[0].argv == (str(fake_pi.binary), "--version")
    assert fake_pi.calls[0].stdin is None
