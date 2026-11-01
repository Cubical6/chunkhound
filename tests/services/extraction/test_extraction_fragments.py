"""Contract: fragmentation covers every source line exactly once within budget."""

from pathlib import Path

import pytest

from chunkhound.services.extraction.fragments import (
    FragmentTooLargeError,
    fragment_document,
)
from chunkhound.services.extraction.sources import read_source


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _covered(fragments) -> list[int]:
    lines: list[int] = []
    for fragment in fragments:
        lines.extend(range(fragment.start_line, fragment.end_line + 1))
    return lines


def test_every_line_in_exactly_one_fragment(tmp_path):
    big_section = "\n\n".join(f"Alinea {n} " + "met tekst " * 30 for n in range(12))
    text = "\n".join(
        [
            "---",
            "title: Architectuur",
            "---",
            "Intro voor het eerste kopje.",
            "# Systeem",
            "Overzicht.",
            "```text",
            "# geen kopje binnen een codeblok",
            "```",
            "## Containers",
            "### Indexeerservice",
            big_section,
            "### Zoekservice",
            "Zoekt in de index.",
            "## Opslag",
            "```python",
            "# niet afgesloten codeblok loopt door tot het einde",
            "# ook geen kopje",
        ]
    )
    _write(tmp_path, "arch.md", text)
    source = read_source(tmp_path, "arch.md", strict=True)
    max_chars = 900

    fragments = fragment_document(source, max_chars=max_chars, markdown=True)

    assert sorted(_covered(fragments)) == list(range(1, len(source.lines) + 1))
    assert len(_covered(fragments)) == len(source.lines)
    for fragment in fragments:
        assert len(fragment.render("F9999", "absolute")) <= max_chars
    # Lines inside fences never become headings in the context chain.
    assert all(
        "geen kopje" not in title
        for fragment in fragments
        for title in fragment.heading_path
    )
    indexer = [f for f in fragments if "Alinea 5 " in f.text and f.start_line > 11]
    assert indexer
    assert indexer[0].heading_path == ("Systeem", "Containers", "Indexeerservice")


def test_unsplittable_line_is_reported_with_location(tmp_path):
    _write(tmp_path, "README.md", "# Kop\nkort\n" + "x" * 2_000 + "\n")
    source = read_source(tmp_path, "README.md", strict=True)

    with pytest.raises(FragmentTooLargeError) as raised:
        fragment_document(source, max_chars=500, markdown=True)

    assert raised.value.path == "README.md"
    assert raised.value.line == 3


def test_non_markdown_readme_ignores_hash_lines(tmp_path):
    text = "Titel\n#####\n\n" + "\n\n".join("woord " * 40 for _ in range(6))
    _write(tmp_path, "README.rst", text)
    source = read_source(tmp_path, "README.rst", strict=True)

    fragments = fragment_document(source, max_chars=700, markdown=False)

    assert sorted(_covered(fragments)) == list(range(1, len(source.lines) + 1))
    assert all(fragment.heading_path == () for fragment in fragments)
