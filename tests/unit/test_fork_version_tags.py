"""Fork release tags must not affect the upstream-derived package version."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import tomllib


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_fork_tags_do_not_change_package_version(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[2] / "pyproject.toml"
    settings = tomllib.loads(project.read_text(encoding="utf-8"))["tool"]["hatch"][
        "version"
    ]

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        )

    git("init")
    git("config", "user.name", "Version contract")
    git("config", "user.email", "version@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("config", "tag.gpgsign", "false")
    git("commit", "--allow-empty", "-m", "upstream release")
    git("tag", "v6.1.0")
    git("commit", "--allow-empty", "-m", "first fork change")
    git("commit", "--allow-empty", "-m", "second fork change")

    def version() -> str:
        # hatch-vcs is an isolated build dependency, not a runtime dependency.
        result = subprocess.run(
            [
                "uv",
                "run",
                "--no-project",
                "--with",
                "hatch-vcs",
                "python",
                "-W",
                "error::DeprecationWarning",
                "-c",
                "import json, sys; from setuptools_scm import get_version; "
                "print(get_version(**json.loads(sys.argv[1])))",
                json.dumps(settings.get("raw-options", {})),
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    before = version()
    assert before.split("+")[0] == "6.1.1.dev2"
    git("tag", "fork-v6.1.1.dev2")
    git("tag", "fork-v9.9.9")
    assert version() == before
