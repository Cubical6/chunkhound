"""GraphQL entry points, input hints, and lowest-ranked API-shape claims."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from chunkhound.domain_model.identity import EmptyKeyError, key_segment
from chunkhound.domain_model.model import Citation
from chunkhound.domain_model.structure.anchors import anchor_id, hint, operation_hint
from chunkhound.domain_model.structure.contract import Anchor, Finding, Handler, Hint
from chunkhound.domain_model.structure.files import select_files
from chunkhound.domain_model.structure.readers import _php
from chunkhound.domain_model.structure.readers._magento import (
    ModuleResolver,
    find_modules,
)
from chunkhound.domain_model.structure.readers._psr4 import PHPType, PSR4Resolver
from chunkhound.domain_model.structure.schema import (
    Column,
    Constraint,
    Schema,
    Span,
    Table,
    TableClaims,
)
from chunkhound.domain_model.structure.translate import concept_term, translate

if TYPE_CHECKING:
    from chunkhound.domain_model.structure.extract import ReadContext


BUILTINS = {
    "all": "read",
    "find": "read",
    "first": "read",
    "paginate": "read",
    "create": "add",
    "update": "change",
    "upsert": "change",
    "delete": "remove",
}


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8") if node is not None and node.text else ""


def _child(node: Node, kind: str) -> Node | None:
    return next((n for n in node.named_children if n.type == kind), None)


def _name(node: Node) -> str:
    return _text(_child(node, "name"))


def _walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def _parse(source: bytes) -> Node:
    # Mask escapes at equal byte lengths: the grammar can otherwise mistake an
    # @method inside an escaped resolver string for a second directive.
    strings = rb'"""(?:\\"""|(?!""")[\s\S])*"""|"(?:\\.|[^"\\\r\n])*"'

    def mask(match: re.Match[bytes]) -> bytes:
        return re.sub(rb"\\[^\r\n]", lambda m: b"x" * len(m[0]), match[0])

    return get_parser("graphql").parse(re.sub(strings, mask, source)).root_node


def _string(node: Node | None, source: bytes) -> str | None:
    if node is None or node.type != "string_value":
        return None
    # The grammar reports local ERROR children for escaped namespaces. Only the
    # source slice is authoritative, including for block strings and Unicode.
    value = source[node.start_byte : node.end_byte].decode("utf-8")
    if value.startswith('"""') and value.endswith('"""'):
        lines = re.split(r"\r\n|[\r\n]", value[3:-3].replace('\\"""', '"""'))
        indent = min(
            (
                len(line) - len(line.lstrip(" \t"))
                for line in lines[1:]
                if line.strip(" \t")
            ),
            default=0,
        )
        lines = [lines[0], *(line[indent:] for line in lines[1:])]
        while lines and not lines[0].strip(" \t"):
            lines.pop(0)
        while lines and not lines[-1].strip(" \t"):
            lines.pop()
        return "\n".join(lines)
    escapes = {
        "\\": "\\",
        '"': '"',
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }

    def decode(match: re.Match[str]) -> str:
        escape = match[0][1:]
        if not escape.startswith("u"):
            return escapes[escape]
        codepoint = int(escape[1:5], 16)
        if len(escape) == 11:
            low = int(escape[7:], 16)
            return chr(0x10000 + ((codepoint - 0xD800) << 10) + low - 0xDC00)
        # Invalid Unicode escapes are preserved, not allowed to abort other fields.
        return match[0] if 0xD800 <= codepoint <= 0xDFFF else chr(codepoint)

    return re.sub(
        r"\\u[dD][89aAbB][0-9a-fA-F]{2}\\u[dD][c-fC-F][0-9a-fA-F]{2}|"
        r'\\(?:u[0-9a-fA-F]{4}|[\\"/bfnrt])',
        decode,
        value[1:-1],
    )


def _directives(node: Node) -> dict[str, Node]:
    container = _child(node, "directives")
    return {_name(d): d for d in container.named_children} if container else {}


def _argument(directive: Node, name: str) -> Node | None:
    arguments = _child(directive, "arguments")
    for argument in arguments.named_children if arguments else ():
        if _name(argument) == name:
            value = _child(argument, "value")
            return value.named_children[0] if value and value.named_children else None
    return None


def _type_name(node: Node) -> str:
    annotation = _child(node, "type")
    return (
        next((_text(n) for n in _walk(annotation) if n.type == "name"), "")
        if annotation
        else ""
    )


def _type_text(node: Node) -> str:
    return _text(_child(node, "type"))


def _type_key(name: str) -> str:
    try:
        return key_segment(concept_term(name, name))
    except EmptyKeyError:
        return ""


@dataclass(frozen=True)
class _Source:
    path: str
    node: Node

    @property
    def span(self) -> Span:
        return Span(
            path=self.path,
            start_line=self.node.start_point.row + 1,
            end_line=self.node.end_point.row + 1,
            reader="graphql",
        )

    def citation(self, ctx: ReadContext) -> Citation:
        repo = ctx.repository_of(self.path)
        return Citation(
            repository=repo.key,
            path=self.path,
            commit=repo.commit,
            start_line=self.span.start_line,
            end_line=self.span.end_line,
        )


@dataclass
class _Type:
    source: _Source
    fields: list[_Source] = field(default_factory=list)


class GraphQLReader:
    name = "graphql"
    patterns: tuple[str, ...] = ("**/*.graphql", "**/*.graphqls", "**/*.gql")

    def read(self, ctx: ReadContext) -> None:
        _GraphQL(ctx).read()


class _GraphQL:
    def __init__(self, ctx: ReadContext) -> None:
        self.ctx = ctx
        self.modules = find_modules(ctx, "graphql")
        self.module_resolver = ModuleResolver(ctx, self.modules, "graphql")
        self.psr4 = PSR4Resolver(
            ctx, select_files(ctx.project_root, ("**/composer.json",))
        )
        self.sources: dict[str, bytes] = {}
        self.objects: dict[tuple[str, str], _Type] = {}
        self.inputs: dict[tuple[str, str], _Type] = {}
        self.enums: dict[tuple[str, str], tuple[str, ...]] = {}
        self.scalars: dict[str, set[str]] = {}
        self.explicit_roots: set[str] = set()
        self.magento_repositories = {
            ctx.repository_of(module.path + "/registration.php").key
            for module in self.modules
        }
        self.roots = {
            repo.key: {
                "Query": "query",
                "Mutation": "mutation",
                "Subscription": "subscription",
            }
            for repo in ctx.repositories
        }

    def read(self) -> None:
        for path in self.ctx.paths:
            if {"vendor", "node_modules"} & set(PurePosixPath(path).parts):
                continue
            containing = sorted(
                (m for m in self.modules if PurePosixPath(path).is_relative_to(m.path)),
                key=lambda m: -len(PurePosixPath(m.path).parts),
            )
            repo = self.ctx.repository_of(path)
            if repo.key in self.magento_repositories and not any(
                not m.third_party for m in containing
            ):
                continue
            try:
                self.read_document(path)
            except Exception:
                self.ctx.findings.append(
                    Finding(
                        kind="unresolved",
                        subject=None,
                        reason="unreadable_source",
                        detail="graphql",
                        citations=(
                            Citation(
                                repository=repo.key,
                                path=path,
                                start_line=1,
                                end_line=1,
                                commit=repo.commit,
                            ),
                        ),
                    )
                )
        for (repo_key, name), entry in self.objects.items():
            method = self.roots[repo_key].get(name)
            if method:
                for field_source in entry.fields:
                    self.anchor(repo_key, name, method, field_source)
        self.facts()

    def read_document(self, path: str) -> None:
        source = self.ctx.read(path)
        if source is None:
            return
        repo = self.ctx.repository_of(path).key
        self.sources[path] = "\n".join(source.lines).encode()
        root = _parse(self.sources[path])
        nodes = list(_walk(root))
        # The grammar also wraps all but the last operation in an extension in
        # ERROR, while still parsing each complete root declaration correctly.
        if any(
            n.is_missing
            or (
                n.type == "ERROR"
                and not (
                    n.named_children
                    and all(
                        c.type == "root_operation_type_definition"
                        for c in n.named_children
                    )
                )
            )
            for n in nodes
        ):
            raise ValueError("Invalid GraphQL document")
        for node in nodes:
            if node.type == "root_operation_type_definition":
                if repo not in self.explicit_roots:
                    self.roots[repo].clear()
                    self.explicit_roots.add(repo)
                self.roots[repo][_text(_child(node, "named_type"))] = _text(
                    _child(node, "operation_type")
                )
            elif node.type in {
                "object_type_definition",
                "object_type_extension",
                "input_object_type_definition",
                "input_object_type_extension",
            }:
                inputs = node.type.startswith("input_")
                registry = self.inputs if inputs else self.objects
                entry = registry.setdefault(
                    (repo, _name(node)), _Type(_Source(path, node))
                )
                fields = _child(
                    node,
                    "input_fields_definition" if inputs else "fields_definition",
                )
                if fields:
                    entry.fields.extend(
                        _Source(path, f)
                        for f in fields.named_children
                        if f.type in {"field_definition", "input_value_definition"}
                    )
            elif node.type in {"enum_type_definition", "enum_type_extension"}:
                values = tuple(_text(n) for n in _walk(node) if n.type == "enum_value")
                key = (repo, _name(node))
                self.enums[key] = (*self.enums.get(key, ()), *values)
            elif node.type == "scalar_type_definition":
                self.scalars.setdefault(repo, set()).add(_name(node))

    def locate(self, name: str, source: _Source, magento: bool) -> PHPType | None:
        if magento:
            return self.module_resolver.resolve(name, source.path)
        origin = PHPType("", source.path, source.node, "", {})
        return self.psr4.resolve("\\" + name.lstrip("\\"), origin)

    def method(
        self,
        item: PHPType,
        name: str,
        magento: bool,
        seen: frozenset[str] = frozenset(),
    ) -> tuple[PHPType, Node] | None:
        identity = item.qualified_name.casefold()
        if identity in seen:
            return None
        seen = seen | {identity}
        body = item.node.child_by_field_name("body")
        references: list[Node] = []
        for member in body.named_children if body else ():
            if (
                member.type == "method_declaration"
                and _php.text(member.child_by_field_name("name")).casefold()
                == name.casefold()
            ):
                return item, member
            if member.type == "use_declaration":
                references.extend(
                    n
                    for n in member.named_children
                    if n.type in {"name", "qualified_name", "relative_name"}
                )
        references.extend(
            n
            for clause in item.node.named_children
            if clause.type == "base_clause"
            for n in clause.named_children
        )
        for reference in references:
            parent = (
                self.module_resolver.resolve(
                    item.qualify(_php.text(reference)), item.path
                )
                if magento
                else self.psr4.resolve(_php.text(reference), item)
            )
            found = self.method(parent, name, magento, seen) if parent else None
            if found:
                return found
        return None

    def anchor(self, repo: str, root: str, method: str, source: _Source) -> None:
        citation = source.citation(self.ctx)
        node = source.node
        directives = _directives(node)
        hints = list(operation_hint(method, citation))
        handler = None
        builtin = next((d for d in directives if d in BUILTINS), None)
        symbol = None
        magento = "resolver" in directives
        if magento:
            name = _string(
                _argument(directives["resolver"], "class"), self.sources[source.path]
            )
            symbol = f"{name}@resolve" if name else None
        elif "field" in directives:
            name = _string(
                _argument(directives["field"], "resolver"), self.sources[source.path]
            )
            symbol = (
                name if name and "@" in name else f"{name}@__invoke" if name else None
            )
        elif builtin:
            handler = Handler(symbol="@" + builtin, citation=None)
            hints = [hint("operation", citation, value=BUILTINS[builtin])]
            model = _string(
                _argument(directives[builtin], "model"), self.sources[source.path]
            )
            if not model:
                model = _type_name(node)
            if model:
                model = model.lstrip("\\")
                if "\\" not in model:
                    model = "App\\Models\\" + model
                hints.append(hint("model", citation, name=model))
        elif method in {"query", "mutation"}:
            directory = "Queries" if method == "query" else "Mutations"
            field_name = _name(node)
            name = (
                f"App\\GraphQL\\{directory}\\{field_name[:1].upper() + field_name[1:]}"
            )
            if self.locate(name, source, False):
                symbol = name + "@__invoke"
        if symbol:
            name, _, member = symbol.partition("@")
            if not magento and "\\" not in name and method in {"query", "mutation"}:
                directory = "Queries" if method == "query" else "Mutations"
                name = f"App\\GraphQL\\{directory}\\{name}"
            item = self.locate(name, source, magento)
            found = self.method(item, member, magento) if item else None
            handler = Handler(
                symbol=symbol,
                citation=_Source(found[0].path, found[1]).citation(self.ctx)
                if found
                else None,
            )
        path = f"{root}.{_name(node)}"
        aid = anchor_id(repo, "graphql", method, path)
        if handler is None or (
            handler.citation is None and not handler.symbol.startswith("@")
        ):
            self.ctx.findings.append(
                Finding(
                    kind="unresolved",
                    subject=aid,
                    reason="handler_not_found",
                    detail=symbol,
                    citations=(citation,),
                )
            )
        arguments = _child(node, "arguments_definition")
        for argument in arguments.named_children if arguments else ():
            if argument.type == "input_value_definition":
                hints.extend(self.input_hints(repo, _Source(source.path, argument)))
        self.ctx.anchors.append(
            Anchor(
                id=aid,
                repository=repo,
                kind="graphql",
                method=method,
                path=path,
                handler=handler,
                source="graphql",
                citations=(citation,),
                hints=tuple(hints),
            )
        )

    def rules(self, source: _Source) -> str | None:
        directive = _directives(source.node).get("rules")
        apply = _argument(directive, "apply") if directive else None
        return (
            self.sources[source.path][apply.start_byte : apply.end_byte].decode("utf-8")
            if apply is not None and apply.type == "list_value"
            else None
        )

    def enum_hint(self, repo: str, source: _Source) -> list[Hint]:
        name = _type_name(source.node)
        values = self.enums.get((repo, name))
        return (
            [hint("enum", source.citation(self.ctx), name=name, values=values)]
            if values is not None
            else []
        )

    def input_hints(self, repo: str, source: _Source) -> list[Hint]:
        result = self.enum_hint(repo, source)
        name = _type_name(source.node)
        entry = self.inputs.get((repo, name))
        rules = self.rules(source)
        if entry is None:
            scalars = {"ID", "String", "Int", "Float", "Boolean"} | self.scalars.get(
                repo, set()
            )
            if name in scalars or (repo, name) in self.enums:
                result.append(
                    hint(
                        "input_rule",
                        source.citation(self.ctx),
                        name=_name(source.node),
                        value=rules or _type_text(source.node),
                    )
                )
            return result
        result.append(hint("input_type", source.citation(self.ctx), name=name))
        for field_source in entry.fields:
            node = field_source.node
            citation = field_source.citation(self.ctx)
            result.append(
                hint(
                    "input_rule",
                    citation,
                    name=_name(node),
                    value=self.rules(field_source) or _type_text(node),
                )
            )
            result.extend(self.enum_hint(repo, field_source))
            nested = _type_name(node)
            if (repo, nested) in self.inputs:
                result.append(hint("input_type", citation, name=nested))
        return result

    def facts(self) -> None:
        # Reuse the storage translation (and its concept_term derivation) rather
        # than guessing plural forms or reimplementing rank/model association.
        model, _, _ = translate(self.ctx.schemas, self.ctx.repository_of)
        terms = {c.id: c.term for c in model.concepts}
        links = {
            (f.repository, key_segment(terms[f.identifies])): f
            for f in model.fact_types
            if f.identifies in terms
        }
        objects = {
            key: entry
            for key, entry in self.objects.items()
            if key[1] not in self.roots[key[0]]
        }
        storage_keys: dict[tuple[str, str], str] = {}
        role_names = {(r.fact_type, r.name) for r in model.roles}
        for fact in links.values():
            # The translated fact's first citation identifies the winning table,
            # including rename history; do not borrow a lower source's key.
            citation = fact.citations[0]
            for schema in self.ctx.schemas:
                table = schema.tables.get(fact.name)
                if schema.repository != fact.repository or table is None:
                    continue
                origin = (table.origin or (table.defined_at,))[0]
                if (origin.path, origin.start_line, origin.end_line) != (
                    citation.path,
                    citation.start_line,
                    citation.end_line,
                ):
                    continue
                primary = next(
                    (c for c in table.constraints if c.kind == "primary"), None
                )
                if (
                    primary
                    and len(primary.columns) == 1
                    and (fact.id, primary.columns[0]) in role_names
                ):
                    storage_keys[fact.repository, fact.name] = primary.columns[0]
                break
        keyed: dict[tuple[str, str], tuple[str, str]] = {}
        for key, entry in objects.items():
            repo, name = key
            if not _type_key(name):
                continue
            linked_fact = links.get((repo, _type_key(name)))
            if linked_fact:
                column = storage_keys.get((repo, linked_fact.name))
                if column:
                    keyed[key] = (linked_fact.name, column)
            elif any(
                _name(s.node) == "id"
                and _type_name(s.node) == "ID"
                and "[" not in _type_text(s.node)
                for s in entry.fields
            ):
                keyed[key] = (name, "id")
        schemas: dict[str, Schema] = {}
        for (repo, name), entry in objects.items():
            schema = schemas.setdefault(repo, Schema("graphql", repo))
            linked_fact = links.get((repo, _type_key(name)))
            linked = linked_fact.name if linked_fact else None
            columns = []
            constraints = []
            scalars = {"ID", "String", "Int", "Float", "Boolean"} | self.scalars.get(
                repo, set()
            )
            for source in entry.fields:
                node = source.node
                field_name = _name(node)
                typename = _type_name(node)
                type_text = _type_text(node)
                target = (repo, typename)
                foreign = keyed.get(target) if "[" not in type_text else None
                scalar_or_enum = typename in scalars or target in self.enums
                if linked and (not scalar_or_enum or "[" in type_text):
                    continue
                if not linked and not scalar_or_enum and not foreign:
                    continue
                span = source.span
                columns.append(
                    Column(
                        name=field_name,
                        datatype=type_text.replace("!", ""),
                        mandatory=type_text.rstrip().endswith("!"),
                        origin=(span,),
                        defined_at=span,
                    )
                )
                if (
                    not linked
                    and field_name == "id"
                    and typename == "ID"
                    and "[" not in type_text
                ):
                    constraints.append(
                        Constraint(kind="primary", columns=(field_name,), spans=(span,))
                    )
                if not linked and foreign:
                    constraints.append(
                        Constraint(
                            kind="foreign",
                            columns=(field_name,),
                            ref_table=foreign[0],
                            ref_columns=(foreign[1],),
                            spans=(span,),
                        )
                    )
                if target in self.enums:
                    constraints.append(
                        Constraint(
                            kind="value",
                            columns=(field_name,),
                            allowed_values=self.enums[target],
                            spans=(span,),
                        )
                    )
            if linked:
                schema.claims.append(
                    TableClaims(
                        table=linked,
                        span=entry.source.span,
                        columns=tuple(columns),
                        constraints=tuple(constraints),
                    )
                )
            else:
                schema.create_table(
                    Table(
                        name=name,
                        columns=tuple(columns),
                        constraints=tuple(constraints),
                        defined_at=entry.source.span,
                    )
                )
        self.ctx.schemas.extend(schemas.values())
