"""Public map output, failure, trial, and replay contracts."""

import argparse
import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

import chunkhound.api.cli.commands.code_mapper as command
from chunkhound.api.cli.parsers.code_mapper_parser import add_map_subparser
from chunkhound.autodoc.index_loader import (
    find_index_file,
    load_topics,
    parse_index_file,
)
from chunkhound.code_mapper.c4 import pipeline as c4_pipeline
from chunkhound.code_mapper.c4.lockfile import LOCK_RELATIVE_PATH
from chunkhound.code_mapper.c4.model import load_c4_pair
from chunkhound.code_mapper.models import CodeMapperPOI
from chunkhound.code_mapper.render import build_topic_artifacts
from chunkhound.code_mapper.service import CodeMapperPipelineResult
from chunkhound.code_mapper.writer import write_code_mapper_outputs
from chunkhound.core.config.config import Config


def parse(repo, out, *flags):
    parser = argparse.ArgumentParser()
    add_map_subparser(parser.add_subparsers(dest="command"))
    return parser.parse_args(["map", str(repo), "--out", str(out), *flags])


def forbidden(*args, **kwargs):
    raise AssertionError("This operation must not run")


@pytest.fixture
def cli(fixture_repo, c4_llm_manager, scripted, monkeypatch, tmp_path):
    monkeypatch.setenv("CHUNKHOUND_USE_RUST", "0")
    monkeypatch.delenv("CH_CODE_MAPPER_WRITE_COMBINED", raising=False)
    config = Config(
        target_dir=fixture_repo,
        embedding={"provider": "openai", "api_key": "test"},
        llm={"provider": "openai", "api_key": "test"},
    )
    monkeypatch.setattr(command, "verify_database_exists", lambda cfg: tmp_path / "db")
    monkeypatch.setattr(
        command, "_create_code_mapper_llm_manager", lambda *a: c4_llm_manager
    )
    monkeypatch.setattr(command, "create_services", lambda **kw: object())
    monkeypatch.setattr(command, "compute_unreferenced_scope_files", lambda **kw: [])
    result = CodeMapperPipelineResult(
        overview_result={"answer": "Overview"},
        poi_sections=[],
        poi_sections_indexed=[],
        failed_poi_sections=[],
        total_points_of_interest=3,
        unified_source_files={"shop/orders.py": "shop/orders.py"},
        unified_chunks_dedup=[],
        total_files_global=10,
        total_chunks_global=10,
        scope_total_files=10,
        scope_total_chunks=10,
    )
    for idx, mode, title, files in (
        (3, "architectural", "Orders", ["shop/orders.py"]),
        (4, "operational", "Run shop", ["shop/cli.py", "README.md"]),
    ):
        poi = CodeMapperPOI(mode=mode, text=title)
        answer = {"answer": title, "metadata": {"sources": {"files": files}}}
        result.poi_sections.append((poi, answer))
        result.poi_sections_indexed.append((idx, poi, answer))
    # A failed architectural topic precedes the successful one: C4 must use the
    # same filenames as the writer, rather than renumbering successful topics.
    result.failed_poi_sections = [
        (1, CodeMapperPOI(mode="architectural", text="Missing"), "Failed")
    ]
    seen = []

    async def research(**kwargs):
        seen.append(kwargs)
        return result

    monkeypatch.setattr(command, "run_code_mapper_pipeline", research)

    def payload(prompt):
        return json.loads(prompt.split("\nInput:\n", 1)[1])

    scripted.answers.update(
        {
            "classify": lambda prompt: {
                "classifications": [
                    {
                        "key": row["key"],
                        "value": "external_system"
                        if row["question"] == "dependency"
                        else "yes",
                    }
                    for row in json.loads(prompt.split("\nItems:\n", 1)[1])
                ]
            },
            "merge": lambda prompt: {
                "components": [
                    {
                        "name": row["name"],
                        "description": "Domain responsibility.",
                        "groups": [row["id"]],
                    }
                    for row in payload(prompt)["groups"]
                ],
                "direct": [],
                "titles": [],
            },
            "titles": lambda prompt: {
                "titles": [
                    {"fingerprint": row["fingerprint"], "title": "gebruikt via API"}
                    for row in payload(prompt)["relations"]
                ]
            },
            "summaries": lambda prompt: {
                "labels": {
                    row["key"]: "gebruikt diensten" for row in payload(prompt)["arrows"]
                }
            },
        }
    )
    return SimpleNamespace(
        repo=fixture_repo,
        out=tmp_path / "out",
        config=config,
        result=result,
        seen=seen,
        provider=scripted,
        monkeypatch=monkeypatch,
    )


