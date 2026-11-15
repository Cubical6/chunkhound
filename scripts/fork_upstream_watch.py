#!/usr/bin/env python3
"""Render the fork's upstream-sync issue from local Git history."""

import json
import re
import subprocess


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def safe_text(text: str) -> str:
    # Git commit subjects and tag names are untrusted, and upstream links in an
    # issue would notify upstream. Remove links before rewriting references.
    text = re.sub(
        r"(?:(?:https?|git)://)?(?:www\.)?github\.com/chunkhound/chunkhound(?:[^\s<>]*)?",
        "upstream repository",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bchunkhound/chunkhound#(\d+)\b", r"upstream PR \1", text, flags=re.IGNORECASE
    )
    text = re.sub(r"(?<![\w#])#(\d+)\b", r"upstream PR \1", text)
    # Break mentions even in untrusted Markdown with unmatched backticks.
    return text.replace("@", "@\u200b")


def main() -> None:
    behind = int(git("rev-list", "--count", "origin/main..upstream/main"))
    tags = git(
        "tag",
        "--list",
        "v*",
        "--merged",
        "upstream/main",
        "--no-merged",
        "origin/main",
        "--sort=-version:refname",
    ).splitlines()
    log = git(
        "log", "--first-parent", "--format=%h %s", "-30", "origin/main..upstream/main"
    )
    title = f"Upstream sync: {behind} commits behind"
    if tags:
        title += f" (new release {safe_text(tags[0])})"
    releases = "\n".join(f"- {safe_text(tag)}" for tag in tags) or "- None"
    history = "\n".join(f"- {safe_text(line)}" for line in log.splitlines()) or "- None"
    body = (
        f"The fork is {behind} commits behind upstream main.\n\n"
        f"## Upstream releases not merged\n\n{releases}\n\n"
        f"## Upstream changes (first parent, up to 30)\n\n{history}\n\n"
        "Review and sync upstream manually; merges may require conflict resolution.\n"
    )
    print(json.dumps({"behind": behind, "title": title, "body": body}))


if __name__ == "__main__":
    main()
