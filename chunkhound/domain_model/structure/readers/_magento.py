"""Magento module discovery, independent of app/code placement."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from chunkhound.domain_model.structure.files import select_files
from chunkhound.domain_model.structure.readers._xml import Element, parse_xml

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
    return parse_xml("\n".join(source.lines), path, reader) if source else ()


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
