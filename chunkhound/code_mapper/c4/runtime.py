"""Discover runtime boundaries and typed storage evidence without an LLM.

Manifest paths are project-relative identity keys. Removed lock entries and
explicit tombstones reserve IDs; the pipeline persists removals in its lockfile.
"""

import ast
import json
import re
import shlex
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

# PyYAML is a runtime dependency; this project does not install its separate stubs.
import yaml  # type: ignore[import-untyped]
from yaml.nodes import (  # type: ignore[import-untyped]
    MappingNode,
    Node,
    ScalarNode,
    SequenceNode,
)

from chunkhound.code_mapper.c4.model import Citation, Marker
from chunkhound.utils.text import slugify_kebab

if sys.version_info >= (3, 11):
    import tomllib
else:
    # Installed conditionally on Python 3.10, absent in the 3.12 QA environment.
    import tomli as tomllib  # type: ignore[import-not-found]

_MANIFESTS = {"pyproject.toml", "package.json", "composer.json", "Cargo.toml"}
_PLACEHOLDERS = ("{{", "}}", "{%", "${")


@dataclass(frozen=True)
class RuntimeUnit:
    id: str
    name: str
    manifest: str
    root: str
    storage: bool
    markers: tuple[Marker, ...]
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class ManifestCandidate:
    manifest: str
    name: str
    line: int
    reason: str


@dataclass(frozen=True)
class StorageCandidate:
    key: str
    file: str
    line: int
    evidence: str


@dataclass(frozen=True)
class DependencyDecl:
    name: str
    manifest: str
    line: int


@dataclass
class RuntimeScan:
    system_id: str
    system_name: str
    containers: list[RuntimeUnit]
    uncertain: list[ManifestCandidate]
    storage: list[StorageCandidate]
    dependencies: list[DependencyDecl]
    container_of: dict[str, str]


def _slug(name: str) -> str:
    return slugify_kebab(name, ascii_only=True)


def assign_container_ids(
    names_by_manifest: Mapping[str, str],
    locked: Mapping[str, str],
    tombstones: Mapping[str, str],
) -> dict[str, str]:
    """Keep locked identities and reserve removed IDs before allocating new ones."""
    assigned = {path: locked[path] for path in names_by_manifest if path in locked}
    reserved = set(locked.values()) | set(tombstones.values())
    counts = Counter(_slug(name) for name in names_by_manifest.values())
    for path, name in sorted(names_by_manifest.items()):
        if path in assigned:
            continue
        slug = _slug(name)
        base = f"container:{slug}"
        if counts[slug] > 1 or base in reserved:
            parent = PurePosixPath(path).parent.as_posix()
            prefix = "" if parent == "." else f"{parent}-"
            base = f"container:{_slug(prefix + name)}"
        candidate = base
        suffix = 2
        while candidate in reserved:
            candidate = f"{base}-{suffix}"
            suffix += 1
        assigned[path] = candidate
        reserved.add(candidate)
    return assigned


def _key_line(text: str, key: str) -> int:
    pattern = rf'^\s*["\']?{re.escape(key)}["\']?\s*[:=]'
    return next(
        (i for i, line in enumerate(text.splitlines(), 1) if re.search(pattern, line)),
        1,
    )


@dataclass(frozen=True)
class _Manifest:
    path: str
    name: str
    line: int
    starts: bool


def _manifest(
    path: str, text: str, files: set[str]
) -> tuple[_Manifest | None, list[DependencyDecl]]:
    filename = PurePosixPath(path).name
    data = json.loads(text) if filename.endswith(".json") else tomllib.loads(text)
    if not isinstance(data, dict):
        return None, []
    if filename == "pyproject.toml":
        package = data.get("project", {})
        starts = bool(package.get("scripts"))
        dependency_names = [
            match.group(0)
            for value in package.get("dependencies", [])
            if (match := re.match(r"[\w.-]+", value))
        ]
    elif filename == "Cargo.toml":
        package = data.get("package", {})
        main = (PurePosixPath(path).parent / "src/main.rs").as_posix()
        starts = bool(data.get("bin")) or (
            package.get("autobins", True) is not False and main in files
        )
        dependency_names = list(data.get("dependencies", {}))
    else:
        package = data
        starts = bool(data.get("bin"))
        dependency_names = list(
            data.get("require" if filename == "composer.json" else "dependencies", {})
        )
    name = package.get("name")
    if not isinstance(name, str):
        return None, []
    dependencies = [
        DependencyDecl(name=dep, manifest=path, line=_dependency_line(text, dep))
        for dep in dependency_names
    ]
    return _Manifest(path, name, _key_line(text, "name"), starts), dependencies


