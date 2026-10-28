"""Disk-only static references, retaining filtered evidence without a ceiling."""

import ast
import asyncio
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from chunkhound.code_mapper.c4.codeboarding import (
    SourceInspector,
    infer_bases_from_line,
)
from chunkhound.code_mapper.c4.model import Reference, ReferenceKind, ReferenceStatus
from chunkhound.core.detection.language_detector import detect_language
from chunkhound.core.types.common import Language
from chunkhound.parsers.parser_factory import ParserFactory
from chunkhound.services.research.shared.import_context import ImportContextService

_JS = frozenset({Language.JAVASCRIPT, Language.JSX, Language.TYPESCRIPT, Language.TSX})
_INSPECTED = _JS | {Language.PYTHON, Language.PHP}
_MODULE = re.compile(r"""(?:from\s*|require\s*\(\s*|import\s*)['"]([^'"]+)['"]""")


@dataclass(frozen=True)
class ReferenceScan:
    references: list[Reference]
    imports_only_files: frozenset[str]
    external_sites: dict[str, list[tuple[str, int]]]


@dataclass(frozen=True)
class _Import:
    text: str
    line: int
    start: int
    end: int


@dataclass(frozen=True)
class _Binding:
    target: str
    status: ReferenceStatus


def _python_import(text: str) -> ast.Import | ast.ImportFrom | None:
    try:
        node = ast.parse(text.strip()).body[0]
    except (SyntaxError, IndexError):
        return None
    return node if isinstance(node, (ast.Import, ast.ImportFrom)) else None


def bound_names(language: Language, import_text: str) -> list[str]:
    """Names introduced by an import, not the symbols on its remote side."""
    if language == Language.PYTHON:
        node = _python_import(import_text)
        if node is None:
            return []
        return [
            alias.asname
            or (
                alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name
            )
            for alias in node.names
            if alias.name != "*"
        ]
    if language in _JS:
        return _js_bound_names(import_text)
    if language == Language.PHP:
        match = re.match(r"\s*use\s+(?:(?:function|const)\s+)?(.+?);?\s*$", import_text)
        if match:
            return [
                part.strip().split()[-1].rsplit("\\", 1)[-1]
                for part in match[1].rstrip(";").split(",")
            ]
    return []


def _js_bound_names(text: str) -> list[str]:
    # A re-export introduces no local callable binding.
    if text.lstrip().startswith("export"):
        return []
    match = re.match(r"\s*import\s+(?:type\s+)?(.+?)\s+from\b", text, re.DOTALL)
    if match is None:
        return []
    clause = match[1].strip()
    names = []
    default = re.match(r"^([\w$]+)(?:\s*,|$)", clause)
    if default:
        names.append(default[1])
    namespace = re.search(r"\*\s+as\s+([\w$]+)", clause)
    if namespace:
        names.append(namespace[1])
    named = re.search(r"\{(.*?)\}", clause, re.DOTALL)
    if named:
        for item in named[1].split(","):
            words = item.strip().split()
            if words:
                names.append(words[-1])
    return names


def package_root(language: Language, import_text: str) -> str | None:
    """Return an external package key; relative and Python stdlib imports have none."""
    if language == Language.PYTHON:
        node = _python_import(import_text)
        if node is None or (isinstance(node, ast.ImportFrom) and node.level):
            return None
        module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
        root = (module or "").split(".")[0]
        return root if root and root not in sys.stdlib_module_names else None
    if language in _JS:
        return _js_package_root(import_text)
    if language == Language.PHP:
        match = re.match(r"\s*use\s+(?:(?:function|const)\s+)?([\w\\]+)", import_text)
        if match:
            return "\\".join(match[1].lstrip("\\").split("\\")[:2])
    return None


def _js_package_root(text: str) -> str | None:
    match = _MODULE.search(text)
    if match is None or match[1].startswith((".", "/", "node:")):
        return None
    parts = match[1].split("/")
    return "/".join(parts[:2]) if parts[0].startswith("@") else parts[0]


def _import_parts(language: Language, text: str) -> list[str]:
    """Resolve each Python binding independently so multi-imports cannot cross-link."""
    node = _python_import(text) if language == Language.PYTHON else None
    if node is not None:
        parts = []
        for alias in node.names:
            cloned = ast.alias(name=alias.name, asname=alias.asname)
            statement = (
                ast.Import(names=[cloned])
                if isinstance(node, ast.Import)
                else ast.ImportFrom(
                    module=node.module, names=[cloned], level=node.level
                )
            )
            parts.append(ast.unparse(statement))
        return parts
    if language == Language.GO and "(" in text:
        return ["import " + value for value in re.findall(r'"[^"\n]+"', text)]
    return [text]


