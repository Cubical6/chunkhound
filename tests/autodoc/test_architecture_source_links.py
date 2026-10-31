"""Source links use their own repository commit, never a moving branch or token."""

from pathlib import Path

import pytest

from chunkhound.autodoc.architecture.source_links import SourceLinkBuilder
from tests.autodoc.test_architecture_input import load_document, model_document


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        (
            "https://github.com/acme/frontend.git",
            "https://github.com/acme/frontend/blob/"
            + "b" * 40
            + "/src/client.ts#L2-L8",
        ),
        (
            "git@github.com:acme/frontend.git",
            "https://github.com/acme/frontend/blob/"
            + "b" * 40
            + "/src/client.ts#L2-L8",
        ),
        (
            "ssh://git@github.com/acme/frontend.git",
            "https://github.com/acme/frontend/blob/"
            + "b" * 40
            + "/src/client.ts#L2-L8",
        ),
        (
            "https://gitlab.com/acme/group/frontend.git",
            "https://gitlab.com/acme/group/frontend/-/blob/"
            + "b" * 40
            + "/src/client.ts#L2-8",
        ),
        (
            "git@gitlab.com:acme/group/frontend.git",
            "https://gitlab.com/acme/group/frontend/-/blob/"
            + "b" * 40
            + "/src/client.ts#L2-8",
        ),
        (
            "ssh://git@gitlab.com/acme/group/frontend.git",
            "https://gitlab.com/acme/group/frontend/-/blob/"
            + "b" * 40
            + "/src/client.ts#L2-8",
        ),
        (
            "https://bitbucket.org/acme/frontend.git",
            "https://bitbucket.org/acme/frontend/src/"
            + "b" * 40
            + "/src/client.ts#lines-2:8",
        ),
        (
            "git@bitbucket.org:acme/frontend.git",
            "https://bitbucket.org/acme/frontend/src/"
            + "b" * 40
            + "/src/client.ts#lines-2:8",
        ),
        (
            "ssh://git@bitbucket.org/acme/frontend.git",
            "https://bitbucket.org/acme/frontend/src/"
            + "b" * 40
            + "/src/client.ts#lines-2:8",
        ),
        (
            "https://user:secret@github.com/acme/frontend.git?access_token=hidden",
            "https://github.com/acme/frontend/blob/"
            + "b" * 40
            + "/src/client.ts#L2-L8",
        ),
    ],
)
def test_R11_sources_use_their_own_repository_commit(
    tmp_path: Path, remote: str, expected: str
):
    document = model_document()
    document["repositories"].append(
        {"id": "frontend", "path": "frontend", "remote_url": remote, "commit": "b" * 40}
    )
    document["sources"][0]["repository"] = "frontend"
    model = load_document(tmp_path, document)
    assert model is not None
    assert SourceLinkBuilder(model).link(model.sources[0]) == expected
    assert (
        SourceLinkBuilder(model).link(model.sources[1])
        == "https://github.com/org/root/blob/" + "a" * 40 + "/README.md#L1-L3"
    )


@pytest.mark.parametrize(
    ("remote", "commit", "repository_path", "source_path"),
    [
        (
            "https://unknown.example/acme/frontend.git",
            "b" * 40,
            "frontend",
            "frontend/src/client.ts",
        ),
        (
            "https://github.com/acme/frontend.git",
            "main",
            "frontend",
            "frontend/src/client.ts",
        ),
        (
            "https://github.com/acme/frontend.git",
            "",
            "frontend",
            "frontend/src/client.ts",
        ),
        (None, "b" * 40, "frontend", "frontend/src/client.ts"),
        (
            "https://github.com/acme/frontend.git",
            "b" * 40,
            "front",
            "frontend/src/client.ts",
        ),
        (
            "https://github.com/acme/frontend.git",
            "b" * 40,
            "frontend",
            "frontend/../backend/client.ts",
        ),
        (
            "https://github.com.evil.test/acme/frontend.git",
            "b" * 40,
            "frontend",
            "frontend/src/client.ts",
        ),
    ],
)
def test_unsafe_or_unpinned_sources_remain_text(
    tmp_path: Path,
    remote: str | None,
    commit: str,
    repository_path: str,
    source_path: str,
):
    document = model_document()
    document["repositories"][0].update(
        path=repository_path, remote_url=remote, commit=commit
    )
    document["sources"][0]["path"] = source_path
    model = load_document(tmp_path, document)
    assert model is not None
    source = model.sources[0]
    assert SourceLinkBuilder(model).link(source) is None
    assert source.path == source_path
    assert (source.start_line, source.end_line) == (2, 8)


def test_nested_repository_path_and_source_url_are_component_safe(tmp_path: Path):
    document = model_document()
    document["repositories"][0]["path"] = "frontend/packages/client"
    document["sources"][0].update(
        path="frontend/packages/client/src/space #é.ts", start_line=4, end_line=4
    )
    model = load_document(tmp_path, document)
    assert model is not None
    assert (
        SourceLinkBuilder(model).link(model.sources[0])
        == "https://github.com/org/root/blob/"
        + "a" * 40
        + "/src/space%20%23%C3%A9.ts#L4"
    )
