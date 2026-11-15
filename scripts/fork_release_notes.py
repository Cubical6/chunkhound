#!/usr/bin/env python3
"""Render fork release notes from committed changelogs, without network access."""

import argparse
import re
import subprocess
import unicodedata
from dataclasses import dataclass

INSTALL = (
    "Download the archive for your platform, verify its hash against manifest.json, "
    "and extract it. On Linux: uv pip install -c constraints.txt ./*.whl\n"
    "Intel macOS: the archive supplies wheels only; manage dependencies separately "
    "(locked pins are not Intel-compatible)."
)


def clean(text: str) -> str:
    """Keep line structure without control characters or upstream notifications."""
    text = re.sub(
        r"(?:(?:https?|git)://)?(?:www\.)?github\.com/chunkhound/chunkhound(?:[^\s<>]*)?",
        "upstream repository",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bchunkhound/chunkhound#(\d+)\b", r"upstream PR \1", text, flags=re.IGNORECASE
    )
    return "".join(
        char
        for char in text.replace("\t", "    ")
        if char == "\n" or unicodedata.category(char) != "Cc"
    )


@dataclass
class Entry:
    category: str
    text: str

    @property
    def identity(self) -> str:
        title = re.match(r"- \*\*(.+?)\*\*", self.text)
        return title[1] if title else " ".join(self.text.split())

    @property
    def title(self) -> str:
        return self.identity.removeprefix("- ")


def git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def entries(repo: str, commit: str) -> list[Entry]:
    result = git(repo, "show", f"{commit}:CHANGELOG.fork.md")
    if result.returncode:
        return []  # A changelog missing at this commit counts as empty.
    parsed: list[Entry] = []
    category = None
    current = None
    for line in clean(result.stdout).splitlines():
        if line.startswith("## "):
            category = line[3:].strip()
            current = None
        elif category is not None and line.startswith("- "):
            current = Entry(category, line)
            parsed.append(current)
        elif current is not None and line.startswith(" "):
            current.text += "\n" + line
        else:
            current = None
    return parsed


def bounded(blocks: list[str], limit: int) -> str:
    """Drop complete entries/sections from the end, never slicing a line."""

    def render(parts: list[str]) -> str:
        return "\n\n".join(parts) + "\n" if parts else ""

    if len(render(blocks)) <= limit:
        return render(blocks)
    marker = "… truncated"
    while blocks and len(render([*blocks, marker])) > limit:
        blocks.pop()
    return render([*blocks, marker]) if len(marker) + 1 <= limit else ""


def notes(args: argparse.Namespace) -> str:
    new = git(
        args.repo_dir,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{args.commit}^{{commit}}",
    )
    if new.returncode:
        raise ValueError(f"Cannot read release commit: {args.commit}")
    commit = new.stdout.strip()
    previous = ""
    if args.previous:
        old = git(
            args.repo_dir,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{args.previous}^{{commit}}",
        )
        if old.returncode == 0:
            candidate = old.stdout.strip()
            ancestry = git(
                args.repo_dir, "merge-base", "--is-ancestor", candidate, commit
            )
            if ancestry.returncode == 0:
                previous = candidate

    header = f"Version: {clean(args.version)}\nCommit: {clean(args.commit)}"
    if args.channel == "stable" and args.run_url:
        header += f"\nPromoted from: {clean(args.run_url)}"
    blocks = [header, INSTALL]
    if previous:
        short = args.previous[:7]
        previous_name = (
            clean(args.previous_name) if args.previous_name else "fork-stable"
        )
        heading = (
            f"Fork changes not yet in {previous_name} (since {short})"
            if args.channel == "latest"
            else f"Fork changes since the previous {previous_name} ({short})"
        )
    else:
        heading = "Fork changes on top of upstream"
    blocks.append(f"## {heading}")
    if args.previous and not previous:
        blocks.append("The previous stable commit could not be compared.")

    new_entries = entries(args.repo_dir, commit)
    old_entries = entries(args.repo_dir, previous) if previous else []
    old_ids = {entry.identity for entry in old_entries}
    new_ids = {entry.identity for entry in new_entries}
    added = [entry for entry in new_entries if entry.identity not in old_ids]
    removed = [entry for entry in old_entries if entry.identity not in new_ids]
    category = None
    for entry in added:
        prefix = f"### {entry.category}\n" if entry.category != category else ""
        blocks.append(prefix + entry.text)
        category = entry.category
    for index, entry in enumerate(removed):
        prefix = "### No longer fork-specific\n" if index == 0 else ""
        blocks.append(f"{prefix}- {entry.title}")
    if not added and not removed:
        blocks.append("No fork changelog entries changed.")
    if previous:
        log = git(
            args.repo_dir,
            "log",
            "--first-parent",
            "--format=%s",
            f"{previous}..{commit}",
        )
        if log.returncode:
            raise ValueError("Could not read merged commit subjects")
        subjects = clean(log.stdout).splitlines()
        for index, subject in enumerate(subjects[:50]):
            prefix = "## Merged\n" if index == 0 else ""
            blocks.append(f"{prefix}- {subject}")
        if len(subjects) > 50:
            blocks.append(f"… and {len(subjects) - 50} more")
    return bounded(blocks, args.max_chars)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True, choices=("latest", "stable"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--previous", default="")
    parser.add_argument("--previous-name", default="")
    parser.add_argument("--run-url")
    parser.add_argument("--repo-dir", default=".")
    parser.add_argument("--max-chars", type=int, default=100000)
    args = parser.parse_args()
    if args.max_chars < 0:
        parser.error("--max-chars must be nonnegative")
    try:
        print(notes(args), end="")
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
