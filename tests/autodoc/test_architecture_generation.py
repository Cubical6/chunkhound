"""Generation owns only map outputs attested by its prior publication data."""

import json
import os
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from chunkhound.autodoc.generator import generate_docsite
from chunkhound.autodoc.models import CleanupConfig
from chunkhound.llm_manager import LLMManager
from tests.fixtures.openai_compatible_server import (
    ChatCompletionScript,
    OpenAICompatibleTestServer,
)


async def _recorded_llm_reply(client, request: httpx.Request, **kwargs):
    assert request.url.host == "task5-llm.invalid"
    payload = json.loads(request.content)
    if payload.get("response_format"):
        content = json.dumps({"nav": {"groups": []}, "glossary": []})
    elif any(message["role"] == "system" for message in payload["messages"]):
        content = "## Overview\nRecorded external cleanup response."
    else:
        content = "Documentation for the application and its request API."
    return httpx.Response(
        200,
        request=request,
        json={
            "id": "task5-recorded",
            "object": "chat.completion",
            "created": 0,
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 32,
                "completion_tokens": 16,
                "total_tokens": 48,
            },
        },
    )


def write_input(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "chosen_code_mapper_index.md").write_text(
        "# AutoDoc Topics (/fixture)\n\n1. [Final Topic](original.md)\n"
    )
    (root / "original.md").write_text("# Original title\n\nReadable topic.\n")
    payload = {
        "schema_version": 1,
        "system": {"id": "system", "name": "Fixture System", "description": "Root"},
        "repositories": [
            {
                "id": "repo",
                "path": ".",
                "remote_url": "https://github.com/org/repo.git",
                "commit": "a" * 40,
            }
        ],
        "sources": [
            {
                "id": "code",
                "repository": "repo",
                "path": "app.py",
                "kind": "code",
                "start_line": 2,
                "end_line": 8,
            }
        ],
        "elements": [
            {
                "id": "app",
                "parent": "system",
                "kind": "container",
                "name": "Application",
                "description": "Runs requests",
                "technology": "Python",
                "status": "aangetroffen",
                "files": ["shared.py"],
                "sources": ["code"],
            },
            {
                "id": "api",
                "parent": "app",
                "kind": "component",
                "name": "Request API",
                "description": "Serves requests",
                "technology": "Python",
                "status": "aangetroffen",
                "files": ["app.py"],
                "sources": ["code"],
            },
        ],
        "relations": [
            {
                "id": "call",
                "source": "app",
                "target": "api",
                "title": "Dispatches requests",
                "technology": "",
                "status": "aangetroffen",
                "sources": ["code"],
            }
        ],
        "merged_labels": [],
        "topics": [
            {
                "file": "original.md",
                "covers": [
                    {"element": "app", "files": ["shared.py"]},
                    {"element": "api", "files": ["app.py"]},
                ],
            }
        ],
    }
    model_path = root / "chosen_c4_model.json"
    model_path.write_text(json.dumps(payload))
    return model_path


async def generate(root: Path, output: Path, warnings: list[str]):
    config = {
        "provider": "openai",
        "model": "task5-recorded-cleanup",
        "api_key": "task5-fixture-only",
        "base_url": "https://task5-llm.invalid/v1",
        "max_retries": 0,
    }
    manager = LLMManager(utility_config=config, synthesis_config=config)
    with patch.object(httpx.AsyncClient, "send", _recorded_llm_reply):
        return await generate_docsite(
            input_dir=root,
            output_dir=output,
            llm_manager=manager,
            cleanup_config=CleanupConfig("llm", 1, 512),
            site_title=None,
            site_tagline=None,
            allow_delete_topics_dir=True,
            log_warning=warnings.append,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, True])
