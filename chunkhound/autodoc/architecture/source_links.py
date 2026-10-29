"""Commit-pinned public codehost URLs, or readable source metadata without a link."""

import re
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

from chunkhound.autodoc.architecture.model import C4Model, Source

_COMMIT = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
_SCP_REMOTE = re.compile(r"(?:[^/@:]+@)?(?P<host>[^/:]+):(?P<path>.+)\Z")
_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}


def _remote(remote: str | None) -> tuple[str, str] | None:
    if not remote:
        return None
    try:
        if "://" in remote:
            parsed = urlsplit(remote)
            if parsed.scheme not in ("https", "ssh"):
                return None
            if parsed.port not in (None, 443 if parsed.scheme == "https" else 22):
                return None
            host, path = parsed.hostname, parsed.path.lstrip("/")
        else:
            match = _SCP_REMOTE.fullmatch(remote)
            if not match:
                return None
            host, path = match.group("host").lower(), match.group("path")
    except ValueError:
        # Invalid bracketed hosts and ports are expected remote-input errors.
        return None
    if host not in _HOSTS:
        return None
    path = path.removesuffix(".git").rstrip("/")
    parts = path.split("/")
    if len(parts) < 2 or any(not part or part in (".", "..") for part in parts):
        return None
    if any(character in path for character in ("?", "#", "\\", "\n", "\r")):
        return None
    return host, quote(path, safe="/")


class SourceLinkBuilder:
    def __init__(self, model: C4Model) -> None:
        self._repositories = {
            repository.id: repository for repository in model.repositories
        }

    def link(self, source: Source) -> str | None:
        repository = self._repositories.get(source.repository_id)
        if repository is None or not _COMMIT.fullmatch(repository.commit):
            return None
        remote = _remote(repository.remote_url)
        if remote is None:
            return None
        path, prefix = PurePosixPath(source.path), PurePosixPath(repository.path)
        if path.is_absolute() or prefix.is_absolute():
            return None
        if ".." in path.parts or ".." in prefix.parts:
            return None
        try:
            relative = path.relative_to(prefix)
        except ValueError:
            return None
        if (
            not relative.parts
            or source.start_line < 1
            or source.end_line < source.start_line
        ):
            return None
        host, project = remote
        file_path = quote(relative.as_posix(), safe="/")
        base = f"https://{host}/{project}"
        commit = repository.commit
        start, end = source.start_line, source.end_line
        if host == "github.com":
            anchor = f"L{start}" if start == end else f"L{start}-L{end}"
            return f"{base}/blob/{commit}/{file_path}#{anchor}"
        if host == "gitlab.com":
            anchor = f"L{start}" if start == end else f"L{start}-{end}"
            return f"{base}/-/blob/{commit}/{file_path}#{anchor}"
        anchor = f"lines-{start}" if start == end else f"lines-{start}:{end}"
        return f"{base}/src/{commit}/{file_path}#{anchor}"
