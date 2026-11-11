"""Frozen HyDE plan contracts at the CLI and provider boundaries."""

import argparse
from types import SimpleNamespace

import pytest

import chunkhound.api.cli.commands.code_mapper as command
from chunkhound.api.cli.parsers.code_mapper_parser import add_map_subparser
from chunkhound.core.config.config import Config


class PlanProvider:
    name = "fake"
    model = "plan-v1"
    reasoning_effort = "low"
    base_url = "http://unused.invalid"

    def __init__(self):
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            content=f"1. **Plan topic {self.calls}** — Explore workflows."
        )


def parse(repo, out, *flags):
    parser = argparse.ArgumentParser()
    add_map_subparser(parser.add_subparsers(dest="command"))
    return parser.parse_args(["map", str(repo), "--out", str(out), *flags])


@pytest.fixture
def planning(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def app(): return 1\n")
    config = Config(target_dir=repo, llm={"provider": "openai", "api_key": "fake"})
    provider = PlanProvider()
    manager = SimpleNamespace(
        is_configured=lambda: True, get_synthesis_provider=lambda: provider
    )
    monkeypatch.setattr(command, "_create_code_mapper_llm_manager", lambda *a: manager)
    return repo, tmp_path / "out", config, provider


async def test_map_dev_cache_freezes_plan_after_source_changes(planning, capsys):
    repo, out, config, provider = planning
    args = parse(repo, out, "--plan", "--no-c4", "--dev-cache")
    await command.code_mapper_command(args, config)
    assert provider.calls == 2
    plans = {p.name: p.read_text() for p in out.glob("hyde_plan_*.md")}
    assert len(plans) == 2
    capsys.readouterr()

    # A warm run republishes the raw plans even into a fresh output directory.
    (repo / "app.py").write_text("def app(): return 2\n")
    (repo / "new.py").write_text("# new layout\n")
    for path in out.glob("hyde_plan_*.md"):
        path.unlink()
    await command.code_mapper_command(args, config)
    assert provider.calls == 2
    assert {p.name: p.read_text() for p in out.glob("hyde_plan_*.md")} == plans
    assert "plan reused (from " in capsys.readouterr().out

    args.refresh_plan = True
    await command.code_mapper_command(args, config)
    assert provider.calls == 4
    assert "plan refreshed" in capsys.readouterr().out
    args.refresh_plan = False
    await command.code_mapper_command(args, config)
    assert provider.calls == 4
    assert {p.name: p.read_text() for p in out.glob("hyde_plan_*.md")} != plans


async def test_map_without_dev_cache_never_reads_or_writes_plan_cache(planning):
    repo, out, config, provider = planning
    args = parse(repo, out, "--plan", "--no-c4")
    await command.code_mapper_command(args, config)
    await command.code_mapper_command(args, config)
    assert provider.calls == 4
    assert not (repo / ".chunkhound" / "extraction").exists()
    args.dev_cache = True
    await command.code_mapper_command(args, config)
    args.dev_cache = False
    await command.code_mapper_command(args, config)
    assert provider.calls == 8  # Ignores even a populated cache.


@pytest.mark.parametrize(
    "change", ["model", "reasoning_effort", "audience", "context", "comprehensiveness"]
)
async def test_plan_inputs_invalidate_cache(planning, change):
    repo, out, config, provider = planning
    args = parse(repo, out, "--plan", "--no-c4", "--dev-cache")
    await command.code_mapper_command(args, config)
    if change in {"model", "reasoning_effort"}:
        setattr(provider, change, "changed")
    elif change == "context":
        args.context = repo / "context.md"
        args.context.write_text("A different planning context.")
    else:
        setattr(args, change, "technical" if change == "audience" else "low")
    await command.code_mapper_command(args, config)
    assert provider.calls == 4


@pytest.mark.parametrize(
    "flags",
    [
        ("--refresh-plan",),
        ("--c4-only", "--dev-cache"),
        ("--c4-only", "--refresh-plan"),
        ("--c4-only", "--dev-cache", "--refresh-plan"),
    ],
)
async def test_invalid_plan_cache_flags_fail_before_provider_setup(planning, flags):
    repo, out, config, provider = planning
    with pytest.raises(SystemExit) as exc:
        await command.code_mapper_command(parse(repo, out, *flags), config)
    assert exc.value.code == 2
    assert provider.calls == 0
    assert not (repo / ".chunkhound").exists()
