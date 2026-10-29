from __future__ import annotations

from chunkhound.autodoc.template_loader import load_text


def test_template_loader_rejects_path_traversal() -> None:
    try:
        load_text("../README.md")
    except ValueError as exc:
        assert "traverse" in str(exc)
    else:
        raise AssertionError("Expected ValueError for path traversal")

