from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from chunkhound.autodoc.architecture.coverage import CoverageIndex
from chunkhound.autodoc.architecture.likec4_ids import LikeC4IdAllocator
from chunkhound.autodoc.architecture.likec4_writer import LikeC4Writer
from chunkhound.autodoc.architecture.site_data import (
    build_search_records,
    build_site_data,
)
from chunkhound.autodoc.architecture.source_links import SourceLinkBuilder
from chunkhound.autodoc.architecture.views import build_views
from chunkhound.autodoc.models import (
    CodeMapperIndex,
    DocsitePage,
    DocsiteSite,
    NavGroup,
    SiteExtras,
)
from chunkhound.autodoc.site_writer_dirs import (
    ensure_astro_asset_dirs,
    ensure_astro_site_dirs,
)
from chunkhound.autodoc.site_writer_metadata import (
    _render_index_metadata as _metadata_render_index_metadata,
)
from chunkhound.autodoc.site_writer_renderers import (
    _render_astro_config,
    _render_doc_layout,
    _render_favicon_bytes,
    _render_font_bytes,
    _render_font_license_text,
    _render_global_css,
    _render_glossary_page,
    _render_index_page,
    _render_nav_json,
    _render_package_json,
    _render_readme,
    _render_search_index,
    _render_site_json,
    _render_topic_page,
    _render_tsconfig,
)
from chunkhound.autodoc.template_loader import load_bytes, load_text

_MAP_ASSETS = (
    "src/pages/architecture/index.astro",
    "src/components/ArchitectureMap.astro",
    "src/components/ArchitectureMap.tsx",
    "src/components/ArchitectureMiniMap.astro",
    "src/components/ArchitectureMiniMap.tsx",
)
_MAP_ARCHIVE = "vendor/likec4/likec4-1.60.0-chunkhound.1.tgz"
_MAP_DSL = tuple(f"likec4/{name}.c4" for name in ("specification", "model", "views"))


