# Copied from CodeBoarding (https://github.com/CodeBoarding/CodeBoarding) commit 13adc4a0, MIT License, Copyright (c) 2025 CodeBoarding. See LICENSE in this directory.
# Source: static_analyzer/engine/models.py.
# Changes: retain only CallSite and use postponed annotations for its classmethod.
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CallSite:
    """A physical source location where an edge is invoked."""

    file: str
    line: int
    column: int

    @classmethod
    def from_lsp_position(cls, file: str, line: int, column: int) -> CallSite:
        return cls(file=file, line=line + 1, column=column + 1)

    @property
    def human_line(self) -> int:
        return self.line

    @property
    def human_column(self) -> int:
        return self.column

    @property
    def lsp_line(self) -> int:
        return self.line - 1

    @property
    def lsp_column(self) -> int:
        return self.column - 1
