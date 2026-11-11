"""Contracts for opt-in reuse, validation, and conservative source versioning."""

import json
import os
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from chunkhound.providers.llm.openai_llm_provider import OpenAILLMProvider
from chunkhound.services.extraction.dev_cache import (
    DevCache,
    provider_identity,
    source_manifest_version,
)
from chunkhound.services.extraction.store import ProviderIdentity

PROVIDER = ProviderIdentity("openai", "test-model", "low", "https://example.invalid")


def test_round_trip_reuse_and_reporting(tmp_path: Path) -> None:
    cache = DevCache(tmp_path, enabled=True)
    answer = {"answer": "Research", "metadata": {"sources": ["file.py"]}}
    cache.put("topic_research", "v1", PROVIDER, {"query": "Overview"}, answer)
    assert cache.counts["topic_research"].new == 1

    # A fresh run reuses persisted answers, not an in-memory result.
    warm = DevCache(tmp_path, enabled=True)
    assert warm.get("topic_research", "v1", PROVIDER, {"query": "Overview"}) == answer
    assert warm.counts["topic_research"].reused == 1
    timestamp = datetime.fromisoformat(warm.created_at["topic_research"])
    assert timestamp.utcoffset() == timedelta(0)
    assert warm.get("topic_research", "v2", PROVIDER, {"query": "Overview"}) is None
    assert warm.get("topic_research", "v1", PROVIDER, {"query": "Other"}) is None
    assert warm.get("other_question", "v1", PROVIDER, {"query": "Overview"}) is None


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "other"},
        {"model": "other-model"},
        {"reasoning_effort": "high"},
        {"base_url": "https://other.invalid"},
    ],
)
def test_provider_changes_miss(tmp_path: Path, change: dict[str, str]) -> None:
    cache = DevCache(tmp_path, enabled=True)
    cache.put("hyde_plan", "v1", PROVIDER, "scope", "Raw plan")
    assert cache.get("hyde_plan", "v1", replace(PROVIDER, **change), "scope") is None


def test_only_validated_answers_extend_cache_lifetime(tmp_path: Path) -> None:
    cache = DevCache(tmp_path, enabled=True)
    cache.put("topic_research", "v1", PROVIDER, "topic", {"hash": "old"})
    path = next(tmp_path.rglob("*.json"))
    os.utime(path, (1, 1))
    assert (
        cache.get(
            "topic_research",
            "v1",
            PROVIDER,
            "topic",
            validate=lambda a: a["hash"] == "new",
        )
        is None
    )
    assert path.stat().st_mtime == 1
    assert cache.counts["topic_research"].reused == 0
    assert cache.get(
        "topic_research", "v1", PROVIDER, "topic", validate=lambda a: a["hash"] == "old"
    ) == {"hash": "old"}
    assert path.stat().st_mtime > 1
    assert cache.counts["topic_research"].reused == 1


def test_disabled_cache_does_no_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("disabled cache accessed the filesystem")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", forbidden)
        patch.setattr(Path, "mkdir", forbidden)
        patch.setattr(os, "utime", forbidden)
        cache = DevCache(tmp_path, enabled=False)
        cache.put("hyde_plan", "v1", PROVIDER, "scope", "Raw plan")
        assert cache.get("hyde_plan", "v1", PROVIDER, "scope") is None
        assert cache.counts == {}
    assert list(tmp_path.iterdir()) == []


def test_malformed_or_foreign_entries_are_misses(tmp_path: Path) -> None:
    cache = DevCache(tmp_path, enabled=True)
    cache.put("hyde_plan", "v1", PROVIDER, "scope", ["arch", "ops"])
    path = next(tmp_path.rglob("*.json"))
    original = json.loads(path.read_text())
    malformed = [
        "not json",
        json.dumps({**original, "key_parts": {"question": "foreign"}}),
        json.dumps({**original, "answer": {"answer": "no timestamp"}}),
        json.dumps({**original, "answer": {"created_at": "invalid", "answer": "x"}}),
    ]
    for content in malformed:
        path.write_text(content)
        os.utime(path, (1, 1))
        assert cache.get("hyde_plan", "v1", PROVIDER, "scope") is None
        assert path.stat().st_mtime == 1


def test_identity_uses_selected_provider_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Constructing the real adapter does not issue requests.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://environment.invalid/v1")
    provider = OpenAILLMProvider(api_key="fake", model="gpt-5", reasoning_effort="high")
    assert provider_identity(provider) == ProviderIdentity(
        "openai", "gpt-5", "high", "https://environment.invalid/v1/"
    )


def test_manifest_tracks_content_paths_and_not_order_or_checkout_root(
    tmp_path: Path,
) -> None:
    base = tmp_path / "first"
    base.mkdir()
    (base / "a.py").write_text("first")
    (base / "b.py").write_text("second")
    version = source_manifest_version(["*.py"], base)
    assert version is not None and len(version) == 64
    assert source_manifest_version(["b.py", "a.py", "*.py"], base) == version
    other = tmp_path / "second"
    other.mkdir()
    (other / "a.py").write_text("first")
    (other / "b.py").write_text("second")
    assert source_manifest_version(["*.py"], other) == version
    (base / "a.py").write_text("changed")
    assert source_manifest_version(["*.py"], base) != version
    (base / "a.py").write_text("first")
    (base / "b.py").rename(base / "c.py")
    assert source_manifest_version(["*.py"], base) != version


def test_missing_or_unreadable_sources_disable_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "source.py").write_text("code")
    assert source_manifest_version(["*.py", "missing.py"], tmp_path) is None
    assert source_manifest_version([], tmp_path) is None

    def unreadable(path: Path) -> bytes:
        raise PermissionError("unreadable source")

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    assert source_manifest_version(["*.py"], tmp_path) is None
