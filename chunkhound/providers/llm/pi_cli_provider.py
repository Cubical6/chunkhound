"""Isolated, tool-free Pi CLI completions with NDJSON error detection."""

import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from chunkhound.core.config.llm_config import DEFAULT_LLM_TIMEOUT
from chunkhound.core.exceptions.core import ConfigurationError
from chunkhound.providers.llm.base_cli_provider import (
    BaseCLIProvider,
    build_cli_argv,
    resolve_cli_binary,
    terminate_cli_process,
)

BASE_SYSTEM_PROMPT = "You are a precise assistant. Follow the instructions exactly."
VALID_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh"}
ISOLATION_FLAGS = (
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
)
_TRANSIENT_ERROR = re.compile(
    r"\b429\b|rate limit|overloaded|timeout|\b5\d\d\b|\b5xx\b", re.IGNORECASE
)


class _PiResponseError(RuntimeError):
    """An API error reported in Pi's successful-exit event stream."""


class PiCLIProvider(BaseCLIProvider):
    """Use Pi's authenticated model access without its coding-agent harness."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "",
        base_url: str | None = None,
        timeout: int = DEFAULT_LLM_TIMEOUT,
        max_retries: int = 3,
        reasoning_effort: str | None = None,
    ) -> None:
        super().__init__(api_key, model, base_url, timeout, max_retries)
        provider, separator, model_id = model.partition("/")
        if not separator or not provider.strip() or not model_id.strip():
            raise ConfigurationError(
                config_key="llm.model",
                config_value=model,
                reason="pi-cli requires a model in provider/id format",
            )
        self._reasoning_effort = (
            reasoning_effort.strip().lower() if reasoning_effort is not None else None
        )
        if (
            self._reasoning_effort is not None
            and self._reasoning_effort not in VALID_REASONING_EFFORTS
        ):
            raise ConfigurationError(
                config_key="llm.reasoning_effort",
                config_value=reasoning_effort,
                reason=f"pi-cli requires one of {sorted(VALID_REASONING_EFFORTS)}",
            )
        if max_retries < 1:
            raise ConfigurationError(
                config_key="llm.max_retries",
                config_value=max_retries,
                reason="pi-cli requires at least one attempt",
            )
        logger.debug(
            "pi-cli ignores max_completion_tokens: Pi has no output-token flag"
        )

    def _get_provider_name(self) -> str:
        return "pi-cli"

    def _build_argv(self, binary: str, system_path: Path | None = None) -> list[str]:
        """Build arguments without including user or ChunkHound system text."""
        args = ["-p", "--mode", "json", "--model", self._model, *ISOLATION_FLAGS]
        args.extend(["--system-prompt", BASE_SYSTEM_PROMPT])
        if system_path is not None:
            args.extend(["--append-system-prompt", str(system_path)])
        if self._reasoning_effort is not None:
            args.extend(["--thinking", self._reasoning_effort])
        return build_cli_argv(binary, *args)

    def _parse_ndjson(self, stdout: bytes) -> str:
        """Read only the last completed assistant message, not streaming deltas."""
        message: dict[str, Any] | None = None
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") != "message_end":
                continue
            candidate = event.get("message")
            if isinstance(candidate, dict) and candidate.get("role") == "assistant":
                message = candidate

        if message is None:
            raise RuntimeError("pi-cli: no assistant message in output")
        stop_reason = message.get("stopReason")
        if stop_reason in ("error", "aborted"):
            error = message.get("errorMessage") or f"assistant {stop_reason}"
            raise _PiResponseError(f"pi-cli: {error}")
        if stop_reason == "length":
            logger.warning("pi-cli response reached the model's output length limit")
        content = message.get("content", [])
        if not isinstance(content, list):
            return ""
        return "".join(
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )

    async def _run_single_attempt(
        self, binary: str, prompt: str, system: str | None, timeout: int
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="chunkhound-pi-") as workdir:
            system_path = None
            if system is not None:
                system_path = Path(workdir) / "system.md"
                system_path.write_bytes(system.encode("utf-8"))
            process = await asyncio.create_subprocess_exec(
                *self._build_argv(binary, system_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")), timeout=timeout
                )
                if process.returncode != 0:
                    tail = "\n".join(
                        stderr.decode("utf-8", errors="replace").splitlines()[-20:]
                    )
                    raise RuntimeError(
                        f"pi-cli failed (exit {process.returncode}): {tail}"
                    )
                return self._parse_ndjson(stdout)
            finally:
                # Also reap the process on cancellation or unexpected pipe errors.
                await terminate_cli_process(process)

    async def _run_cli_command(
        self,
        prompt: str,
        system: str | None = None,
        max_completion_tokens: int | None = None,
        timeout: int | None = None,
    ) -> str:
        # Resolve before changing cwd; PATH may contain relative directories.
        binary = str(
            Path(resolve_cli_binary("pi", env_var="CHUNKHOUND_PI_BIN")).absolute()
        )
        request_timeout = self._timeout if timeout is None else timeout
        for attempt in range(self._max_retries):
            try:
                return await self._run_single_attempt(
                    binary, prompt, system, request_timeout
                )
            except asyncio.TimeoutError as error:
                if attempt + 1 == self._max_retries:
                    raise RuntimeError(
                        f"pi-cli timed out after {self._max_retries} attempts "
                        f"({request_timeout}s per attempt)"
                    ) from error
            except _PiResponseError as error:
                if (
                    not _TRANSIENT_ERROR.search(str(error))
                    or attempt + 1 == self._max_retries
                ):
                    raise
            logger.debug("pi-cli retrying transient failure (attempt {})", attempt + 1)
            await asyncio.sleep(2**attempt)
        raise RuntimeError("pi-cli exhausted its attempt budget")

    async def health_check(self) -> dict[str, Any]:
        """Check the binary with --version, without making a model request."""
        try:
            binary = str(
                Path(resolve_cli_binary("pi", env_var="CHUNKHOUND_PI_BIN")).absolute()
            )
            with tempfile.TemporaryDirectory(prefix="chunkhound-pi-") as workdir:
                process = await asyncio.create_subprocess_exec(
                    *build_cli_argv(binary, "--version"),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=workdir,
                )
                try:
                    _, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=self.HEALTH_CHECK_TIMEOUT
                    )
                    if process.returncode != 0:
                        raise RuntimeError(
                            f"pi-cli --version failed (exit {process.returncode}): "
                            + stderr.decode("utf-8", errors="replace")
                        )
                finally:
                    await terminate_cli_process(process)
            return {"status": "healthy", "provider": self.name, "model": self.model}
        except Exception as error:
            return {"status": "unhealthy", "provider": self.name, "error": str(error)}