def _locate_imports(content: str, texts: list[str]) -> list[_Import]:
    sites = []
    cursor = 0
    for text in texts:
        start = content.find(text, cursor)
        if start < 0:
            logger.debug("Import text not found in source: {}", text)
            continue
        end = start + len(text)
        sites.append(_Import(text, content.count("\n", 0, start) + 1, start, end))
        cursor = end
    return sites


def _js_ast_imports(content: str, tree: Any) -> list[_Import]:
    """Read JS-family import syntax absent from the shared IMPORT concept."""
    if tree is None:
        return []
    raw = content.encode("utf-8")
    sites = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "import_statement" or (
            node.type == "export_statement"
            and node.child_by_field_name("source") is not None
        ):
            start = len(raw[: node.start_byte].decode("utf-8"))
            text = raw[node.start_byte : node.end_byte].decode("utf-8")
            sites.append(
                _Import(text, node.start_point.row + 1, start, start + len(text))
            )
            continue
        stack.extend(reversed(node.named_children))
    return sites


def _type_checking_lines(content: str) -> set[int]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        ):
            for statement in node.body:
                lines.update(
                    range(
                        statement.lineno, (statement.end_lineno or statement.lineno) + 1
                    )
                )
    return lines


def _status(
    language: Language,
    site: _Import,
    names: list[str],
    body: str,
    type_lines: set[int],
    path: Path,
) -> ReferenceStatus:
    if site.line in type_lines or re.match(r"\s*import\s+type\b", site.text):
        return "type_only"
    if path.name in {"__init__.py", "index.ts"} or site.text.lstrip().startswith(
        "export"
    ):
        return "counts"
    if language not in _INSPECTED or not names:
        return "counts"
    return (
        "counts"
        if any(
            re.search(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", body)
            for name in names
        )
        else "unused"
    )


def _reference(
    source: str, line: int, target: str, kind: ReferenceKind, status: ReferenceStatus
) -> Reference:
    return Reference.model_validate(
        {
            "relation": None,
            "from": source,
            "line": line,
            "to": target,
            "kind": kind,
            "status": status,
        }
    )


@dataclass(frozen=True)
class _Source:
    path: Path
    relative: str
    language: Language
    content: str
    sites: list[_Import]


def _resolve_targets(
    source: _Source,
    site: _Import,
    part: str,
    mapping: Any,
    root: Path,
    external_sites: dict[str, list[tuple[str, int]]],
) -> list[str]:
    # The same mapping entry point as ImportResolverService, per statement so
    # each binding retains its own target and evidence location.
    try:
        paths = mapping.resolve_import_paths(part, root, source.path)
    except Exception as exc:
        logger.debug(
            "Cannot resolve import at {}:{}: {}", source.relative, site.line, exc
        )
        return []
    targets = list(
        dict.fromkeys(
            p.resolve().relative_to(root).as_posix()
            for p in paths
            if p.resolve().is_relative_to(root)
        )
    )
    if targets:
        return targets
    package = package_root(source.language, part)
    if package is None:
        return []
    location = (source.relative, site.line)
    locations = external_sites.setdefault(package, [])
    if location not in locations:
        locations.append(location)
    return ["package:" + package]


def _import_references(
    source: _Source,
    mapping: Any,
    root: Path,
    external_sites: dict[str, list[tuple[str, int]]],
) -> tuple[list[Reference], dict[str, _Binding]]:
    body = source.content
    for site in reversed(source.sites):
        body = body[: site.start] + " " * (site.end - site.start) + body[site.end :]
    type_lines = (
        _type_checking_lines(source.content)
        if source.language == Language.PYTHON
        else set()
    )
    references = []
    bindings = {}
    for site in source.sites:
        for part in _import_parts(source.language, site.text):
            names = bound_names(source.language, part)
            status = _status(
                source.language, site, names, body, type_lines, source.path
            )
            targets = _resolve_targets(
                source, site, part, mapping, root, external_sites
            )
            for target in targets:
                references.append(
                    _reference(source.relative, site.line, target, "import", status)
                )
            if len(targets) == 1:
                bindings.update({name: _Binding(targets[0], status) for name in names})
    return references, bindings


def _call_binding(
    inspector: SourceInspector,
    path: Path,
    line: int,
    column: int,
    source_line: str,
    bindings: dict[str, _Binding],
) -> _Binding | None:
    name = inspector.identifier_at(path, line - 1, column - 1)
    # Inspector positions name the member in `module.call()`. Only a simple
    # imported receiver can bind it; `unknown().call()` must not be guessed.
    prefix = source_line.encode("utf-16-le")[: (column - 1) * 2].decode("utf-16-le")
    receiver = re.search(r"([\w$]+)(?:(?:\.|::)[\w$]+)*(?:\.|::)\s*$", prefix)
    if receiver:
        return bindings.get(receiver[1])
    if prefix.rstrip().endswith((".", "::")):
        return None
    return bindings.get(name) if name else None


def _usage_references(
    inspector: SourceInspector,
    path: Path,
    relative: str,
    language: Language,
    content: str,
    bindings: dict[str, _Binding],
) -> list[Reference]:
    lines = content.splitlines()
    references = []
    for site in inspector.find_call_sites(path):
        binding = _call_binding(
            inspector, path, site.line, site.column, lines[site.line - 1], bindings
        )
        if binding:
            references.append(
                _reference(relative, site.line, binding.target, "call", binding.status)
            )
    for line, bases in _bases_by_line(inspector, path, language, lines):
        for base in bases:
            name = re.split(r"[.\[]", base)[0]
            binding = bindings.get(name)
            if binding:
                references.append(
                    _reference(
                        relative, line, binding.target, "inherit", binding.status
                    )
                )
    return references


def _bases_by_line(
    inspector: SourceInspector, path: Path, language: Language, lines: list[str]
) -> list[tuple[int, list[str]]]:
    if language == Language.PYTHON:
        return [(i, infer_bases_from_line(line)) for i, line in enumerate(lines, 1)]
    result = []
    cursor = 0
    for name, bases in inspector.find_type_bases(path):
        pattern = re.compile(r"\b(?:class|interface)\s+" + re.escape(name) + r"\b")
        for index in range(cursor, len(lines)):
            if pattern.search(lines[index]):
                result.append((index + 1, bases))
                cursor = index + 1
                break
    return result


class _Scanner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.factory = ParserFactory()
        self.imports = ImportContextService(self.factory)
        self.inspector = SourceInspector()
        self.external_sites: dict[str, list[tuple[str, int]]] = {}

    def scan_file(self, relative: str) -> tuple[list[Reference], bool]:
        path = self.root / relative
        content = path.read_text(encoding="utf-8")
        language = detect_language(path)
        parser: Any = self.factory.create_parser_for_file(path)
        texts = self.imports.get_file_imports(str(path), content)
        tree = None
        try:
            if language in _INSPECTED:
                tree = parser.engine.parse_to_ast(content)
        except Exception as exc:
            logger.debug("Cannot parse {} for usage analysis: {}", relative, exc)
        sites = (
            _js_ast_imports(content, tree)
            if not texts and language in _JS
            else _locate_imports(content, texts)
        )
        mapping = getattr(getattr(parser, "extractor", None), "mapping", None)
        if mapping is None:
            return [], False
        source = _Source(path, relative, language, content, sites)
        references, bindings = _import_references(
            source, mapping, self.root, self.external_sites
        )
        if language not in _INSPECTED:
            return references, True
        try:
            if tree is None or tree.root_node.has_error:
                logger.debug("Skipping usage analysis of unparsable file {}", relative)
                return references, bool(sites)
            references.extend(
                _usage_references(
                    self.inspector, path, relative, language, content, bindings
                )
            )
        except Exception as exc:
            logger.debug("Skipping usage analysis of {}: {}", relative, exc)
            return references, bool(sites)
        return references, False


def _scan_references(project_root: Path, files: Sequence[str]) -> ReferenceScan:
    scanner = _Scanner(project_root.resolve())
    references = []
    imports_only = set()
    for relative in sorted(set(files)):
        try:
            found, limited = scanner.scan_file(relative)
        except Exception as exc:
            logger.debug("Skipping static analysis of {}: {}", relative, exc)
            continue
        references.extend(found)
        if limited:
            imports_only.add(relative)
    references.sort(key=lambda r: (r.from_file, r.line, r.to, r.kind, r.status))
    return ReferenceScan(references, frozenset(imports_only), scanner.external_sites)


async def scan_references(*, project_root: Path, files: Sequence[str]) -> ReferenceScan:
    """Analyze all supplied source files off the event loop, without a database."""
    return await asyncio.to_thread(_scan_references, project_root, files)
