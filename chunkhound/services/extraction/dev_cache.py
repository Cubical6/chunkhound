"""Opt-in development caches backed by the shared disposable decision store.

``root`` is the project root. Callers own prompt versions and answer validation;
this module deliberately knows nothing about C4 or research result types.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chunkhound.interfaces.llm_provider import LLMProvider
from chunkhound.services.extraction.store import (
    DECISION_FORMAT_VERSION,
    DecisionStore,
    ProviderIdentity,
    key_from_parts,
)

SOURCE_MANIFEST_FORMAT_VERSION = 1


@dataclass
class CacheCounts:
    reused: int = 0
    new: int = 0


class DevCache:
    """No filesystem access when disabled; count accepted hits and stored results.

    ``counts`` is indexed by question. ``created_at`` holds the creation time of
    the last accepted hit per question, for reports such as "plan reused from".
    Misses do not count as new until a replacement is successfully stored.
    """

    def __init__(self, root: Path, *, enabled: bool) -> None:
        self.enabled = enabled
        self._store = DecisionStore(
            root / ".chunkhound" / "extraction" / "decisions", read_only=False
        )
        self.counts: dict[str, CacheCounts] = {}
        self.created_at: dict[str, str] = {}

    @staticmethod
    def _key_parts(
        question: str,
        question_version: str,
        provider: ProviderIdentity,
        item: Any,
    ) -> dict[str, Any]:
        return {
            "format": DECISION_FORMAT_VERSION,
            "question": question,
            "question_version": question_version,
            "provider": asdict(provider),
            "item": item,
        }

    def get(
        self,
        question: str,
        question_version: str,
        provider: ProviderIdentity,
        item: Any,
        validate: Callable[[Any], bool] | None = None,
    ) -> Any | None:
        if not self.enabled:
            return None
        self.created_at.pop(question, None)
        parts = self._key_parts(question, question_version, provider, item)
        envelope = self._store.get(question, parts)
        if envelope is None or "answer" not in envelope:
            return None
        created_at = envelope.get("created_at")
        if not isinstance(created_at, str):
            return None
        try:
            timestamp = datetime.fromisoformat(created_at)
            if timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
                return None
        except ValueError:
            return None
        answer = envelope["answer"]
        if answer is None or (validate is not None and not validate(answer)):
            return None
        self._store.touch(question, key_from_parts(parts))
        self.counts.setdefault(question, CacheCounts()).reused += 1
        self.created_at[question] = created_at
        return answer

    def put(
        self,
        question: str,
        question_version: str,
        provider: ProviderIdentity,
        item: Any,
        answer: Any,
    ) -> None:
        if not self.enabled or answer is None:
            return
        parts = self._key_parts(question, question_version, provider, item)
        self._store.put(
            question,
            parts,
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "answer": answer,
            },
        )
        self.counts.setdefault(question, CacheCounts()).new += 1


def provider_identity(provider: LLMProvider) -> ProviderIdentity:
    """Identify the selected instance, including resolved endpoint and effort.

    Unlike C4's role configuration, the instance also reflects provider defaults
    and environment-resolved settings. Some providers expose effort only as an
    internal attribute; keep that compatibility detail confined to this helper.
    """
    effort = getattr(provider, "reasoning_effort", None)
    if effort is None:
        effort = getattr(provider, "_reasoning_effort", None)
    endpoint = getattr(provider, "base_url", None)
    if endpoint is None:
        client = getattr(provider, "_client", None)
        endpoint = getattr(client, "base_url", None)
    return ProviderIdentity(
        provider=provider.name,
        model=provider.model,
        reasoning_effort=None if effort is None else str(effort),
        base_url=None if endpoint is None else str(endpoint),
    )


def source_manifest_version(paths_globs: Sequence[str], base: Path) -> str | None:
    """Hash sorted relative source paths and contents, or fail closed.

    Every pattern must match a readable file. Empty/partial installations must
    not silently yield a reusable version. Overlapping patterns are deduplicated.
    """
    try:
        paths: set[Path] = set()
        for pattern in paths_globs:
            matches = {path for path in base.glob(pattern) if path.is_file()}
            if not matches:
                return None
            paths.update(matches)
        if not paths:
            return None
        manifest = [
            {
                "path": path.relative_to(base).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(
                paths, key=lambda path: path.relative_to(base).as_posix()
            )
        ]
        return key_from_parts(
            {
                "source_manifest_format": SOURCE_MANIFEST_FORMAT_VERSION,
                "files": manifest,
            }
        )
    except (OSError, ValueError):
        return None