async def test_full_generation_removes_only_owned_architecture_outputs(
    tmp_path: Path, invalid: bool
):
    root, output = tmp_path / "input", tmp_path / "site"
    model_path = write_input(root)
    warnings: list[str] = []
    result = await generate(root, output, warnings)
    data_path = output / "src/data/architecture.json"
    data = json.loads(data_path.read_text())
    slug = result.pages[0].slug
    assert data["topics"][slug]["directElementIds"] == ["api", "app"]
    records = json.loads((output / "src/data/search.json").read_text())
    assert {record["title"] for record in records} == {
        result.pages[0].title,
        "Application",
        "Request API",
    }
    assert all(
        record["url"].startswith("/architecture/?view=focus_")
        for record in records
        if record["title"] != result.pages[0].title
    )
    user_file = output / "likec4/user.txt"
    user_file.write_text("user-owned")
    if invalid:
        model_path.write_text("{invalid")
    else:
        model_path.unlink()
    await generate(root, output, warnings)
    assert json.loads(data_path.read_text()) == {
        "schemaVersion": 1,
        "enabled": False,
        "contextView": "index",
        "views": {},
        "elements": {},
        "topics": {},
    }
    assert user_file.read_text() == "user-owned"
    for path in (
        "likec4/model.c4",
        "likec4/views.c4",
        "likec4/specification.c4",
        "src/pages/architecture/index.astro",
        "src/components/ArchitectureMap.astro",
        "src/components/ArchitectureMap.tsx",
        "src/components/ArchitectureMiniMap.astro",
        "src/components/ArchitectureMiniMap.tsx",
        "vendor/likec4/likec4-1.60.0-chunkhound.1.tgz",
    ):
        assert not (output / path).exists(), path
    assert (
        json.loads((output / "src/data/search.json").read_text())[0]["url"]
        == f"/topics/{slug}/"
    )
    assert len(json.loads((output / "src/data/search.json").read_text())) == 1
    assert (output / f"src/pages/topics/{slug}.md").exists()
    assert any("C4 model" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_no_model_preserves_unowned_paths_and_disables_map_imports(
    tmp_path: Path,
):
    root, output = tmp_path / "input", tmp_path / "site"
    write_input(root).unlink()
    originals = {
        "likec4/model.c4": "// user model\n",
        "src/components/ArchitectureMap.tsx": "export const user = true;\n",
        "src/pages/architecture/index.astro": "<p>User architecture notes</p>\n",
    }
    for relative, content in originals.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for _ in range(2):
        await generate(root, output, [])
        assert (
            json.loads((output / "src/data/architecture.json").read_text())["enabled"]
            is False
        )
        for relative, content in originals.items():
            assert (output / relative).read_text() == content
        dependencies = json.loads((output / "package.json").read_text())["dependencies"]
        assert (
            not {"react", "react-dom", "likec4", "@astrojs/react"} & dependencies.keys()
        )


def test_missing_model_is_warning_not_cli_failure(tmp_path: Path) -> None:
    root, output = tmp_path / "input", tmp_path / "site"
    model_path = write_input(root)
    model_path.unlink()
    cleanup_response = (
        "## Overview\n\nRecorded full CLI cleanup reached ordinary documentation.\n"
    )
    assert cleanup_response.strip() not in (root / "original.md").read_text()
    scripts = [
        ChatCompletionScript(
            name="information-architecture",
            content=json.dumps({"nav": {"groups": []}, "glossary": []}),
            predicate=lambda body, _: bool(body.get("response_format")),
        ),
        ChatCompletionScript(
            name="cleanup",
            content=cleanup_response,
            predicate=lambda body, _: any(
                message["role"] == "system" for message in body["messages"]
            ),
        ),
        ChatCompletionScript(
            name="homepage",
            content="Ordinary application documentation.",
            predicate=lambda body, _: not any(
                message["role"] == "system" for message in body["messages"]
            ),
        ),
    ]
    home = tmp_path / "home"
    home.mkdir()
    # Isolate all config layers and provider/proxy variables from the subprocess.
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "WINDIR"}
    }
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        TMPDIR=str(tmp_path),
        TMP=str(tmp_path),
        TEMP=str(tmp_path),
        CHUNKHOUND_NO_RICH="1",
    )
    with OpenAICompatibleTestServer(scripts) as server:
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "llm": {
                        "provider": "openai",
                        "model": "task5-recorded-cleanup",
                        "api_key": "task5-fixture-only",
                        "base_url": server.base_url,
                        "max_retries": 0,
                    }
                }
            )
        )
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(Path(__file__).resolve().parents[2]),
                "--no-sync",
                "chunkhound",
                "autodoc",
                str(root),
                "--out-dir",
                str(output),
                "--config",
                str(config_path),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
    diagnostic = completed.stdout + completed.stderr
    assert completed.returncode == 0, diagnostic
    warning = diagnostic.lower()
    assert model_path.name in warning
    assert any(
        cause in warning for cause in ("no such file", "cannot find", "not found")
    )
    assert re.search(r"\bregenerat\w*\b", warning) and re.search(r"\bmap\b", warning)
    assert json.loads((output / "src/data/architecture.json").read_text()) == {
        "schemaVersion": 1,
        "enabled": False,
        "contextView": "index",
        "views": {},
        "elements": {},
        "topics": {},
    }
    records = json.loads((output / "src/data/search.json").read_text())
    assert len(records) == 1
    topic = output / "src/pages/topics" / f"{records[0]['slug']}.md"
    assert cleanup_response.strip() in topic.read_text()
    assert records[0]["url"] == f"/topics/{topic.stem}/"
    dependencies = json.loads((output / "package.json").read_text())["dependencies"]
    assert not {"react", "react-dom", "likec4", "@astrojs/react"} & dependencies.keys()
