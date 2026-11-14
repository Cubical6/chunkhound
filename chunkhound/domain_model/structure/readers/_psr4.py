"""Literal PHP names and repository-local Composer PSR-4 lookup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from chunkhound.domain_model.structure.readers import _php

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext


@dataclass(frozen=True)
class PHPType:
    name: str
    path: str
    node: Node
    namespace: str
    imports: dict[str, str]

    def qualify(self, name: str) -> str:
        if name.startswith("\\"):
            return name.lstrip("\\")
        if name.startswith("namespace\\"):
            name = name.removeprefix("namespace\\")
        else:
            first, _, rest = name.partition("\\")
            if first in self.imports:
                return self.imports[first] + ("\\" + rest if rest else "")
        return "\\".join(part for part in (self.namespace, name) if part)

    @property
    def qualified_name(self) -> str:
        return "\\".join(part for part in (self.namespace, self.name) if part)


def _imports(node: Node) -> dict[str, str]:
    result: dict[str, str] = {}
    # Functions and constants do not participate in class-name resolution.
    if _php.text(node).startswith(("use function ", "use const ")):
        return result
    group = node.child_by_field_name("body")
    prefix = ""
    if group is not None:
        prefix = _php.text(node.named_children[0]).strip("\\") + "\\"
    for clause in (group or node).named_children:
        if clause.type != "namespace_use_clause":
            continue
        alias = clause.child_by_field_name("alias")
        target = prefix + _php.text(clause.named_children[0]).lstrip("\\")
        result[_php.text(alias) if alias else target.split("\\")[-1]] = target
    return result


def file_scopes(path: str, root: Node) -> list[PHPType]:
    """Name-resolution contexts for file-level code as well as class declarations."""
    result: list[PHPType] = []
    namespace = ""
    imports: dict[str, str] = {}
    for node in root.named_children:
        if node.type == "namespace_definition":
            namespace = _php.text(node.child_by_field_name("name"))
            imports = {}
            body = node.child_by_field_name("body")
            if body is not None:
                for scope in file_scopes(path, body):
                    result.append(
                        PHPType("", path, scope.node, namespace, scope.imports)
                    )
                continue
        elif node.type == "namespace_use_declaration":
            imports.update(_imports(node))
        else:
            result.append(PHPType("", path, node, namespace, imports))
    return result


def _types(path: str, root: Node) -> list[PHPType]:
    return [
        PHPType(
            _php.text(scope.node.child_by_field_name("name")),
            path,
            scope.node,
            scope.namespace,
            scope.imports,
        )
        for scope in file_scopes(path, root)
        if scope.node.type
        in {"class_declaration", "enum_declaration", "trait_declaration"}
    ]


class PSR4Resolver:
    def __init__(self, ctx: ReadContext, composer_paths: tuple[str, ...]) -> None:
        self.ctx = ctx
        self.files: dict[str, list[PHPType]] = {}
        self.mappings: list[tuple[str, str, str]] = []
        for path in sorted(composer_paths):
            source = ctx.read(path)
            if source is None:
                continue
            try:
                data = json.loads("\n".join(source.lines))
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            for section in ("autoload", "autoload-dev"):
                config = data.get(section, {})
                mappings = config.get("psr-4", {}) if isinstance(config, dict) else {}
                if not isinstance(mappings, dict):
                    continue
                for prefix, directories in mappings.items():
                    for directory in (
                        directories if isinstance(directories, list) else [directories]
                    ):
                        if not isinstance(directory, str):
                            continue
                        base = PurePosixPath(path).parent / directory
                        if base.is_absolute() or ".." in base.parts:
                            continue
                        self.mappings.append(
                            (ctx.repository_of(path).key, prefix, base.as_posix())
                        )
        # Longest prefix wins; preserve Composer's directory order for ties.
        self.mappings.sort(key=lambda m: -len(m[1]))

    def load(self, path: str) -> list[PHPType]:
        if path not in self.files:
            source = self.ctx.read(path)
            self.files[path] = (
                _types(
                    path,
                    get_parser("php")
                    .parse("\n".join(source.lines).encode("utf-8"))
                    .root_node,
                )
                if source
                else []
            )
        return self.files[path]

    def resolve(self, name: str, origin: PHPType) -> PHPType | None:
        qualified = origin.qualify(name)
        for item in self.load(origin.path):
            if item.qualified_name == qualified:
                return item
        repository = self.ctx.repository_of(origin.path).key
        for repo, prefix, base in self.mappings:
            if repo != repository or not qualified.startswith(prefix):
                continue
            suffix = qualified[len(prefix) :].replace("\\", "/") + ".php"
            path = (PurePosixPath(base) / suffix).as_posix()
            if not (self.ctx.project_root / path).is_file():
                continue
            if self.ctx.repository_of(path).key != repository:
                continue
            for item in self.load(path):
                if item.qualified_name == qualified:
                    return item
        return None
