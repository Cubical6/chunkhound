# Copied from CodeBoarding (https://github.com/CodeBoarding/CodeBoarding) commit 13adc4a0, MIT License, Copyright (c) 2025 CodeBoarding. See LICENSE in this directory.
# Source: static_analyzer/config.py.
# Changes: retain only Language, LANGUAGE_EXTENSIONS and NodeType enum values.
# Changes: omit Kotlin and inline suffix strings instead of SourceSuffix members.
# Changes: use str + Enum for Python 3.10 compatibility.
from enum import Enum, IntEnum


class Language(str, Enum):
    """Enumeration of supported programming languages.

    Using Enum ensures type safety and prevents typos in language names.
    The values are the lowercase language identifiers used in LSP and throughout
    the codebase.
    """

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    GO = "go"
    JAVA = "java"
    PHP = "php"
    RUST = "rust"
    CSHARP = "csharp"
    CPP = "cpp"


LANGUAGE_EXTENSIONS: dict[Language, tuple[str, ...]] = {
    Language.PYTHON: (".py",),
    # TypeScript carries the JavaScript suffixes too: one tsserver serves the whole family,
    # and ``allowJs`` puts .js inside a TypeScript project.
    Language.TYPESCRIPT: (
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
    ),
    Language.JAVASCRIPT: (".js", ".jsx", ".mjs", ".cjs"),
    Language.GO: (".go",),
    Language.JAVA: (".java",),
    Language.PHP: (".php",),
    Language.RUST: (".rs",),
    Language.CSHARP: (".cs",),
    Language.CPP: (
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".hh",
        ".hxx",
        ".h",
    ),
}


class NodeType(IntEnum):
    """LSP SymbolKind constants as an IntEnum.

    The integer values match the LSP specification so comparisons with raw LSP
    ``symbol.get("kind")`` still work transparently (IntEnum is an int subclass).

    All 26 standard LSP SymbolKind values are included so that any symbol kind
    returned by an LSP server can be represented without raising ValueError.
    """

    FILE = 1
    MODULE = 2
    NAMESPACE = 3
    PACKAGE = 4
    CLASS = 5
    METHOD = 6
    PROPERTY = 7
    FIELD = 8
    CONSTRUCTOR = 9
    ENUM = 10
    INTERFACE = 11
    FUNCTION = 12
    VARIABLE = 13
    CONSTANT = 14
    STRING = 15
    NUMBER = 16
    BOOLEAN = 17
    ARRAY = 18
    OBJECT = 19
    KEY = 20
    NULL = 21
    ENUM_MEMBER = 22
    STRUCT = 23
    EVENT = 24
    OPERATOR = 25
    TYPE_PARAMETER = 26
