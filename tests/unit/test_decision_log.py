"""Contracts for opt-in, local-only decision logging."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from chunkhound.core import decision_log
from chunkhound.core.config.config import Config
from chunkhound.core.config.decision_log_config import DecisionLogConfig
from chunkhound.version import __version__


@pytest.fixture(autouse=True)
def reset_decision_log(tmp_path):
    decision_log.configure(None, tmp_path)
    yield
    decision_log.configure(None, tmp_path)


def enable(tmp_path, **kwargs):
    decision_log.configure(
        SimpleNamespace(decision_log=DecisionLogConfig(enabled=True, **kwargs)),
        tmp_path,
    )
    return tmp_path / ".chunkhound" / "decisions.jsonl"


@pytest.mark.parametrize(
    "config",
    [None, SimpleNamespace(), SimpleNamespace(decision_log=DecisionLogConfig())],
)
def test_disabled_log_creates_nothing(tmp_path, config):
    enable(tmp_path)
    decision_log.configure(config, tmp_path)
    assert not decision_log.is_enabled()
    decision_log.record("search", {"query": "raw query"})
    assert list(tmp_path.iterdir()) == []


def test_records_are_jsonl_with_common_fields_and_raw_payload(tmp_path):
    path = enable(tmp_path)
    assert decision_log.is_enabled()
    assert not path.parent.exists()
    decision_log.record(
        "search", {"query": "waarom?\nvolgende regel", "path": Path("example")}
    )
    decision_log.record("search", {"schema_version": 999, "event": "spoofed"})
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 2
    assert records[0]["query"] == "waarom?\nvolgende regel"
    assert records[0]["path"] == "example"
    for item in records:
        assert item["schema_version"] == 1
        assert item["event"] == "search"
        assert item["trace_id"]
        assert item["parent_trace_id"] is None
        assert item["chunkhound_version"] == __version__
        assert datetime.fromisoformat(item["ts"]).tzinfo == timezone.utc
    assert records[0]["trace_id"] != records[1]["trace_id"]


def test_nested_traces_link_and_restore_even_after_exception(tmp_path):
    path = enable(tmp_path)
    with decision_log.trace() as outer:
        decision_log.record("outer", {})
        with pytest.raises(ValueError, match="caller failure"):
            with decision_log.trace() as inner:
                decision_log.record("inner", {})
                raise ValueError("caller failure")
        decision_log.record("outer_again", {})
    decision_log.record("outside", {})
    first, nested, restored, outside = map(json.loads, path.read_text().splitlines())
    assert first["trace_id"] == restored["trace_id"] == outer
    assert first["parent_trace_id"] is None
    assert nested["trace_id"] == inner != outer
    assert nested["parent_trace_id"] == outer
    assert outside["trace_id"] not in (outer, inner)
    assert outside["parent_trace_id"] is None


def test_concurrent_tasks_inherit_parent_without_leaking_traces(tmp_path):
    path = enable(tmp_path)

    async def child():
        with decision_log.trace():
            await asyncio.sleep(0)
            decision_log.record("child", {})

    async def run():
        with decision_log.trace() as parent:
            await asyncio.gather(child(), child())
            decision_log.record("parent", {})
            return parent

    parent = asyncio.run(run())
    first, second, last = map(json.loads, path.read_text().splitlines())
    assert first["parent_trace_id"] == second["parent_trace_id"] == parent
    assert first["trace_id"] != second["trace_id"]
    assert last["trace_id"] == parent
    assert last["parent_trace_id"] is None


def test_unwritable_path_does_not_fail_or_print(tmp_path, capsys):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file")
    enable(tmp_path, path=blocker / "decisions.jsonl")
    decision_log.record("search", {})
    assert blocker.read_text() == "file"
    assert capsys.readouterr().out == ""


def test_serialization_failure_does_not_break_later_records(tmp_path):
    path = enable(tmp_path)
    circular = {}
    circular["self"] = circular
    decision_log.record("invalid", circular)
    decision_log.record("valid", {})
    assert [json.loads(line)["event"] for line in path.read_text().splitlines()] == [
        "valid"
    ]


def test_rotation_keeps_one_generation_and_continues_writing(tmp_path):
    path = enable(tmp_path, max_size_mb=0.000001)
    backup = path.with_name(path.name + ".1")
    decision_log.record("first", {})
    assert path.stat().st_size > 0.000001 * 1024 * 1024
    decision_log.record("second", {})
    assert json.loads(backup.read_text())["event"] == "first"
    assert json.loads(path.read_text())["event"] == "second"
    decision_log.record("third", {})
    assert json.loads(backup.read_text())["event"] == "second"
    assert json.loads(path.read_text())["event"] == "third"
    assert sorted(p.name for p in path.parent.iterdir()) == [
        "decisions.jsonl",
        "decisions.jsonl.1",
    ]


def test_environment_enables_log_through_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CHUNKHOUND_DECISION_LOG__ENABLED", "true")
    monkeypatch.setenv("CHUNKHOUND_DECISION_LOG__PATH", "logs/custom.jsonl")
    monkeypatch.setenv("CHUNKHOUND_DECISION_LOG__MAX_SIZE_MB", "2")
    config = Config(
        target_dir=tmp_path,
        skip_layers={"global", "local_config", "config_file", "cli"},
    )
    assert config.decision_log.enabled
    assert config.decision_log.max_size_mb == 2
    decision_log.configure(config, tmp_path)
    decision_log.record("env", {})
    assert json.loads((tmp_path / "logs/custom.jsonl").read_text())["event"] == "env"


def test_file_config_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CHUNKHOUND_DECISION_LOG__ENABLED", "true")
    (tmp_path / ".chunkhound.json").write_text(
        json.dumps({"decision_log": {"enabled": False, "max_size_mb": 3}})
    )
    config = Config(target_dir=tmp_path, skip_layers={"global", "config_file", "cli"})
    assert not config.decision_log.enabled
    assert config.decision_log.max_size_mb == 3
    decision_log.configure(config, tmp_path)
    decision_log.record("disabled", {})
    assert not (tmp_path / ".chunkhound").exists()
