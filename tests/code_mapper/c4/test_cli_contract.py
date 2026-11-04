"""Public map output, failure, trial, and replay contracts."""

import argparse
import asyncio
import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

import chunkhound.api.cli.commands.code_mapper as command
from chunkhound.api.cli.parsers.code_mapper_parser import add_map_subparser
from chunkhound.autodoc.architecture.coverage import CoverageIndex
from chunkhound.autodoc.architecture.loader import ModelLoader
from chunkhound.autodoc.index_loader import (
    find_index_file,
    load_topics,
    parse_index_file,
)
from chunkhound.autodoc.models import DocsitePage
from chunkhound.code_mapper.c4 import pipeline as c4_pipeline
from chunkhound.code_mapper.c4.contract import ContractCounts
from chunkhound.code_mapper.c4.files import select_scope_files
from chunkhound.code_mapper.c4.llm import AnswerRejectedError
from chunkhound.code_mapper.c4.lockfile import LOCK_RELATIVE_PATH
from chunkhound.code_mapper.c4.model import load_c4_pair
from chunkhound.code_mapper.models import CodeMapperPOI, HydeConfig
from chunkhound.code_mapper.render import build_topic_artifacts
from chunkhound.code_mapper.scope import collect_scope_files
from chunkhound.code_mapper.service import CodeMapperPipelineResult
from chunkhound.code_mapper.writer import write_code_mapper_outputs
from chunkhound.core.config.c4_config import C4Config
from chunkhound.core.config.config import Config
from tests.code_mapper.c4.conftest import (
    documented_fragments,
    documented_per_fragment,
)


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
                        "name": row["dir"],
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
                "labels": [
                    {"key": row["key"], "label": "gebruikt diensten"}
                    for row in payload(prompt)["arrows"]
                ]
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


CONTRACT = "__c4_model.json"
MAP_MODEL = "__c4_map_model.json"
MAP_EVIDENCE = "__c4_map_evidence.json"
OLD_EVIDENCE = "__c4_evidence.json"


def pair(out):
    return load_c4_pair(out / MAP_MODEL, out / MAP_EVIDENCE)


def load_contract_quietly(out):
    """Read the contract the way AutoDoc does; any warning fails the contract."""
    warnings = []
    loaded = ModelLoader.load(
        index_path=out / "__code_mapper_index.md", log_warning=warnings.append
    )
    assert warnings == []
    assert loaded is not None
    return loaded


@pytest.mark.parametrize("flags", [("--no-c4",), ("--no-c4", "--combined")])
async def test_no_c4_output_is_byte_identical(cli, tmp_path, flags):
    cli.monkeypatch.setattr(c4_pipeline, "scan_references", forbidden)
    writer_inputs = {}

    def record_writer(**kwargs):
        writer_inputs.update(deepcopy(kwargs))
        return write_code_mapper_outputs(**kwargs)

    cli.monkeypatch.setattr(command, "write_code_mapper_outputs", record_writer)
    await command.code_mapper_command(parse(cli.repo, cli.out, *flags), cli.config)
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
    published = snapshot(cli.out)
    assert CONTRACT in published
    with pytest.raises(SystemExit) as exc:
        await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    assert exc.value.code == 1
    assert snapshot(cli.out) == published


async def test_rerun_unchanged_zero_calls_stable_output(cli):
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    first = {
        name: data for name, data in snapshot(cli.out).items() if name.endswith(".json")
    }
    assert set(first) == {CONTRACT, MAP_MODEL, MAP_EVIDENCE}
    lock_path = cli.repo / LOCK_RELATIVE_PATH
    lock = lock_path.read_bytes()
    cli.provider.calls.clear()
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    assert not cli.provider.calls
    assert {
        name: data for name, data in snapshot(cli.out).items() if name.endswith(".json")
    } == first
    assert lock_path.read_bytes() == lock


