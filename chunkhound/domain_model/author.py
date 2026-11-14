"""Resolve the local Git identity for each repository in a write request."""

import getpass
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from chunkhound.utils.git_safe import GitCommandError, run_git


class Author(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    name: str
    email: str | None = None


def resolve_author(
    project_root: Path, repository_keys: Iterable[str]
) -> dict[str, Author]:
    """Use repository-local Git config, falling back to the OS user."""
    authors = {}
    for key in set(repository_keys):
        repository = project_root / key
        cwd = (
            repository
            if key != "root" and repository.is_dir() and (repository / ".git").exists()
            else project_root
        )
        values: dict[str, str | None] = {}
        for field in ("name", "email"):
            try:
                result = run_git(["config", "--get", f"user.{field}"], cwd=cwd)
                values[field] = (
                    result.stdout.strip() or None if result.returncode == 0 else None
                )
            except GitCommandError:
                values[field] = None
        name = values["name"]
        authors[key] = (
            Author(name=name, email=values["email"])
            if name
            else Author(name=getpass.getuser())
        )
    return authors
