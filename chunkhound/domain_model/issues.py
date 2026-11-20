"""Shared, path-addressed domain contract errors."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    path: str
    code: str
    message: str


class ModelLoadError(ValueError):
    issues: tuple[Issue, ...]

    def __init__(self, issues: Iterable[Issue]) -> None:
        self.issues = tuple(issues)
        details = "\n".join(
            f"{issue.path}: {issue.code}: {issue.message}" for issue in self.issues[:20]
        )
        super().__init__(f"{len(self.issues)} issues in domain model\n{details}")