def publish_to_origin(repo):
    """Make every commit count as pushed, so source links depend on the worktree."""
    for args in (
        ["remote", "add", "origin", "https://example.invalid/shop.git"],
        ["update-ref", "refs/remotes/origin/main", "HEAD"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.mark.parametrize("inside", [False, True], ids=["outside", "inside"])
async def test_second_run_makes_no_merge_call_and_identical_contract(cli, inside):
    """Invariant 5. The out directory stays untracked, and nothing is committed."""
    publish_to_origin(cli.repo)
    out = cli.repo / "docs" if inside else cli.out
    await command.code_mapper_command(parse(cli.repo, out), cli.config)
    assert pair(out)[0].run.fallback_count == 0
    contract = (out / CONTRACT).read_bytes()
    assert json.loads(contract)["repositories"][0]["remote_url"]
    lock_path = cli.repo / LOCK_RELATIVE_PATH
    lock = lock_path.read_bytes()
    if inside:
        # The test double does no research, so it left no HyDE files behind.
        write_files(
            cli.repo,
            ["docs/hyde_plan_arch__.md", "docs/hyde_scope_prompt_ops__.md"],
        )
        # Without the own-output rule this run would read all of them as sources.
        unfiltered = select_scope_files(
            scope_path=cli.repo, project_root=cli.repo, config=cli.config
        ).files
        assert {
            f"docs/{CONTRACT}",
            "docs/hyde_plan_arch__.md",
            "docs/hyde_scope_prompt_ops__.md",
        } <= set(unfiltered)
    cli.provider.calls.clear()
    await command.code_mapper_command(parse(cli.repo, out), cli.config)
    assert cli.provider.calls["merge"] == 0
    assert (out / CONTRACT).read_bytes() == contract
    assert lock_path.read_bytes() == lock


def c4_report(output):
    return [
        line.removeprefix("[INFO] ")
        for line in output.splitlines()
        if line.startswith(("[INFO] C4-bron", "[INFO] C4-merge", "[INFO] C4-contract"))
    ]


async def test_report_lines(cli, capsys):
    write_files(cli.repo, ["shop/test_cart.py", "shop/skip.py"])
    config = cli.config.model_copy(update={"c4": C4Config(exclude=["shop/skip.py"])})
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/shop.git"],
        cwd=cli.repo,
        check=True,
    )
    await command.code_mapper_command(parse(cli.repo, cli.out), config)
    head = pair(cli.out)[0].run.head_sha
    source = (
        "C4-bron: 14 bestanden geanalyseerd, 1 uitgesloten als testcode, "
        "1 door c4.exclude"
    )
    contract = [
        "C4-contract: 12 elementen, 1 relaties, 21 bronnen, 0 labels, 2 topics",
        "C4-contract weggelaten: 0 componenten zonder container, 0 elementen zonder "
        "bron, 0 componenten zonder geldige container, 0 relaties zonder eindpunt, "
        "0 relaties zonder bron, 0 labels, 0 relaties binnen een container, "
        "0 overbodige relaties van directe bestanden",
        "C4-contract zonder relatie weggelaten: 1 externe systemen (Stripe), "
        "1 personen (beheerder)",
        "C4-contract onvolledig: 1 zonder technologie, 6 zonder omschrijving, "
        "0 relaties tussen containers zonder protocol",
        f"C4-contract repository .: geen bronlinks (commit {head} staat niet op "
        "origin)",
    ]
    assert c4_report(capsys.readouterr().out) == [
        source,
        "C4-merge container:acme-admin: 2 bouwstenen, 2 geplaatst, "
        "0 plaatsingen verwijderd",
        "C4-merge container:shop: 3 bouwstenen, 3 geplaatst, 0 plaatsingen verwijderd",
        "C4-merge container:web: 2 bouwstenen, 2 geplaatst, 0 plaatsingen verwijderd",
        *contract,
    ]

    # Nothing is pending any more: no merge line, but the override is reported.
    lock_path = cli.repo / LOCK_RELATIVE_PATH
    document = json.loads(lock_path.read_text())
    document["scopes"]["/"]["overrides"]["placements"]["container:shop/gone"] = (
        "component:shop"
    )
    lock_path.write_text(json.dumps(document))
    await command.code_mapper_command(parse(cli.repo, cli.out), config)
    assert c4_report(capsys.readouterr().out) == [
        source,
        "C4-merge: override voor onbekende groep genegeerd: container:shop/gone",
        *contract,
    ]


async def test_report_states_each_contract_count_under_its_own_label(cli, capsys):
    build = c4_pipeline.build_contract

    def counted(*args):
        return build(*args)[0], ContractCounts(
            1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, ("Stripe", "Mollie"), ("Beheerder",)
        )

    cli.monkeypatch.setattr(c4_pipeline, "build_contract", counted)
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    report = c4_report(capsys.readouterr().out)
    assert (
        "C4-contract weggelaten: 1 componenten zonder container, 2 elementen zonder "
        "bron, 3 componenten zonder geldige container, 4 relaties zonder eindpunt, "
        "5 relaties zonder bron, 6 labels, 10 relaties binnen een container, "
        "11 overbodige relaties van directe bestanden"
    ) in report
    assert (
        "C4-contract zonder relatie weggelaten: 2 externe systemen (Stripe, Mollie), "
        "1 personen (Beheerder)"
    ) in report
    assert (
        "C4-contract onvolledig: 7 zonder technologie, 8 zonder omschrijving, "
        "9 relaties tussen containers zonder protocol"
    ) in report


async def test_report_names_why_groups_stay_unplaced(cli, capsys):
    """Repaired, then the narrow retry fails: only the placed part stays placed."""

    def respond(prompt):
        data = json.loads(prompt.split("\nInput:\n", 1)[1])
        if data["existing"]:
            raise TimeoutError("temporarily unavailable")
        first = data["groups"][0]["id"]
        return {
            "components": [
                {"name": "Eerste", "description": "x", "groups": [first, "G99"]}
            ],
            "direct": [],
            "titles": [],
        }

    cli.provider.answers["merge"] = respond
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    lines = [
        line
        for line in c4_report(capsys.readouterr().out)
        if line.startswith("C4-merge")
    ]
    assert lines == [
        f"C4-merge container:{name}: {total} bouwstenen, 1 geplaatst, "
        f"{total - 1} niet geplaatst (tijdelijke fout), 1 plaatsingen verwijderd"
        for name, total in (("acme-admin", 2), ("shop", 3), ("web", 2))
    ]


async def test_report_says_a_trial_writes_no_contract(cli, capsys):
    await command.code_mapper_command(
        parse(cli.repo, cli.out, "--plan", "--no-markdown"), cli.config
    )
    report = c4_report(capsys.readouterr().out)
    assert report[0].startswith("C4-bron: ")
    # The trial makes no call, so a merge line would contradict "0 pogingen".
    assert report[1:] == ["C4-contract: niet geschreven (proefrun)"]


async def test_end_to_end_contract_links_topics_to_pages(cli):
    """A topic in the contract binds to the page AutoDoc builds from the same run."""
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    index_path = find_index_file(cli.out)
    warnings = []
    model = ModelLoader.load(index_path=index_path, log_warning=warnings.append)
    assert model is not None
    topics, missing = load_topics(cli.out, parse_index_file(index_path))
    assert not missing
    pages = [
        DocsitePage(
            order=topic.order,
            title=topic.title,
            slug=f"topic-{topic.order}",
            description="",
            body_markdown=topic.body_markdown,
            source_path=str(topic.source_path),
        )
        for topic in topics
    ]
    coverage = CoverageIndex(model, pages, cli.out, warnings.append)
    assert warnings == []

    # A failed topic still gets a page, but the contract only has successful ones.
    assert {topic.file for topic in model.topics} == {
        Path(page.source_path).name
        for page in pages
        if "missing" not in page.source_path
    }
    owner = next(e for e in model.elements if "shop/orders.py" in e.files)
    assert owner.kind == "component"
    orders = next(page for page in pages if page.title == "Orders")
    assert coverage.direct_elements_for(orders) == [owner.id]
    assert [(page.slug, files) for page, files in coverage.topics_for(owner.id)] == [
        (orders.slug, frozenset({"shop/orders.py"})),
        *[
            (page.slug, frozenset({"shop/cli.py"}))
            for page in pages
            if page.title == "Run shop"
        ],
    ]


async def test_failed_cleanup_does_not_fail_a_published_run(cli, capsys):
    cli.out.mkdir()
    # A directory under the old name: removing it raises an OSError on any platform.
    (cli.out / OLD_EVIDENCE).mkdir()
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    assert load_contract_quietly(cli.out).elements
    assert (cli.repo / LOCK_RELATIVE_PATH).exists()
    output = " ".join(capsys.readouterr().out.split())
    assert "[WARN] C4: oude uitvoer niet verwijderd" in output
    assert OLD_EVIDENCE in output


@pytest.mark.parametrize(
    "response", ["accepted", "quote_rejected", "schema_rejected", "unsafe_rejection"]
)
async def test_call_report_names_step_and_reason(cli, capsys, response):
    private_file = "private-context.md"
    private_text = "PRIVATE_PROMPT_CONTENT"
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    capsys.readouterr()
    cli.provider.calls.clear()
    (cli.repo / private_file).write_text(private_text)
    if response == "quote_rejected":
        answer = deepcopy(cli.provider.answers["documented"])
        for item in [*answer["elements"], *answer["relations"]]:
            if "term" in item:
                item["term"] = "PRIVATE_RESPONSE_CONTENT"
            item["citation"]["quote"] = "PRIVATE_RESPONSE_CONTENT"
            # Unchanged README fragments come from the extraction cache; only
            # the newly selected document is sent, so the forgery targets it.
            item["citation"].update(file=private_file, start_line=1, end_line=1)
        cli.provider.answers["documented"] = answer
    elif response == "schema_rejected":
        cli.provider.answers["documented"] = {"PRIVATE_RESPONSE_CONTENT": private_text}
    elif response == "unsafe_rejection":
        cli.provider.answers["documented"] = AnswerRejectedError(
            f"documented: PRIVATE_RESPONSE_CONTENT {private_text} {private_file}"
        )
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    output = capsys.readouterr().out
    report = [line for line in output.splitlines() if "C4 documented:" in line]
    assert set(cli.provider.calls) == {"documented"}
    assert len(report) == 1
    line = report[0]
    assert "documentatieset gewijzigd" in line
    assert "+1/-0/~0" in line
    for secret in (private_file, private_text, "PRIVATE_RESPONSE_CONTENT"):
        assert secret not in line
    if response == "accepted":
        assert cli.provider.calls["documented"] == 1
        assert "1 pogingen" in line
        assert "geaccepteerd" in line
    else:
        assert cli.provider.calls["documented"] == 2
        assert "2 pogingen" in line
        assert line.count("afgekeurd") == 2
        assert "terugval" in line
        rule = {
            "quote_rejected": "no proposed item has a literal quote",
            "schema_rejected": "invalid answer schema",
            "unsafe_rejection": "answer validation",
        }[response]
        assert rule in line


@pytest.mark.parametrize("recover", [True, False])
async def test_call_report_counts_bundled_rounds_and_retry_outcome(
    cli, capsys, recover
):
    valid = cli.provider.answers["classify"]

    def respond(prompt):
        if not recover or cli.provider.calls["classify"] <= 3:
            raise TimeoutError("PRIVATE_PROVIDER_ERROR")
        return valid(prompt)

    cli.provider.answers["classify"] = respond
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("[INFO] C4 ")
        and "C4 documented-bundels:" not in line
        and "C4 documentatierelaties" not in line
    ]
    assert len(lines) == 5
    line = next(line for line in lines if "C4 classify:" in line)
    assert cli.provider.calls["classify"] == 6
    assert "6 pogingen" in line
    assert "nieuwe kandidaten" in line
    assert line.count("tijdelijke fout") == (3 if recover else 6)
    assert ("terugval" in line) is not recover
    assert ("geaccepteerd" in line) is recover
    assert "PRIVATE_PROVIDER_ERROR" not in line