def _dependency_line(text: str, name: str) -> int:
    # Handles inline arrays as well as JSON/TOML dependency tables.
    pattern = rf'["\']?{re.escape(name)}(?=[\s"\'\[<>=!~;:]|$)'
    return next(
        (i for i, line in enumerate(text.splitlines(), 1) if re.search(pattern, line)),
        1,
    )


def _path_annotation(node: ast.expr, paths: set[str], modules: set[str]) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return False
    if isinstance(node, ast.Name):
        return node.id in paths
    if not isinstance(node, ast.Attribute) or node.attr != "Path":
        return False
    return isinstance(node.value, ast.Name) and node.value.id in modules


def _python_storage(file: str, text: str) -> list[StorageCandidate]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    paths: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "pathlib":
            paths.update(a.asname or a.name for a in node.names if a.name == "Path")
        elif isinstance(node, ast.Import):
            modules.update(
                a.asname or a.name for a in node.names if a.name == "pathlib"
            )
    result = []
    lines = text.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if _path_annotation(node.annotation, paths, modules):
            result.append(
                StorageCandidate(
                    ast.unparse(node.target), file, node.lineno, lines[node.lineno - 1]
                )
            )
    return result


def _docker_storage(file: str, text: str) -> list[StorageCandidate]:
    result: list[StorageCandidate] = []
    for line, evidence in enumerate(text.splitlines(), 1):
        match = re.match(r"\s*VOLUME\s+(.+)", evidence, re.IGNORECASE)
        if match is None:
            continue
        value = match.group(1)
        keys = json.loads(value) if value.startswith("[") else shlex.split(value)
        result.extend(StorageCandidate(key, file, line, evidence) for key in keys)
    return result


def _yaml_mapping(node: Node | None) -> dict[str, Node]:
    if not isinstance(node, MappingNode):
        return {}
    return {
        key.value: value for key, value in node.value if isinstance(key, ScalarNode)
    }


def _mount_target(mount: Node) -> str | None:
    if isinstance(mount, ScalarNode):
        parts = mount.value.split(":")
        return cast(str, parts[1] if len(parts) > 1 else parts[0])
    target = _yaml_mapping(mount).get("target")
    return cast(str, target.value) if isinstance(target, ScalarNode) else None


def _service_storage(
    file: str, service: Node, lines: list[str]
) -> list[StorageCandidate]:
    mounts = _yaml_mapping(service).get("volumes")
    if not isinstance(mounts, SequenceNode):
        return []
    result = []
    for mount in mounts.value:
        target = _mount_target(mount)
        if target is not None:
            line = mount.start_mark.line + 1
            result.append(StorageCandidate(target, file, line, lines[line - 1]))
    return result


def _compose_storage(file: str, text: str) -> list[StorageCandidate]:
    root = _yaml_mapping(yaml.compose(text, Loader=yaml.SafeLoader))
    lines = text.splitlines()
    result = []
    volumes = root.get("volumes")
    if isinstance(volumes, MappingNode):
        for key, _ in volumes.value:
            if isinstance(key, ScalarNode):
                line = key.start_mark.line + 1
                result.append(StorageCandidate(key.value, file, line, lines[line - 1]))
    for service in _yaml_mapping(root.get("services")).values():
        result.extend(_service_storage(file, service, lines))
    return result


def _storage(file: str, text: str) -> list[StorageCandidate]:
    filename = PurePosixPath(file).name
    if filename == "Dockerfile":
        return _docker_storage(file, text)
    if filename in {
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
    }:
        return _compose_storage(file, text)
    if file.endswith(".py"):
        return _python_storage(file, text)
    return []


def _citation(target: str, file: str, line: int) -> Citation:
    return Citation(
        target=target,
        file=file,
        start_line=line,
        end_line=line,
        source="configuration",
        verified=True,
    )


