"""Release-note CLI contracts against committed fork changelogs."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fork_release_notes.py"
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


@pytest.fixture
def history(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init")
    git("config", "user.name", "Release Test")
    git("config", "user.email", "release@example.invalid")
    changelog = tmp_path / "CHANGELOG.fork.md"
    changelog.write_text(
        "## Added\n- **Kept** — original wording\n"
        "## Fixed\n- **Retired** — now shipped upstream\n"
    )
    git("add", ".")
    git("commit", "-m", "Previous release")
    previous = git("rev-parse", "HEAD")
    changelog.write_text(
        "## Added\n- **New feature** — available now\n"
        "  More detail for users.\n- **Kept** — revised wording\n"
        "## Fixed\n- **New fix** — correct results\n"
    )
    git("add", ".")
    git("commit", "-m", "Merge pull request #38 from Cubical6/release-improvements")
    return tmp_path, previous, git("rev-parse", "HEAD")


def render(history, channel="stable", *options):
    repo, _, commit = history
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-dir",
            str(repo),
            "--channel",
            channel,
            "--version",
            "6.1.1.dev2+gabcdef",
            "--commit",
            commit,
            *options,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.mark.parametrize("channel", ["latest", "stable"])
@pytest.mark.parametrize("previous_name", ["", "fork-v6.1.1.dev1"])
def test_release_notes_compare_entries_with_named_or_legacy_stable(
    history, channel, previous_name
):
    _, previous, commit = history
    output = render(
        history,
        channel,
        "--previous",
        previous,
        "--previous-name",
        previous_name,
        "--run-url",
        "https://example.invalid/actions/runs/42",
    )
    name = previous_name or "fork-stable"
    heading = (
        f"Fork changes not yet in {name} (since {previous[:7]})"
        if channel == "latest"
        else f"Fork changes since the previous {name} ({previous[:7]})"
    )
    assert f"## {heading}\n" in output
    assert f"Version: 6.1.1.dev2+gabcdef\nCommit: {commit}" in output
    assert (
        "### Added\n- **New feature** — available now\n  More detail for users."
        in output
    )
    assert "### Fixed\n- **New fix** — correct results" in output
    assert "### No longer fork-specific\n- Retired" in output
    assert "**Kept**" not in output
    assert (
        "## Merged\n- Merge pull request #38 from Cubical6/release-improvements"
        in output
    )
    assert "upstream PR 38" not in output
    assert ("Promoted from: https://example.invalid/actions/runs/42" in output) == (
        channel == "stable"
    )
    if previous_name:
        assert "fork-stable" not in output


@pytest.mark.parametrize("channel", ["latest", "stable"])
def test_first_release_lists_all_current_fork_changes(history, channel):
    output = render(history, channel)
    assert "## Fork changes on top of upstream\n" in output
    assert "- **New feature** — available now" in output
    assert "- **Kept** — revised wording" in output
    assert "- **New fix** — correct results" in output
    assert "Retired" not in output
    assert "## Merged" not in output


def test_release_notes_warn_when_previous_commit_cannot_be_compared(history):
    output = render(
        history, "stable", "--previous", "missing-commit", "--previous-name", "fork-v0"
    )
    assert "The previous stable commit could not be compared." in output
    assert "## Fork changes on top of upstream\n" in output
    assert "- **Kept** — revised wording" in output


def test_release_notes_do_not_notify_upstream(history):
    repo, _, _ = history
    changelog = repo / "CHANGELOG.fork.md"
    changelog.write_text(
        "## Fixed\n- **Safe references** — chunkhound/chunkhound#456 "
        "https://github.com/chunkhound/chunkhound/pull/789\n"
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "Fix upstream references"],
        check=True,
        capture_output=True,
    )
    output = render((repo, "", "HEAD"))
    assert "upstream PR 456" in output
    assert "upstream repository" in output
    assert "chunkhound/chunkhound" not in output
    assert "#456" not in output