async def test_full_run_writes_contract_and_map_pair(cli):
    """A rerun over old output: contract replaced, old evidence gone, in order."""
    cli.out.mkdir()
    (cli.out / CONTRACT).write_text('{"run": {"schema_version": 3}}\n')
    (cli.out / OLD_EVIDENCE).write_text('{"schema_version": 3}\n')
    published = []
    replace = os.replace

    def record(source, destination):
        replace(source, destination)
        published.append((Path(destination).name, (cli.out / OLD_EVIDENCE).exists()))

    cli.monkeypatch.setattr(os, "replace", record)
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)

    publication = [
        row
        for row in published
        if row[0] in {MAP_EVIDENCE, MAP_MODEL, CONTRACT, LOCK_RELATIVE_PATH.name}
    ]
    assert publication == [
        (MAP_EVIDENCE, True),
        (MAP_MODEL, True),
        (CONTRACT, True),
        (LOCK_RELATIVE_PATH.name, True),
    ]
    assert not (cli.out / OLD_EVIDENCE).exists()
    model, evidence = pair(cli.out)
    assert model.run.kind == "full"
    assert model.run.schema_version == evidence.schema_version == 4
    raw = (cli.out / CONTRACT).read_text(encoding="utf-8")
    contract = json.loads(raw)
    assert contract["schema_version"] == 1
    assert raw == (
        json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    assert load_contract_quietly(cli.out).elements


async def test_interrupted_publication_keeps_older_contract_and_lock(cli):
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    lock_path = cli.repo / LOCK_RELATIVE_PATH
    contract, lock = (cli.out / CONTRACT).read_bytes(), lock_path.read_bytes()
    pair_before = pair(cli.out)[0].run.id
    (cli.out / OLD_EVIDENCE).write_text("{}\n")
    (cli.repo / "shop/added.py").write_text("x = 1\n")
    replace = os.replace

    def interrupt(source, destination):
        if Path(destination).name == CONTRACT:
            raise OSError("interrupted")
        replace(source, destination)

    cli.monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(SystemExit) as exc:
        await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    assert exc.value.code == 1
    assert pair(cli.out)[0].run.id != pair_before
    assert (cli.out / CONTRACT).read_bytes() == contract
    assert lock_path.read_bytes() == lock
    assert (cli.out / OLD_EVIDENCE).exists()


async def test_trial_writes_no_contract_and_keeps_existing(cli):
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    contract = (cli.out / CONTRACT).read_bytes()
    (cli.out / OLD_EVIDENCE).write_text("leftover\n")
    await command.code_mapper_command(
        parse(cli.repo, cli.out, "--plan", "--no-markdown"), cli.config
    )
    assert pair(cli.out)[0].run.kind == "trial"
    assert (cli.out / CONTRACT).read_bytes() == contract
    assert (cli.out / OLD_EVIDENCE).read_text() == "leftover\n"

    fresh = cli.out.parent / "fresh"
    await command.code_mapper_command(
        parse(cli.repo, fresh, "--plan", "--no-markdown"), cli.config
    )
    assert set(snapshot(fresh)) == {MAP_MODEL, MAP_EVIDENCE}


@pytest.mark.parametrize(
    ("flags", "fallback"),
    [((), True), (("--no-markdown",), False)],
    ids=["fallback", "no-markdown"],
)
async def test_fallback_and_no_markdown_write_loadable_contract(cli, flags, fallback):
    if fallback:
        cli.provider.answers["merge"] = TimeoutError("temporarily unavailable")
        cli.provider.answers["documented"] = TimeoutError("temporarily unavailable")
    await command.code_mapper_command(parse(cli.repo, cli.out, *flags), cli.config)
    assert (pair(cli.out)[0].run.fallback_count > 0) is fallback
    loaded = load_contract_quietly(cli.out)
    assert loaded.elements
    raw = (cli.out / CONTRACT).read_text(encoding="utf-8")
    assert "fallback" not in raw
    assert "markers" not in raw
    assert (cli.out / "__code_mapper_index.md").exists() == (not flags)


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
    assert set(snapshot(cli.out)) == {CONTRACT, MAP_MODEL, MAP_EVIDENCE}
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


async def test_old_lock_stops_with_a_clear_message(cli, capsys):
    lock = cli.repo / LOCK_RELATIVE_PATH
    lock.parent.mkdir(exist_ok=True)
    old = '{"version": 3, "scopes": {}}'
    lock.write_text(old)
    cli.monkeypatch.setattr(command, "_create_code_mapper_llm_manager", forbidden)
    with pytest.raises(SystemExit) as exc:
        await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    assert exc.value.code == 1
    assert lock.read_text() == old
    assert not cli.seen
    captured = capsys.readouterr()
    message = " ".join((captured.out + captured.err).split())
    assert "map.lock.json" in message
    assert "older version" in message


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
    assert set(snapshot(cli.out)) == {MAP_MODEL, MAP_EVIDENCE}


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


async def test_failed_merge_warns(cli, capsys):
    cli.provider.answers["merge"] = TimeoutError("temporarily unavailable")
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    model, _ = pair(cli.out)
    count = model.run.fallback_count
    assert not [e for e in model.elements if e.kind == "component"]
    assert count == len(
        [e for e in model.elements if e.kind == "container" and "fallback" in e.markers]
    )
    assert count > 0
    assert (
        f"C4: {count} elementen via terugval (niet opgeslagen)"
        in capsys.readouterr().out
    )
    document = json.loads((cli.repo / LOCK_RELATIVE_PATH).read_text())
    assert document["scopes"]["/"]["components"] == {}
    assert document["scopes"]["/"]["containers"]


async def test_failed_documentation_fragment_warns_the_user(cli, capsys):
    cli.provider.answers["documented"] = TimeoutError("temporarily unavailable")
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    model, _ = pair(cli.out)
    count = model.run.fallback_fragments
    assert count > 0
    assert f"C4: {count} documentatiefragmenten niet onderzocht" in (
        capsys.readouterr().out
    )


async def test_resume_after_fatal_error_publishes_nothing(cli, scripted):
    """Bundles validated before a fatal error survive; nothing is published."""
    from chunkhound.code_mapper.c4.documented import EXTRACTION_CACHE
    from chunkhound.llm_manager import LLMManager
    from tests.code_mapper.c4.conftest import component_answer, write_sections

    cli.monkeypatch.setattr(
        LLMManager, "_create_provider", lambda self, config: scripted
    )
    config = {"provider": "fake", "model": "fake-gpt", "max_input_chars": 16_000}
    limited = LLMManager(utility_config=config, synthesis_config=config)
    cli.monkeypatch.setattr(
        command, "_create_code_mapper_llm_manager", lambda *a: limited
    )
    write_sections(cli.repo / "docs/arch.md")
    cli.result.poi_sections_indexed[0][2]["metadata"]["sources"]["files"].append(
        "docs/arch.md"
    )

    def fatal_on_second(prompt):
        if scripted.calls["documented"] == 2:
            raise ValueError("invalid credentials")
        return component_answer(prompt)

    scripted.answers["documented"] = fatal_on_second
    with pytest.raises(SystemExit) as exc:
        await command.code_mapper_command(
            parse(cli.repo, cli.out, "--jobs", "1"), cli.config
        )
    assert exc.value.code == 1
    assert not cli.out.exists() or not list(cli.out.iterdir())
    assert not (cli.repo / LOCK_RELATIVE_PATH).exists()
    cache = cli.repo / EXTRACTION_CACHE / "documented"
    assert len(list(cache.glob("*.json"))) == 1

    scripted.calls.clear()
    scripted.answers["documented"] = component_answer
    await command.code_mapper_command(
        parse(cli.repo, cli.out, "--jobs", "1"), cli.config
    )
    resumed_calls = scripted.calls["documented"]
    assert resumed_calls >= 1
    # Every bundle is stored once: the one from before the failure is reused.
    assert len(list(cache.glob("*.json"))) == resumed_calls + 1
    assert (cli.repo / LOCK_RELATIVE_PATH).exists()


async def test_cli_reports_documented_bundles(cli, capsys):
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    output = capsys.readouterr().out
    assert (
        "C4 documented-bundels: 0 hergebruikt, 1 nieuw, 0 gesplitst, "
        "0 teruggevallen; fragmenten 1 gedekt, 0 teruggevallen"
    ) in output
    relations = [
        line for line in output.splitlines() if "C4 documentatierelaties" in line
    ]
    assert len(relations) == 1
    assert "geen treffer" in relations[0]
    assert "meerdere treffers" in relations[0]
    assert "niet toegestaan" in relations[0]
    assert len([line for line in output.splitlines() if "C4 documented:" in line]) == 1


def write_files(repo, files, content="# content\n"):
    for file in files:
        path = repo / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def modeled_files(out, label="_"):
    model, evidence = load_c4_pair(
        out / f"{label}_c4_map_model.json", out / f"{label}_c4_map_evidence.json"
    )
    return {file for files in evidence.element_files.values() for file in files}, {
        element.name for element in model.elements
    }


def record_documented(cli):
    """Collect the documents that reach the provider."""
    seen = set()
    answer = cli.provider.answers["documented"]

    def respond(prompt):
        seen.update(path for path, _ in documented_fragments(prompt).values())
        return documented_per_fragment(prompt, answer)

    cli.provider.answers["documented"] = respond
    return seen


TEST_MANIFEST = "tests/e2e/package.json"
TEST_CODE = (
    "tests/test_orders.py",
    "shop/test/helper.py",
    "web/src/__tests__/checkout.ts",
    "shop/fixtures/orders.py",
    "web/src/__fixtures__/cart.ts",
    "shop/testdata/rows.py",
    "shop/test_cart.py",
    "shop/cart_test.py",
    "web/src/cart.test.ts",
    "web/src/cart.spec.ts",
    "shop/conftest.py",
)


async def test_test_code_is_not_a_c4_source(cli):
    write_files(cli.repo, TEST_CODE)
    (cli.repo / TEST_MANIFEST).parent.mkdir(parents=True)
    (cli.repo / TEST_MANIFEST).write_text(
        json.dumps({"name": "e2e-app", "bin": {"e2e-app": "index.js"}})
    )
    await command.code_mapper_command(parse(cli.repo, cli.out), cli.config)
    files, names = modeled_files(cli.out)
    assert not files & {*TEST_CODE, TEST_MANIFEST}
    assert "shop/orders.py" in files
    assert "e2e-app" not in names

    config = cli.config.model_copy(update={"c4": C4Config(exclude_test_code=False)})
    restored = cli.out.parent / "with-tests"
    await command.code_mapper_command(parse(cli.repo, restored), config)
    files, names = modeled_files(restored)
    assert set(TEST_CODE) <= files
    assert "e2e-app" in names


async def test_c4_exclude_applies_to_code_and_documentation(cli):
    excluded_doc = "docs/melly/deep/plan.md"
    write_files(cli.repo, ["docs/guide.md", "docs/melly/plan.md", excluded_doc])
    (cli.repo / ".chunkhound.json").write_text(
        json.dumps({"c4": {"exclude": ["docs/melly/**", "shop/payments.py"]}})
    )
    config = Config(
        target_dir=cli.repo,
        embedding={"provider": "openai", "api_key": "test"},
        llm={"provider": "openai", "api_key": "test"},
    )
    cli.result.poi_sections_indexed[0][2]["metadata"]["sources"]["files"] += [
        "docs/guide.md",
        "docs/melly/plan.md",
        excluded_doc,
    ]
    documents = record_documented(cli)
    await command.code_mapper_command(parse(cli.repo, cli.out), config)
    files, _ = modeled_files(cli.out)
    assert not files & {"docs/melly/plan.md", excluded_doc, "shop/payments.py"}
    assert {"docs/guide.md", "shop/orders.py"} <= files
    assert documents == {"README.md", "docs/guide.md"}


async def test_scope_inside_tests_keeps_its_files(cli):
    write_files(
        cli.repo,
        [
            "tests/e2e/app.py",
            "tests/e2e/README.md",
            "tests/e2e/test_app.py",
            "tests/e2e/fixtures/data.py",
            "tests/e2e/fixtures/guide.md",
        ],
    )
    documents = record_documented(cli)
    await command.code_mapper_command(
        parse(cli.repo / "tests/e2e", cli.out), cli.config
    )
    files, _ = modeled_files(cli.out, "tests_e2e")
    assert {"tests/e2e/app.py", "tests/e2e/README.md"} <= files
    assert not files & {"tests/e2e/test_app.py", "tests/e2e/fixtures/data.py"}
    assert documents == {"tests/e2e/README.md"}


@pytest.mark.parametrize(
    ("scope", "label"), [("", "_"), ("web/src", "web_src")], ids=["root", "nested"]
)
async def test_map_does_not_read_its_own_output(cli, scope, label):
    out = cli.repo / scope / "generated"
    own = [
        f"{label}_code_mapper_index.md",
        f"hyde_plan_arch_{label}.md",
        f"hyde_scope_prompt_ops_{label}.md",
    ]
    relative = Path(scope) / "generated"
    write_files(
        cli.repo,
        [(relative / name).as_posix() for name in own]
        + [(relative / "notes.md").as_posix()]
        + [(relative / "deep" / own[0]).as_posix()],
    )
    # Once earlier output is indexed, a topic can cite it as documentation too.
    documents = record_documented(cli)
    cli.result.poi_sections_indexed[0][2]["metadata"]["sources"]["files"] += [
        (relative / "notes.md").as_posix(),
        *((relative / name).as_posix() for name in own),
    ]
    await command.code_mapper_command(parse(cli.repo / scope, out), cli.config)
    files, _ = modeled_files(out, label)
    assert not files & {(relative / name).as_posix() for name in own}
    assert {
        (relative / "notes.md").as_posix(),
        (relative / "deep" / own[0]).as_posix(),
    } <= files
    assert (relative / "notes.md").as_posix() in documents
    assert not documents & {(relative / name).as_posix() for name in own}


def test_hyde_still_sees_excluded_files(cli):
    write_files(cli.repo, ["tests/test_orders.py", "shop/skip.py"])
    config = cli.config.model_copy(update={"c4": C4Config(exclude=["shop/skip.py"])})
    selection = select_scope_files(
        scope_path=cli.repo, project_root=cli.repo, config=config
    )
    assert not {"tests/test_orders.py", "shop/skip.py"} & set(selection.files)
    assert selection.excluded_as_test_code == 1
    assert selection.excluded_by_pattern == 1
    assert {"tests/test_orders.py", "shop/skip.py"} <= set(
        collect_scope_files(
            scope_path=cli.repo,
            project_root=cli.repo,
            hyde_cfg=HydeConfig(
                max_scope_files=0,
                max_snippet_files=0,
                max_snippet_chars=0,
                max_completion_tokens=1,
                max_snippet_tokens=1,
            ),
        )
    )
