import argparse
import json
from pathlib import Path

from chunkhound.api.cli.parsers.autodoc_parser import add_autodoc_subparser
from chunkhound.autodoc.site_writer import write_astro_assets_only


def test_autodoc_parser_accepts_assets_only_flag() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_autodoc_subparser(subparsers)

    args = parser.parse_args(["autodoc", ".", "--out-dir", "site", "--assets-only"])

    assert args.command == "autodoc"
    assert args.assets_only is True


def test_autodoc_parser_defaults_audience_to_balanced() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_autodoc_subparser(subparsers)

    args = parser.parse_args(["autodoc", ".", "--out-dir", "site"])

    assert args.command == "autodoc"
    assert args.audience == "balanced"


def test_autodoc_parser_accepts_audience_numeric_and_named_values() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_autodoc_subparser(subparsers)

    base = ["autodoc", ".", "--out-dir", "site", "--audience"]

    assert parser.parse_args([*base, "1"]).audience == "technical"
    assert parser.parse_args([*base, "technical"]).audience == "technical"
    assert parser.parse_args([*base, "2"]).audience == "balanced"
    assert parser.parse_args([*base, "balanced"]).audience == "balanced"
    assert parser.parse_args([*base, "3"]).audience == "end-user"
    assert parser.parse_args([*base, "end-user"]).audience == "end-user"
    assert parser.parse_args([*base, "end_user"]).audience == "end-user"


def test_autodoc_parser_accepts_map_audience() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_autodoc_subparser(subparsers)

    args = parser.parse_args(
        ["autodoc", ".", "--out-dir", "site", "--map-audience", "3"]
    )
    assert args.map_audience == "end-user"


def test_write_astro_assets_only_preserves_topic_pages(tmp_path: Path) -> None:
    output_dir = tmp_path / "site"
    topics_dir = output_dir / "src" / "pages" / "topics"
    data_dir = output_dir / "src" / "data"
    topics_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    (data_dir / "site.json").write_text(
        json.dumps(
            {
                "title": "Test Site",
                "tagline": "Tagline",
                "scopeLabel": "/",
                "generatedAt": "2025-12-22T00:00:00Z",
                "sourceDir": str(tmp_path),
                "topicCount": 1,
            }
        ),
        encoding="utf-8",
    )

    topic_path = topics_dir / "topic.md"
    topic_path.write_text("original topic content", encoding="utf-8")

    write_astro_assets_only(output_dir=output_dir)

    assert topic_path.read_text(encoding="utf-8") == "original topic content"


def test_write_astro_assets_only_preserves_package_and_readme_without_site_json(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "site"
    (output_dir / "src" / "pages" / "topics").mkdir(parents=True)

    package_json_path = output_dir / "package.json"
    readme_path = output_dir / "README.md"
    package_json_path.write_text("sentinel package.json", encoding="utf-8")
    readme_path.write_text("sentinel README", encoding="utf-8")

    write_astro_assets_only(output_dir=output_dir)

    assert package_json_path.read_text(encoding="utf-8") == "sentinel package.json"
    assert readme_path.read_text(encoding="utf-8") == "sentinel README"


def test_assets_only_preserves_architecture_and_ignores_changed_input_model(
    tmp_path: Path,
) -> None:
    output = tmp_path / "site"
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    producer = input_dir / "scope_c4_model.json"
    producer.write_text('{"schema_version": 999}')
    originals = {
        "src/data/architecture.json": (
            b'{"schemaVersion":1,"enabled":true,"contextView":"index",'
            b'"views":{},"elements":{},"topics":{}}\n'
        ),
        "src/data/search.json": b'[{"title":"Original"}]\n',
        "src/data/nav.json": b'{"groups":[]}\n',
        "src/pages/topics/original.md": b"# Original topic\n",
        "likec4/model.c4": b"// original model\n",
        "likec4/specification.c4": b"// original specification\n",
        "likec4/views.c4": b"// original views\n",
        "likec4/user.txt": b"user content\n",
    }
    for relative, content in originals.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    write_astro_assets_only(output_dir=output)
    for relative, content in originals.items():
        assert (output / relative).read_bytes() == content
    assert producer.read_text() == '{"schema_version": 999}'
    assert (output / "src/pages/architecture/index.astro").exists()


def test_assets_only_initializes_disabled_data_for_older_site(tmp_path: Path) -> None:
    write_astro_assets_only(output_dir=tmp_path)
    assert json.loads((tmp_path / "src/data/architecture.json").read_text()) == {
        "schemaVersion": 1,
        "enabled": False,
        "contextView": "index",
        "views": {},
        "elements": {},
        "topics": {},
    }
