"""Contracts for opt-in, local-only decision logging."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from loguru import logger
from pydantic import ValidationError

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
    blocker = tmp_path / ".chunkhound" / "not-a-directory"
    blocker.parent.mkdir()
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


@pytest.mark.parametrize("absolute", [False, True])
def test_custom_log_inside_chunkhound_rotates_one_generation(tmp_path, absolute):
    path = tmp_path / ".chunkhound" / "logs" / "d.jsonl"
    enable(
        tmp_path,
        path=path if absolute else path.relative_to(tmp_path),
        max_size_mb=1,
    )
    assert decision_log.is_enabled()
    assert not path.parent.exists()
    backup = path.with_name(path.name + ".1")
    payload = {"query": "x" * (1024 * 1024)}
    decision_log.record("first", payload)
    assert path.stat().st_size > 1024 * 1024
    decision_log.record("second", payload)
    assert json.loads(backup.read_text())["event"] == "first"
    assert json.loads(path.read_text())["event"] == "second"
    decision_log.record("third", {})
    assert json.loads(backup.read_text())["event"] == "second"
    assert json.loads(path.read_text())["event"] == "third"
    assert sorted(p.name for p in path.parent.iterdir()) == ["d.jsonl", "d.jsonl.1"]


@pytest.mark.parametrize("value", [0, 0.5, -1, float("nan"), float("inf")])
def test_max_size_requires_at_least_one_finite_mib(value):
    with pytest.raises(ValidationError):
        DecisionLogConfig(max_size_mb=value)


@pytest.mark.parametrize("layer", ["local_config", "global", "env"])
@pytest.mark.parametrize(
    "path_kind", ["home", "absolute", "parent", "source", "traversal", "prefix"]
)
@pytest.mark.parametrize("target_exists", [False, True])
def test_unsafe_log_path_stays_disabled_without_touching_target(
    tmp_path, monkeypatch, layer, path_kind, target_exists
):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    configured_path, target = {
        "home": ("~/.bashrc", home / ".bashrc"),
        "absolute": (str(tmp_path / "outside"), tmp_path / "outside"),
        "parent": ("../x", tmp_path / "x"),
        "source": ("src/main.py", project / "src" / "main.py"),
        "traversal": (".chunkhound/../src/main.py", project / "src" / "main.py"),
        "prefix": (
            ".chunkhound-other/log.jsonl",
            project / ".chunkhound-other/log.jsonl",
        ),
    }[path_kind]
    original = b"# operator content\n" * (64 * 1024)
    if target_exists:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original)
    settings = {"enabled": True, "path": configured_path, "max_size_mb": 1}
    if layer == "env":
        for key, value in settings.items():
            monkeypatch.setenv(f"CHUNKHOUND_DECISION_LOG__{key.upper()}", str(value))
    else:
        config_file = (
            project / ".chunkhound.json"
            if layer == "local_config"
            else home / ".chunkhound.json"
        )
        config_file.write_text(json.dumps({"decision_log": settings}))
        if layer == "global":
            monkeypatch.setenv("CHUNKHOUND_GLOBAL_CONFIG_FILE", str(config_file))
    config = Config(
        target_dir=project,
        skip_layers={"global", "local_config", "env", "config_file", "cli"} - {layer},
    )
    # Refusing a new configuration must also disable a previously active log.
    enable(project)
    messages = []
    handler = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        decision_log.configure(config, project)
        decision_log.record("search", {"query": "first"})
        decision_log.record("search", {"query": "second"})
    finally:
        logger.remove(handler)
    assert not decision_log.is_enabled()
    assert len(messages) == 1
    assert "outside" in messages[0] and ".chunkhound" in messages[0]
    assert target.exists() == target_exists
    if target_exists:
        assert target.read_bytes() == original
    assert not target.with_name(target.name + ".1").exists()
    assert not (project / ".chunkhound").exists()


@pytest.mark.parametrize("symlink_kind", ["file", "directory"])
def test_symlink_escape_disables_log_without_touching_target(tmp_path, symlink_kind):
    log_dir = tmp_path / ".chunkhound"
    log_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "victim"
    original = b"x" * (1024 * 1024 + 1)
    target.write_bytes(original)
    link = log_dir / "link"
    try:
        link.symlink_to(
            target if symlink_kind == "file" else outside,
            target_is_directory=symlink_kind == "directory",
        )
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    path = link if symlink_kind == "file" else link / "victim"
    messages = []
    handler = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        enable(tmp_path, path=path, max_size_mb=1)
        decision_log.record("first", {})
        decision_log.record("second", {})
    finally:
        logger.remove(handler)
    assert not decision_log.is_enabled()
    assert len(messages) == 1
    assert "outside" in messages[0]
    assert target.read_bytes() == original
    assert not target.with_name(target.name + ".1").exists()
    assert not (log_dir / "decisions.jsonl").exists()


def test_log_directory_itself_is_resolved_for_containment(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    try:
        (project / ".chunkhound").symlink_to(storage, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    enable(project, path=".chunkhound/logs/../custom.jsonl")
    assert decision_log.is_enabled()
    decision_log.record("search", {})
    assert json.loads((storage / "custom.jsonl").read_text())["event"] == "search"


def test_environment_enables_log_through_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CHUNKHOUND_DECISION_LOG__ENABLED", "true")
    monkeypatch.setenv("CHUNKHOUND_DECISION_LOG__PATH", ".chunkhound/logs/custom.jsonl")
    monkeypatch.setenv("CHUNKHOUND_DECISION_LOG__MAX_SIZE_MB", "2")
    config = Config(
        target_dir=tmp_path,
        skip_layers={"global", "local_config", "config_file", "cli"},
    )
    assert config.decision_log.enabled
    assert config.decision_log.max_size_mb == 2
    decision_log.configure(config, tmp_path)
    decision_log.record("env", {})
    path = tmp_path / ".chunkhound/logs/custom.jsonl"
    assert json.loads(path.read_text())["event"] == "env"


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
