"""Magento module discovery, independent of app/code placement."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from tree_sitter_language_pack import get_parser

from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.contract import Finding
from chunkhound.domain_model.structure.files import select_files
from chunkhound.domain_model.structure.readers import _php
from chunkhound.domain_model.structure.readers._psr4 import PHPType, file_scopes
from chunkhound.domain_model.structure.readers._xml import Element, parse_xml
from chunkhound.domain_model.structure.schema import Span

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext


@dataclass(frozen=True)
class Module:
    path: str
    third_party: bool
    package: str | None


def is_vendor(path: str) -> bool:
    return "vendor" in PurePosixPath(path).parts


def read_xml(ctx: ReadContext, path: str, reader: str) -> tuple[Element, ...]:
    source = ctx.read(path)
    if source is None:
        return ()
    errors: list[Span] = []
    elements = parse_xml("\n".join(source.lines), path, reader, errors)
    if errors:
        repo = ctx.repository_of(path)
        error = errors[0]
        ctx.findings.append(
            Finding(
                kind="unresolved",
                subject=None,
                reason="unreadable_source",
                detail=None,
                citations=(
                    Citation(
                        repository=repo.key,
                        path=path,
                        start_line=error.start_line,
                        end_line=error.end_line,
                        commit=repo.commit,
                    ),
                ),
            )
        )
    return elements


def package_detail(ctx: ReadContext, module_path: str) -> str | None:
    path = f"{module_path}/composer.json"
    if not (ctx.project_root / path).is_file():
        return None
    source = ctx.read(path)
    if source is None:
        return None
    try:
        data = json.loads("\n".join(source.lines))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str):
        return None
    version = data.get("version")
    return name + (f" {version}" if isinstance(version, str) else "")


def find_modules(ctx: ReadContext, reader: str) -> tuple[Module, ...]:
    paths = tuple(
        path
        for path in select_files(ctx.project_root, ("**/module.xml",))
        if not is_vendor(path)
    )
    vendor_paths = set()
    for repo in ctx.repositories:
        vendor_root = ctx.project_root / repo.path / "vendor"
        if not vendor_root.is_dir():
            continue
        for path in select_files(
            vendor_root, ("*/*/etc/module.xml",), ignore_gitignore=True
        ):
            if len(PurePosixPath(path).parts) == 4:
                vendor_paths.add(
                    (vendor_root / path).relative_to(ctx.project_root).as_posix()
                )
    modules = []
    for path in sorted(set(paths) | set(vendor_paths)):
        if PurePosixPath(path).parent.name != "etc":
            continue
        root = PurePosixPath(path).parent.parent.as_posix()
        registration = f"{root}/registration.php"
        if not (ctx.project_root / registration).is_file():
            continue
        if ctx.read(registration) is None:
            continue
        if not any(
            child.name == "module"
            for element in read_xml(ctx, path, reader)
            for child in element.children
        ):
            continue
        modules.append(Module(root, is_vendor(root), package_detail(ctx, root)))
    return tuple(modules)


def module_name(ctx: ReadContext, module: Module, reader: str) -> str | None:
    return next(
        (
            child.attributes.get("name")
            for root in read_xml(ctx, f"{module.path}/etc/module.xml", reader)
            for child in root.children
            if child.name == "module"
        ),
        None,
    )


class ModuleResolver:
    """Resolve PHP declarations using module names or literal Composer mappings."""

    def __init__(
        self, ctx: ReadContext, modules: tuple[Module, ...], reader: str
    ) -> None:
        self.ctx = ctx
        self.files: dict[str, list[PHPType]] = {}
        self.mappings: list[tuple[str, str, str]] = []
        for module in modules:
            name = module_name(ctx, module, reader)
            mappings: list[tuple[str, str]] = []
            path = f"{module.path}/composer.json"
            if (ctx.project_root / path).is_file():
                source = ctx.read(path)
                try:
                    data = json.loads("\n".join(source.lines)) if source else {}
                except ValueError:
                    data = {}
                autoload = data.get("autoload", {}) if isinstance(data, dict) else {}
                psr4 = autoload.get("psr-4", {}) if isinstance(autoload, dict) else {}
                if isinstance(psr4, dict):
                    for prefix, directories in psr4.items():
                        for directory in (
                            directories
                            if isinstance(directories, list)
                            else [directories]
                        ):
                            if not isinstance(directory, str):
                                continue
                            base = PurePosixPath(module.path) / directory
                            if base.is_absolute() or ".." in base.parts:
                                continue
                            mappings.append((prefix, base.as_posix()))
            if not mappings and name:
                mappings.append((name.replace("_", "\\") + "\\", module.path))
            repo = ctx.repository_of(path).key
            self.mappings.extend((repo, prefix, base) for prefix, base in mappings)
        self.mappings.sort(key=lambda mapping: -len(mapping[1]))

    def load(self, path: str) -> list[PHPType]:
        if path not in self.files:
            source = self.ctx.read(path)
            self.files[path] = []
            if source:
                root = (
                    get_parser("php").parse("\n".join(source.lines).encode()).root_node
                )
                self.files[path] = [
                    PHPType(
                        _php.text(scope.node.child_by_field_name("name")),
                        path,
                        scope.node,
                        scope.namespace,
                        scope.imports,
                    )
                    for scope in file_scopes(path, root)
                    if scope.node.type
                    in {
                        "class_declaration",
                        "interface_declaration",
                        "trait_declaration",
                    }
                ]
        return self.files[path]

    def resolve(self, name: str, origin_path: str) -> PHPType | None:
        qualified = name.lstrip("\\")
        repository = self.ctx.repository_of(origin_path).key
        for repo, prefix, base in self.mappings:
            if repo != repository or not qualified.startswith(prefix):
                continue
            path = str(
                PurePosixPath(base)
                / (qualified[len(prefix) :].replace("\\", "/") + ".php")
            )
            if not (self.ctx.project_root / path).is_file():
                continue
            if self.ctx.repository_of(path).key != repository:
                continue
            for item in self.load(path):
                if item.qualified_name == qualified:
                    return item
        return None
