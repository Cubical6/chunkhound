# Copied from CodeBoarding (https://github.com/CodeBoarding/CodeBoarding) commit 13adc4a0, MIT License, Copyright (c) 2025 CodeBoarding. See LICENSE in this directory.
# Source: tests/static_analyzer/test_hierarchy_builder.py; license: chunkhound/code_mapper/c4/codeboarding/LICENSE.
# Changes: assert extracted base names directly instead of mocked LSP/hierarchy links.
# Changes: combine extends/implements and add namespace and no-base boundary cases.
"""Source-only inheritance fallback contracts."""

import pytest

from chunkhound.code_mapper.c4.codeboarding.hierarchy_fallback import infer_bases_from_line


@pytest.mark.parametrize(
    "line,expected",
    [
        ("class Dog(Animal):", ["Animal"]),
        ("class Duck(Animal, SwimmingMixin):", ["Animal", "SwimmingMixin"]),
        ("class A(metaclass=M):", []),
        ("class Dog extends Animal implements Speakable", ["Animal", "Speakable"]),
        ("class Child extends Base {", ["Base"]),
        ("class Dog implements Speakable {", ["Speakable"]),
        ("class C(A, metaclass=M):", ["A"]),
        ("class Dog extends Zoo\\Animal implements Zoo\\Speakable, Runner {", ["Animal", "Speakable", "Runner"]),
        ("class Plain:", []),
        ("", []),
    ],
)
def test_infers_declared_bases(line: str, expected: list[str]) -> None:
    assert infer_bases_from_line(line) == expected
