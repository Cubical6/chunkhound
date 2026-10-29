"""Bind original topic paths to final pages and roll up unique shared files."""

import posixpath
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from chunkhound.autodoc.architecture.model import C4Model, CoveredElement
from chunkhound.autodoc.models import DocsitePage


class CoverageIndex:
    def __init__(
        self,
        model: C4Model,
        pages: list[DocsitePage],
        input_dir: Path,
        log_warning: Callable[[str], None] | None = None,
    ) -> None:
        root = input_dir.resolve()
        self._pages = {page.slug: page for page in pages}
        self._direct: dict[str, set[str]] = {}
        self._topics: dict[str, dict[str, set[str]]] = {}
        by_path = {
            Path(page.source_path).resolve(): page
            for page in pages
            if page.source_path is not None
        }
        self._system_id = model.system.id
        self._parents = {element.id: element.parent_id for element in model.elements}
        self._parents[model.system.id] = None
        self._files = {
            element.id: frozenset(posixpath.normpath(path) for path in element.files)
            for element in model.elements
        }
        for topic in model.topics:
            relative = PurePosixPath(topic.file)
            path = (root / relative).resolve()
            page = by_path.get(path) if path.is_relative_to(root) else None
            if page is None:
                if log_warning:
                    log_warning(
                        f"C4 topic {topic.file}: no generated page; skipping link."
                    )
                continue
            for cover in topic.covers:
                self._add_cover(cover, page.slug, log_warning)

    def _add_cover(
        self,
        cover: CoveredElement,
        slug: str,
        log_warning: Callable[[str], None] | None,
    ) -> None:
        if cover.element_id not in self._parents:
            if log_warning:
                log_warning(f"C4 cover: unknown element {cover.element_id}.")
            return
        shared = set(cover.files)
        if cover.element_id != self._system_id:
            shared.intersection_update(self._files[cover.element_id])
        if not shared:
            return
        self._direct.setdefault(slug, set()).add(cover.element_id)
        target: str | None = cover.element_id
        while target is not None:
            self._topics.setdefault(target, {}).setdefault(slug, set()).update(shared)
            target = self._parents[target]

    def topics_for(self, element_id: str) -> list[tuple[DocsitePage, frozenset[str]]]:
        topics = [
            (self._pages[slug], frozenset(files))
            for slug, files in self._topics.get(element_id, {}).items()
        ]
        topics.sort(key=lambda item: (-len(item[1]), item[0].title, item[0].slug))
        return topics

    def direct_elements_for(self, page: DocsitePage) -> list[str]:
        return sorted(self._direct.get(page.slug, ()))
