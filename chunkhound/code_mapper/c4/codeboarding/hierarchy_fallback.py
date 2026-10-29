# Copied from CodeBoarding (https://github.com/CodeBoarding/CodeBoarding) commit 13adc4a0, MIT License, Copyright (c) 2025 CodeBoarding. See LICENSE in this directory.
# Source: static_analyzer/engine/hierarchy_builder.py:_infer_hierarchy_from_source.
# Changes: extract the line regex logic as a free function returning base names.
# Changes: remove symbol resolution, LSP, SymbolTable and CallGraph dependencies.
"""Read Python and PHP base names from a class declaration line."""

import re


def infer_bases_from_line(line: str) -> list[str]:
    """Return base names in source order, excluding Python metaclass keywords."""
    match = re.search(r"\bclass\s+\w+\s*\(([^)]+)\)", line)
    if match:
        bases = []
        for base in match.group(1).split(","):
            base_name = base.strip().split("=")[0].strip()
            if not base_name or base_name.startswith("metaclass"):
                continue
            bases.append(base_name)
        return bases

    bases = []
    extends_match = re.search(r"\bextends\s+([\w\\]+)", line)
    if extends_match:
        bases.append(extends_match.group(1).rsplit("\\", 1)[-1])

    implements_match = re.search(r"\bimplements\s+(.+?)(?:\s*\{|$)", line)
    if implements_match:
        for iface in implements_match.group(1).split(","):
            iface_name = iface.strip().rsplit("\\", 1)[-1]
            if iface_name:
                bases.append(iface_name)
    return bases
