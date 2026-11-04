"""One deterministic group per directory of each container, derived from paths.

File identities (Group.files) are project-relative POSIX paths. Group IDs, names
and prefixes are relative to the explicit runtime root, which may be '.' or a
provisional scope root. Files belong only to the group of their own directory.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Group:
    id: str
    container: str
    name: str
    prefix: str
    files: tuple[str, ...]


def build_groups(
    *,
    files: Sequence[str],
    container_of: Mapping[str, str],
    container_roots: Mapping[str, str],
    container_names: Mapping[str, str],
) -> list[Group]:
    """Group files by directory; the root group ('.') takes the container's name."""
    members: dict[tuple[str, str], list[str]] = defaultdict(list)
    for file in sorted(set(files)):
        container = container_of[file]
        parent = PurePosixPath(file).parent
        directory = parent.relative_to(container_roots[container]).as_posix()
        members[container, directory].append(file)
    return [
        Group(
            f"{container}/{directory}",
            container,
            container_names[container] if directory == "." else directory,
            directory,
            tuple(owned),
        )
        for (container, directory), owned in sorted(members.items())
    ]