def _discover(
    project_root: Path, files: set[str]
) -> tuple[list[_Manifest], list[DependencyDecl], list[StorageCandidate], list[str]]:
    manifests = []
    dependencies = []
    storage = []
    dockerfiles = []
    template_roots = set()
    for file in sorted(files):
        text = (project_root / file).read_text(encoding="utf-8", errors="replace")
        storage.extend(_storage(file, text))
        if PurePosixPath(file).name == "Dockerfile":
            dockerfiles.append(file)
        if PurePosixPath(file).name in _MANIFESTS:
            manifest, declarations = _manifest(file, text, files)
            if manifest is not None:
                if any(token in manifest.name for token in _PLACEHOLDERS):
                    template_roots.add(PurePosixPath(file).parent.as_posix())
                else:
                    manifests.append(manifest)
                    dependencies.extend(declarations)
    # Excluded package roots must not be resurrected by their Dockerfile.
    dockerfiles = [
        file
        for file in dockerfiles
        if PurePosixPath(file).parent.as_posix() not in template_roots
    ]
    return manifests, dependencies, storage, dockerfiles


def _runtime_unit(m: _Manifest, id: str, dockerfiles: list[str]) -> RuntimeUnit:
    root = PurePosixPath(m.path).parent.as_posix()
    citations = [_citation(id, m.path, m.line)]
    citations.extend(
        _citation(id, file, 1)
        for file in dockerfiles
        if PurePosixPath(file).parent.as_posix() == root and file != m.path
    )
    return RuntimeUnit(id, m.name, m.path, root, False, (), tuple(citations))


def _bind_files(files: set[str], containers: list[RuntimeUnit]) -> dict[str, str]:
    container_of = {}
    # Walk ancestors rather than comparing each file against every container.
    by_root = {c.root: c.id for c in containers}
    for file in sorted(files):
        for parent in PurePosixPath(file).parents:
            if parent.as_posix() in by_root:
                container_of[file] = by_root[parent.as_posix()]
                break
    return container_of


def scan_runtime(
    *,
    project_root: Path,
    scope_path: Path,
    files: Sequence[str],
    locked_containers: Mapping[str, str],
    tombstones: Mapping[str, str],
    accepted: Mapping[str, bool] = {},
) -> RuntimeScan:
    """Scan the supplied scope file list; never consult git or traverse beyond it."""
    file_set = set(files)
    manifests, dependencies, storage, dockerfiles = _discover(project_root, file_set)
    scope_root = scope_path.resolve().relative_to(project_root.resolve()).as_posix()
    system_name = next(
        (
            m.name
            for m in manifests
            if PurePosixPath(m.path).parent.as_posix() == scope_root
        ),
        scope_path.name,
    )
    roots_with_docker = {PurePosixPath(f).parent.as_posix() for f in dockerfiles}
    selected = [
        m
        for m in manifests
        if m.starts
        or accepted.get(m.path, False)
        or PurePosixPath(m.path).parent.as_posix() in roots_with_docker
    ]
    uncertain = [
        ManifestCandidate(m.path, m.name, m.line, "No standard runtime entrypoint")
        for m in manifests
        if m not in selected and m.path not in accepted
    ]
    # A Dockerfile in a named package is evidence for that package, not a second unit.
    manifest_roots = {PurePosixPath(m.path).parent.as_posix() for m in selected}
    for dockerfile in dockerfiles:
        parent = PurePosixPath(dockerfile).parent
        if parent.as_posix() not in manifest_roots:
            selected.append(
                _Manifest(dockerfile, (project_root / parent).name, 1, True)
            )
    ids = assign_container_ids(
        {m.path: m.name for m in selected}, locked_containers, tombstones
    )
    containers = [_runtime_unit(m, ids[m.path], dockerfiles) for m in selected]
    if not containers:
        provisional_id = assign_container_ids(
            {"": system_name}, locked_containers, tombstones
        )[""]
        containers.append(
            RuntimeUnit(
                provisional_id, system_name, "", scope_root, False, ("provisional",), ()
            )
        )
    container_of = _bind_files(file_set, containers)
    return RuntimeScan(
        f"systeem:{_slug(system_name)}",
        system_name,
        containers,
        uncertain,
        storage,
        dependencies,
        container_of,
    )
