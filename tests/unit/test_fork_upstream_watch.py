"""The scheduled watch reports safe, actionable upstream status."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/fork_upstream_watch.py"
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


def test_watch_renders_unmerged_releases_and_safe_issue_text(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    def report() -> dict:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    git("commit", "--allow-empty", "-qm", "Base")
    git("tag", "v1.0.0")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git(
        "commit",
        "--allow-empty",
        "-qm",
        "Fix #123 and https://github.com/chunkhound/chunkhound/pull/456",
    )
    git("tag", "v1.1.0")
    git(
        "commit", "--allow-empty", "-qm",
        "See chunkhound/chunkhound#789; thanks @alice and @org/team",
    )
    git("update-ref", "refs/remotes/upstream/main", "HEAD")

    issue = report()
    assert issue["behind"] == 2
    assert issue["title"] == "Upstream sync: 2 commits behind (new release v1.1.0)"
    assert "- v1.1.0" in issue["body"]
    assert "v1.0.0" not in issue["body"]
    assert "Fix upstream PR 123" in issue["body"]
    assert "See upstream PR 789" in issue["body"]
    assert "@\u200balice" in issue["body"]
    assert "@\u200borg/team" in issue["body"]
    assert "github.com/chunkhound/chunkhound" not in issue["body"].lower()
    assert "chunkhound/chunkhound#" not in issue["body"].lower()

    git("update-ref", "refs/remotes/origin/main", "HEAD")
    caught_up = report()
    assert caught_up["behind"] == 0
    assert caught_up["title"] == "Upstream sync: 0 commits behind"
    assert "v1.1.0" not in caught_up["body"]
