from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from chunkhound.api.cli.commands import autodoc_autorun as autorun
from chunkhound.api.cli.commands.autodoc_autorun import resolve_auto_map_options


@pytest.mark.asyncio
@pytest.mark.parametrize("dev_cache", [False, True])
async def test_autorun_forwards_dev_cache(
    tmp_path: Path, monkeypatch, dev_cache: bool
) -> None:
    from chunkhound.api.cli.commands import code_mapper

    monkeypatch.setattr(autorun.prompts, "is_interactive", lambda: True)
    monkeypatch.setattr(
        autorun, "confirm_autorun_and_validate_prereqs", lambda **_: None
    )
    mapper = AsyncMock()
    monkeypatch.setattr(code_mapper, "code_mapper_command", mapper)
    args = Namespace(
        map_in=None,
        map_out_dir=tmp_path / "maps",
        map_comprehensiveness="medium",
        map_audience="balanced",
        map_context=None,
        dev_cache=dev_cache,
    )
    monkeypatch.setattr(autorun.prompts, "prompt_text", lambda *_, **__: None)

    await autorun.ensure_map_dir(
        args=args,
        config=object(),
        formatter=SimpleNamespace(info=lambda _: None),
        output_dir=tmp_path / "site",
    )

    map_args = mapper.await_args.args[0]
    assert map_args.dev_cache is dev_cache
    assert map_args.refresh_plan is False
    assert map_args.c4_only is False


def test_resolve_auto_map_options_defaults_noninteractive(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    output_dir = (tmp_path / "site").resolve()

    args = SimpleNamespace(
        map_out_dir=None,
        map_comprehensiveness=None,
        map_context=None,
        map_audience=None,
        audience="end-user",
    )

    options = resolve_auto_map_options(args=args, output_dir=output_dir)

    assert options.map_out_dir == output_dir.with_name(f"map_{output_dir.name}")
    assert options.comprehensiveness == "medium"
    assert options.audience == "end-user"
    assert options.map_context is None


def test_resolve_auto_map_options_honors_explicit_args(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    output_dir = (tmp_path / "site").resolve()

    args = SimpleNamespace(
        map_out_dir="maps",
        map_comprehensiveness="high",
        map_context="ctx.md",
        map_audience="technical",
        audience="balanced",
    )

    options = resolve_auto_map_options(args=args, output_dir=output_dir)

    assert options.map_out_dir == (tmp_path / "maps").resolve()
    assert options.comprehensiveness == "high"
    assert options.audience == "technical"
    assert options.map_context == Path("ctx.md")