def snapshot(path):
    return {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}


def pair(out):
    return load_c4_pair(out / "__c4_model.json", out / "__c4_evidence.json")


async def test_no_c4_output_matches_upstream(cli, tmp_path):
    cli.monkeypatch.setattr(c4_pipeline, "scan_references", forbidden)
    writer_inputs = {}

    def record_writer(**kwargs):
        writer_inputs.update(deepcopy(kwargs))
        return write_code_mapper_outputs(**kwargs)

    cli.monkeypatch.setattr(command, "write_code_mapper_outputs", record_writer)
    await command.code_mapper_command(
        parse(cli.repo, cli.out, "--no-c4", "--combined"), cli.config
    )
    expected = tmp_path / "expected"
    write_code_mapper_outputs(**{**writer_inputs, "out_dir": expected})
    assert not list(cli.out.glob("*_c4_*.json"))
    assert not (cli.repo / LOCK_RELATIVE_PATH).exists()
    assert snapshot(cli.out) == snapshot(expected)


@pytest.mark.parametrize(
    "flags", [("--no-c4", "--no-markdown"), ("--combined", "--no-markdown")]
)
async def test_conflicting_output_flags_exit_2(cli, flags):
    cli.monkeypatch.setattr(command, "apply_code_mapper_workspace_overrides", forbidden)
    with pytest.raises(SystemExit) as exc:
        await command.code_mapper_command(parse(cli.repo, cli.out, *flags), cli.config)
    assert exc.value.code == 2
    assert not cli.seen
    assert not cli.out.exists()


async def test_plan_no_markdown_zero_calls_no_db(cli):
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    lock_path = cli.repo / LOCK_RELATIVE_PATH
    before = lock_path.read_bytes()
    cli.provider.calls.clear()
    cli.seen.clear()
    cli.monkeypatch.setattr(command, "verify_database_exists", forbidden)
    cli.monkeypatch.setattr(command, "_create_code_mapper_llm_manager", forbidden)
    await command.code_mapper_command(
        parse(cli.repo, cli.out, "--plan", "--no-markdown"), cli.config
    )
    model, _ = pair(cli.out)
    assert model.run.kind == "trial"
    assert not cli.provider.calls
    assert not cli.seen
    assert lock_path.read_bytes() == before


async def test_autodoc_loads_only_topics(cli):
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    topics, missing = load_topics(cli.out, parse_index_file(find_index_file(cli.out)))
    artifacts, _ = build_topic_artifacts(
        scope_label="/",
        poi_sections_indexed=cli.result.poi_sections_indexed,
        failed_poi_sections=cli.result.failed_poi_sections,
    )
    assert {topic.source_path.name for topic in topics} == {
        name for name, _ in artifacts
    }
    assert not missing
    model, _ = pair(cli.out)
    covered = {name for element in model.elements for name in element.coverage.topics}
    assert covered == {name for name, _ in artifacts if "missing" not in name}


async def test_llm_failure_contract(cli):
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    lock_path = cli.repo / LOCK_RELATIVE_PATH
    before = lock_path.read_bytes()
    (cli.repo / "README.md").write_text("Changed documentation\n")
    cli.provider.answers["documented"] = ValueError("invalid credentials")
    failed_out = cli.out.parent / "failed"
    with pytest.raises(SystemExit) as exc:
        await command.code_mapper_command(parse(cli.repo, failed_out), cli.config)
    assert exc.value.code == 1
    assert not failed_out.exists() or not list(failed_out.iterdir())
    assert lock_path.read_bytes() == before


async def test_rerun_unchanged_zero_calls_stable_output(cli):
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    first = {
        name: data for name, data in snapshot(cli.out).items() if name.endswith(".json")
    }
    lock_path = cli.repo / LOCK_RELATIVE_PATH
    lock = lock_path.read_bytes()
    cli.provider.calls.clear()
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    assert not cli.provider.calls
    assert {
        name: data for name, data in snapshot(cli.out).items() if name.endswith(".json")
    } == first
    assert lock_path.read_bytes() == lock