def write_astro_assets_only(*, output_dir: Path) -> None:
    """
    Update only the Astro runtime assets in an already-generated docsite.

    Intended for iterating on UI/layout without rewriting topic markdown pages.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    architecture_path = output_dir / "src/data/architecture.json"
    if not architecture_path.exists():
        architecture_path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(
            architecture_path,
            json.dumps(
                build_site_data(
                    model=None, coverage=None, views=[], ids=None, pages=[]
                ),
                indent=2,
            )
            + "\n",
        )
    architecture_enabled = (
        _has_published_architecture(output_dir) and (output_dir / "likec4").is_dir()
    )
    if architecture_enabled:
        _write_map_assets(output_dir)

    asset_dirs = ensure_astro_asset_dirs(output_dir=output_dir)

    site = _load_site_from_existing(output_dir)
    _write_common_configs(
        output_dir=output_dir, site=site, architecture_enabled=architecture_enabled
    )
    _write_common_assets(
        layouts_dir=asset_dirs.layouts_dir,
        styles_dir=asset_dirs.styles_dir,
        public_dir=asset_dirs.public_dir,
        architecture_enabled=architecture_enabled,
    )


def write_astro_site(
    *,
    output_dir: Path,
    site: DocsiteSite,
    pages: list[DocsitePage],
    index: CodeMapperIndex,
    allow_delete_topics_dir: bool,
    extras: SiteExtras,
    log_warning: Callable[[str], None] | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    site_dirs = ensure_astro_site_dirs(
        output_dir=output_dir,
        clean_topics_dir=True,
        allow_delete_topics_dir=allow_delete_topics_dir,
    )
    architecture_records = _publish_architecture(
        output_dir=output_dir,
        site=site,
        pages=pages,
        extras=extras,
        log_warning=log_warning,
    )
    _write_common_configs(
        output_dir=output_dir,
        site=site,
        architecture_enabled=extras.architecture is not None,
    )

    _write_text(site_dirs.data_dir / "site.json", _render_site_json(site))
    _write_text(
        site_dirs.data_dir / "search.json",
        _render_search_index(pages, architecture_records),
    )
    _write_common_assets(
        layouts_dir=site_dirs.layouts_dir,
        styles_dir=site_dirs.styles_dir,
        public_dir=site_dirs.public_dir,
        architecture_enabled=extras.architecture is not None,
    )

    nav_payload: list[NavGroup]
    if extras.nav_groups:
        nav_payload = extras.nav_groups
    else:
        nav_payload = [NavGroup(title="Topics", slugs=[page.slug for page in pages])]
    _write_text(site_dirs.data_dir / "nav.json", _render_nav_json(nav_payload))

    _write_text(
        site_dirs.pages_dir / "index.md",
        _render_index_page(
            site=site,
            pages=pages,
            index=index,
            overview_markdown=extras.homepage_overview,
        ),
    )

    glossary_path = site_dirs.pages_dir / "glossary.md"
    if extras.glossary_terms:
        _write_text(glossary_path, _render_glossary_page(extras.glossary_terms))
    elif glossary_path.exists():
        glossary_path.unlink()

    for page in pages:
        _write_text(
            site_dirs.topics_dir / f"{page.slug}.md",
            _render_topic_page(page),
        )


def _has_published_architecture(output_dir: Path) -> bool:
    try:
        data = json.loads(
            (output_dir / "src/data/architecture.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return False
    return (
        isinstance(data, dict)
        and data.get("schemaVersion") == 1
        and data.get("enabled") is True
    )


def _write_map_assets(output_dir: Path) -> None:
    for relative in _MAP_ASSETS:
        path = output_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(path, load_text(relative))
    archive = output_dir / _MAP_ARCHIVE
    archive.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes(archive, load_bytes(_MAP_ARCHIVE))


def _remove_owned_map(output_dir: Path) -> None:
    paths = [
        output_dir / relative for relative in (*_MAP_DSL, *_MAP_ASSETS, _MAP_ARCHIVE)
    ]
    for path in paths:
        if path.is_file():
            path.unlink()
    # Only empty managed directories: unknown files are never removed.
    for directory in sorted({path.parent for path in paths}, reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


def _publish_architecture(
    *,
    output_dir: Path,
    site: DocsiteSite,
    pages: list[DocsitePage],
    extras: SiteExtras,
    log_warning: Callable[[str], None] | None,
) -> list[dict[str, str]]:
    previously_owned = _has_published_architecture(output_dir)
    model = extras.architecture
    records: list[dict[str, str]] = []
    if model is None:
        if previously_owned:
            _remove_owned_map(output_dir)
        data = build_site_data(
            model=None, coverage=None, views=[], ids=None, pages=pages
        )
    else:
        coverage = CoverageIndex(model, pages, Path(site.source_dir), log_warning)
        ids = LikeC4IdAllocator(model)
        views = build_views(model=model, coverage=coverage, pages=pages, ids=ids)
        LikeC4Writer(
            coverage=coverage, ids=ids, source_links=SourceLinkBuilder(model)
        ).write(model, views, output_dir / "likec4")
        data = build_site_data(
            model=model, coverage=coverage, views=views, ids=ids, pages=pages
        )
        records = build_search_records(model=model, data=data)
        _write_map_assets(output_dir)
    _write_text(
        output_dir / "src/data/architecture.json", json.dumps(data, indent=2) + "\n"
    )
    return records


def _write_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def _write_bytes(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def _write_common_configs(
    *, output_dir: Path, site: DocsiteSite | None, architecture_enabled: bool
) -> None:
    _write_text(output_dir / "astro.config.mjs", _render_astro_config())
    _write_text(
        output_dir / "tsconfig.json",
        _render_tsconfig(architecture_enabled=architecture_enabled),
    )
    if site is not None:
        _write_text(
            output_dir / "package.json",
            _render_package_json(site, architecture_enabled=architecture_enabled),
        )
        _write_text(output_dir / "README.md", _render_readme(site))


def _write_common_assets(
    *,
    layouts_dir: Path,
    styles_dir: Path,
    public_dir: Path,
    architecture_enabled: bool,
) -> None:
    _write_text(
        layouts_dir / "DocLayout.astro",
        _render_doc_layout(architecture_enabled=architecture_enabled),
    )
    _write_text(
        styles_dir / "global.css",
        _render_global_css(architecture_enabled=architecture_enabled),
    )
    _write_bytes(public_dir / "favicon.ico", _render_favicon_bytes())

    fonts_dir = public_dir / "fonts"
    licenses_dir = fonts_dir / "licenses"
    licenses_dir.mkdir(parents=True, exist_ok=True)

    for filename in (
        "SourceSans3VF-Upright.ttf.woff2",
        "SourceSans3VF-Italic.ttf.woff2",
        "DMSerifDisplay-Regular.ttf",
        "DMSerifDisplay-Italic.ttf",
    ):
        _write_bytes(fonts_dir / filename, _render_font_bytes(filename))

    for filename in (
        "SourceSans3-LICENSE.md",
        "DMSerif-OFL.txt",
        "DMSerif-LICENSE.txt",
    ):
        _write_text(licenses_dir / filename, _render_font_license_text(filename))


def _load_site_from_existing(output_dir: Path) -> DocsiteSite | None:
    site_path = output_dir / "src" / "data" / "site.json"
    try:
        if not site_path.exists():
            return None
        payload = json.loads(site_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        title = payload.get("title")
        tagline = payload.get("tagline")
        scope_label = payload.get("scopeLabel")
        generated_at = (
            payload.get("generatedAt") or datetime.now(timezone.utc).isoformat()
        )
        source_dir = payload.get("sourceDir") or str(output_dir)
        topic_count = payload.get("topicCount") or 0
        if (
            not isinstance(title, str)
            or not isinstance(tagline, str)
            or not isinstance(scope_label, str)
        ):
            return None
        if not isinstance(generated_at, str) or not isinstance(source_dir, str):
            return None
        if not isinstance(topic_count, int):
            topic_count = 0
        return DocsiteSite(
            title=title,
            tagline=tagline,
            scope_label=scope_label,
            generated_at=generated_at,
            source_dir=source_dir,
            topic_count=topic_count,
        )
    except Exception:  # noqa: BLE001
        return None


def _render_index_metadata(index: CodeMapperIndex) -> list[str]:
    return _metadata_render_index_metadata(index)
