"""LanceDB scope failures must not masquerade as an empty file index."""

import pytest

from chunkhound.providers.database.lancedb_provider import LanceDBProvider


class _ExplodingFilesTable:
    def search(self):  # noqa: ANN001 - test stub
        raise RuntimeError("boom")

    def count_rows(self) -> int:
        raise RuntimeError("boom")

    def head(self, *_: object, **__: object):  # noqa: ANN001 - test stub
        raise RuntimeError("boom")


class _ExplodingChunksTable:
    def count_rows(self) -> int:
        raise RuntimeError("boom")

    def to_pandas(self, *_: object, **__: object):  # noqa: ANN001 - test stub
        raise RuntimeError("boom")


def test_lancedb_scope_stats_handles_errors() -> None:
    provider = LanceDBProvider.__new__(LanceDBProvider)
    provider._files_table = _ExplodingFilesTable()
    provider._chunks_table = _ExplodingChunksTable()

    total_files, total_chunks = provider._executor_get_scope_stats(object(), {}, "scope/")
    assert total_files == 0
    assert total_chunks == 0


@pytest.mark.parametrize("scope_prefix", [None, "scope/"])
def test_lancedb_scope_paths_propagates_errors(scope_prefix: str | None) -> None:
    provider = LanceDBProvider.__new__(LanceDBProvider)
    provider._files_table = _ExplodingFilesTable()

    with pytest.raises(RuntimeError, match="boom"):
        provider._executor_get_scope_file_paths(object(), {}, scope_prefix)

