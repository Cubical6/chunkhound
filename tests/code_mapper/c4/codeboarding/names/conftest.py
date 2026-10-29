# Copied from CodeBoarding (https://github.com/CodeBoarding/CodeBoarding) commit 13adc4a0, MIT License, Copyright (c) 2025 CodeBoarding. See LICENSE in this directory.
# Source: tests/static_analyzer/names/conftest.py; license: chunkhound/code_mapper/c4/codeboarding/LICENSE (repository root).
# Changes: imports point at chunkhound.code_mapper.c4.codeboarding.names.
# Changes: the call-graph helper graph_from_layout was left out.
"""Builders shared by the names tests: units straight from qualified names, no engine."""

from pathlib import Path

from chunkhound.code_mapper.c4.codeboarding.names import ComponentRule, ScopeSpec, TreeSpec, Trie, Unit
from chunkhound.code_mapper.c4.codeboarding.names.inventory import TrieNode


def unit(file_path: str, *names: str, language: str = "python", project: tuple[str, ...] | None = None) -> Unit:
    """A unit positioned by its path, the way the inventory positions a file under the repository root."""
    relative = Path(file_path)
    position = () if relative.parent.parts == (".",) else relative.parent.parts
    return Unit(file_path, language, tuple(sorted(names)), position, position + (relative.name,), project)


def units_from_layout(layout: dict[str, list[str]], language: str = "python") -> list[Unit]:
    """``{file_path: [qualified names]}`` -> units, sorted the way the inventory sorts them."""
    return [unit(path, *names, language=language) for path, names in sorted(layout.items())]


def scope_of(spec: TreeSpec, scope_id: str) -> ScopeSpec:
    scope = spec.scope(scope_id)
    assert scope is not None, f"scope {scope_id!r} was not drafted"
    return scope


def rule_of(scope: ScopeSpec, component_id: str) -> ComponentRule:
    rule = scope.rule(component_id)
    assert rule is not None, f"no rule {component_id!r} in scope {scope.scope_id!r}"
    return rule


def node_of(trie: Trie, path: tuple[str, ...]) -> TrieNode:
    node = trie.node(path)
    assert node is not None, f"no trie node at {path!r}"
    return node