async def test_output_validates_against_schema(cli):
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    model, evidence = pair(cli.out)
    schemas = Path(c4_pipeline.__file__).parent / "schemas"
    jsonschema.validate(
        model.model_dump(mode="json", by_alias=True),
        json.loads((schemas / "c4_model.schema.json").read_text()),
    )
    jsonschema.validate(
        evidence.model_dump(mode="json", by_alias=True),
        json.loads((schemas / "c4_evidence.schema.json").read_text()),
    )
    ids = {e.id for e in model.elements} | {r.id for r in model.relations}
    assert set(evidence.element_files) <= ids
    assert {c.target for c in evidence.citations if c.target is not None} <= ids
    assert {r.relation for r in evidence.references if r.relation is not None} <= ids


async def test_no_markdown_still_researches_topics(cli):
    await command.code_mapper_command(
        parse(cli.repo, cli.out, "--no-markdown"), cli.config
    )
    model, _ = pair(cli.out)
    assert model.run.kind == "full"
    assert set(snapshot(cli.out)) == {"__c4_model.json", "__c4_evidence.json"}
    assert any(e.coverage.topics for e in model.elements)
    assert len(cli.seen) == 1


async def test_corrupt_lock_stops_before_research(cli):
    lock = cli.repo / LOCK_RELATIVE_PATH
    lock.parent.mkdir(exist_ok=True)
    lock.write_text("not json")
    cli.monkeypatch.setattr(command, "_create_code_mapper_llm_manager", forbidden)
    with pytest.raises(SystemExit) as exc:
        await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    assert exc.value.code == 1
    assert lock.read_text() == "not json"
    assert not cli.seen


async def test_fatal_c4_error_settles_parallel_research(cli):
    finished = asyncio.Event()

    async def research(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    cli.monkeypatch.setattr(command, "run_code_mapper_pipeline", research)
    cli.provider.answers["classify"] = ValueError("invalid credentials")
    with pytest.raises(SystemExit) as exc:
        await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    assert exc.value.code == 1
    assert finished.is_set()
    assert not cli.out.exists()
    assert not (cli.repo / LOCK_RELATIVE_PATH).exists()


async def test_uncached_trial_needs_no_database_or_model(cli):
    cli.monkeypatch.setattr(command, "verify_database_exists", forbidden)
    cli.monkeypatch.setattr(command, "_create_code_mapper_llm_manager", forbidden)
    await command.code_mapper_command(
        parse(cli.repo, cli.out, "--plan", "--no-markdown"), cli.config
    )
    model, _ = pair(cli.out)
    assert model.run.kind == "trial"
    assert not cli.provider.calls
    assert not cli.seen
    assert not (cli.repo / LOCK_RELATIVE_PATH).exists()
    assert set(snapshot(cli.out)) == {"__c4_model.json", "__c4_evidence.json"}


async def test_plan_keeps_overview_and_adds_zero_call_trial(cli):
    async def overview(**kwargs):
        return "Overview", [CodeMapperPOI(mode="architectural", text="Orders")]

    cli.monkeypatch.setattr(command, "run_code_mapper_overview_hyde", overview)
    cli.monkeypatch.setattr(command, "verify_database_exists", forbidden)
    await command.code_mapper_command(parse(cli.repo, cli.out, "--plan"), cli.config)
    model, _ = pair(cli.out)
    assert (cli.out / "__overview.md").is_file()
    assert model.run.kind == "trial"
    assert not cli.provider.calls
    assert not cli.seen
    assert not (cli.repo / LOCK_RELATIVE_PATH).exists()


async def test_transient_failure_reports_fallback_without_caching_it(cli, capsys):
    cli.provider.answers["merge"] = TimeoutError("temporarily unavailable")
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    model, _ = pair(cli.out)
    count = model.run.fallback_count
    assert count > 0
    assert (
        f"C4: {count} elementen via terugval (niet opgeslagen)"
        in capsys.readouterr().out
    )
    document = json.loads((cli.repo / LOCK_RELATIVE_PATH).read_text())
    assert document["scopes"]["/"]["components"] == {}
