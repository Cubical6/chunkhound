"""CLI and MCP acceptance contracts for human domain input."""

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from chunkhound.core.config.config import Config
from chunkhound.database_factory import create_services
from chunkhound.mcp_server.common import handle_tool_call, tool_call_failed

ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = [{"op": "put", "element": {"kind": "concept", "term": "skill"}}]


@pytest.fixture(autouse=True)
def isolated_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    subprocess.run(
        ["git", "config", "--global", "user.name", "A. Developer"], check=True
    )
    subprocess.run(
        ["git", "config", "--global", "user.email", "dev@example.com"], check=True
    )


def cli(
    project: Path, *args: str, request: Any = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--no-sync", "chunkhound", "domain", str(project), *args],
        cwd=ROOT,
        input=json.dumps(request) if request is not None else None,
        text=True,
        capture_output=True,
        timeout=60,
    )


def test_cli_domain_write_and_list_round_trip(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    schema = cli(project, "--schema")
    assert schema.returncode == 0, schema.stderr
    assert "operations" in json.loads(schema.stdout)["properties"]
    empty = cli(project, "--list-input")
    assert empty.returncode == 0, empty.stderr
    assert json.loads(empty.stdout)["judgements"] == []
    assert json.loads(empty.stdout)["model"]["concepts"] == []
    assert not (project / ".chunkhound").exists()
    invalid_utf8 = project / "invalid-utf8.json"
    invalid_utf8.write_bytes(b"\xff")
    invalid_json = project / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    for source in (project / "missing.json", project, invalid_utf8, invalid_json):
        bad_input = cli(project, "--write", str(source))
        assert bad_input.returncode == 1, bad_input.stderr
        error = json.loads(bad_input.stdout)["error"]
        assert error["type"] == "DomainInputRejected"
        assert len(error["issues"]) == 1
        assert error["issues"][0]["path"] == ""
        assert error["issues"][0]["code"] == "invalid_json"
        assert not (project / ".chunkhound").exists()
    for mode in ((), ("--list-input",), ("--schema",)):
        invalid_dry_run = cli(project, "--dry-run", *mode)
        assert invalid_dry_run.returncode == 2
        assert "--dry-run requires --write" in invalid_dry_run.stderr
        assert not (project / ".chunkhound").exists()
    written = cli(project, "--write", "-", request={"operations": OPERATIONS})
    assert written.returncode == 0, written.stderr
    assert json.loads(written.stdout)["records"] == [1]
    view = cli(project, "--list-input")
    assert json.loads(view.stdout)["model"]["concepts"][0]["id"] == "concept:root/skill"
    rejected = cli(project, "--write", "-", request={"operations": []})
    assert rejected.returncode == 1, rejected.stderr
    assert json.loads(rejected.stdout)["error"]["issues"]
    assert cli(project, "--list-input").stdout == view.stdout
    dry = cli(project, "--write", "-", "--dry-run", request={"operations": OPERATIONS})
    assert dry.returncode == 0, dry.stderr
    assert json.loads(dry.stdout)["dry_run"] is True
    assert json.loads(dry.stdout)["records"] == []
    db = project / ".chunkhound" / "db" / "chunks.db"
    lock = subprocess.Popen(
        [
            "uv",
            "run",
            "--no-sync",
            "python",
            "-c",
            "import duckdb, sys; c=duckdb.connect(sys.argv[1]); "
            "sys.stdout.write('ready\\n'); sys.stdout.flush(); sys.stdin.read()",
            str(db),
        ],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert lock.stdout is not None
        assert lock.stdout.readline().strip() == "ready"
        locked = cli(project, "--write", "-", request={"operations": OPERATIONS})
        assert locked.returncode == 2, locked.stderr
        assert "domain_write" in locked.stderr
        assert "domain_read" in locked.stderr
    finally:
        lock.communicate(input="", timeout=20)


async def call(name: str, arguments: dict[str, Any], services: Any, config: Config):
    ready = asyncio.Event()
    ready.set()
    return await handle_tool_call(name, arguments, services, None, ready, config=config)


@pytest.mark.asyncio
async def test_mcp_domain_write_reports_issues_as_tool_error(tmp_path: Path) -> None:
    config = Config(target_dir=tmp_path)
    services = create_services(config.database.get_db_path(), config)
    services.provider.connect()
    try:
        content = await call("domain_write", {"operations": []}, services, config)
        assert tool_call_failed(content)  # Transport uses this to set isError.
        error = json.loads(content[0].text)["error"]
        assert error["type"] == "DomainInputRejected"
        assert error["issues"][0]["path"] == "operations"
        assert error["issues"][0]["code"]
        config.database.read_only = True
        content = await call(
            "domain_write", {"operations": OPERATIONS}, services, config
        )
        assert tool_call_failed(content)
        error = json.loads(content[0].text)["error"]
        assert error["type"] == "DomainInputUnavailable"
        assert error["issues"][0]["code"] == "backend_not_supported"
        assert "read-only" in error["issues"][0]["message"]
        view = await call("domain_read", {}, services, config)
        assert json.loads(view[0].text)["model"]["concepts"] == []
        assert (
            services.provider.execute_query(
                "SELECT table_name FROM duckdb_tables() "
                "WHERE starts_with(table_name, 'domain_')"
            )
            == []
        )
    finally:
        services.provider.disconnect()


@pytest.mark.asyncio
async def test_mcp_domain_read_returns_human_input(tmp_path: Path) -> None:
    config = Config(target_dir=tmp_path)
    services = create_services(config.database.get_db_path(), config)
    services.provider.connect()
    try:
        content = await call("domain_read", {}, services, config)
        assert not tool_call_failed(content)
        assert json.loads(content[0].text)["model"]["concepts"] == []
        assert json.loads(content[0].text)["judgements"] == []
        assert (
            services.provider.execute_query(
                "SELECT table_name FROM duckdb_tables() "
                "WHERE starts_with(table_name, 'domain_')"
            )
            == []
        )
        written = await call(
            "domain_write", {"operations": OPERATIONS}, services, config
        )
        assert not tool_call_failed(written)
        config.database.read_only = True
        content = await call("domain_read", {}, services, config)
        assert not tool_call_failed(content)
        assert (
            json.loads(content[0].text)["model"]["concepts"][0]["human_sources"][0][
                "entry_point"
            ]
            == "mcp"
        )
    finally:
        services.provider.disconnect()
    listed = cli(tmp_path, "--list-input")
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.rstrip("\n") == content[0].text
