"""Presentation identifiers; neutral producer identity never depends on these names."""

import re
import unicodedata
from collections import defaultdict

from chunkhound.autodoc.architecture.model import C4Model, Element, SoftwareSystem

# Keywords from the pinned LikeC4 1.60 grammar that cannot safely be bare IDs.
_RESERVED = frozenset(
    "specification element relationship deploymentNode tag color import from as "
    "model deployment views view dynamic extends of include exclude with where "
    "title description technology notation summary style metadata link navigateTo "
    "global styleId autoLayout direction rankSep nodeSep edgeSep group extend "
    "true false and or not is this it source target kind instance node notes "
    "order routing variant predicate opacity shape icon size padding textSize "
    "border multiple line head tail ast stylesheet deploymentView colorDefinitions "
    "iconColor iconSize iconPosition rank min max same new parallel step try alt "
    "else for in filter theme fontFamily fontWeight align bendPoint".split()
)


def _slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9_-]+", "-", ascii_name.lower()).strip("-") or "element"
    if not re.match(r"[a-z]", slug) or slug in _RESERVED:
        slug = "e-" + slug
    return slug


class LikeC4IdAllocator:
    def __init__(self, model: C4Model) -> None:
        self._local: dict[str, str] = {}
        self._fqns: dict[str, str] = {}
        self._parents = {element.id: element.parent_id for element in model.elements}
        self._parents[model.system.id] = None
        siblings: dict[str | None, list[SoftwareSystem | Element]] = defaultdict(list)
        siblings[None].append(model.system)
        for element in model.elements:
            siblings[element.parent_id].append(element)
        # LikeC4 resolves the first FQN segment against the unique descendants of a
        # `view ... of X` before the roots, so nested IDs must not repeat a root ID.
        roots = siblings.pop(None)
        self._allocate(roots, set())
        reserved = {self._local[element.id] for element in roots}
        for elements in siblings.values():
            self._allocate(elements, set(reserved))
        for element_id in self._local:
            self._build_fqn(element_id)

    def _allocate(
        self, elements: list[SoftwareSystem | Element], used: set[str]
    ) -> None:
        # Reserve natural names first so a suffix cannot steal another base slug.
        bases = {_slug(element.name) for element in elements}
        for sibling in sorted(elements, key=lambda item: item.id):
            base = _slug(sibling.name)
            slug = base
            suffix = 2
            while slug in used or (slug != base and slug in bases):
                slug = f"{base}-{suffix}"
                suffix += 1
            used.add(slug)
            self._local[sibling.id] = slug

    def _build_fqn(self, element_id: str) -> str:
        if element_id not in self._fqns:
            parent = self._parents[element_id]
            prefix = self._build_fqn(parent) + "." if parent is not None else ""
            self._fqns[element_id] = prefix + self._local[element_id]
        return self._fqns[element_id]

    def allocate(self, element: SoftwareSystem | Element) -> str:
        return self._local[element.id]

    def fqn(self, element_id: str) -> str:
        return self._fqns[element_id]
