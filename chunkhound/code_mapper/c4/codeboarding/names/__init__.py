# Copied from CodeBoarding (https://github.com/CodeBoarding/CodeBoarding) commit 13adc4a0, MIT License, Copyright (c) 2025 CodeBoarding. See LICENSE in this directory.
# Source: static_analyzer/clustering/names/__init__.py; license: ../LICENSE.
# Changes: imports point at chunkhound.code_mapper.c4.codeboarding.names.
# Changes: dropped units_from_graph(s).
# Changes: re-export Links and ROOT_SCOPE_ID as required by the ChunkHound package interface.
"""Partition a repository by what its qualified names say: one tree, replayed everywhere.

See ``docs/design/name-tree.md``.
"""

from chunkhound.code_mapper.c4.codeboarding.names.draft import (
    AffinityGrouper,
    CandidateGroup,
    Grouper,
    GroupingContext,
    KinshipGrouper,
    Links,
    draft_scope,
    draft_tree,
    role_words_for,
)
from chunkhound.code_mapper.c4.codeboarding.names.frontier import (
    Candidate,
    Frontier,
    walk,
)
from chunkhound.code_mapper.c4.codeboarding.names.ids import ROOT_SCOPE_ID
from chunkhound.code_mapper.c4.codeboarding.names.inventory import (
    Trie,
    Unit,
)
from chunkhound.code_mapper.c4.codeboarding.names.replay import Partition, replay
from chunkhound.code_mapper.c4.codeboarding.names.spec import (
    ComponentRule,
    ScopeSpec,
    TreeSpec,
)
from chunkhound.code_mapper.c4.codeboarding.names.tokens import (
    ROLE_WORDS,
    stem,
    tokenize,
)

__all__ = [
    "ROOT_SCOPE_ID",
    "ROLE_WORDS",
    "AffinityGrouper",
    "Candidate",
    "CandidateGroup",
    "ComponentRule",
    "Frontier",
    "Grouper",
    "GroupingContext",
    "KinshipGrouper",
    "Links",
    "Partition",
    "ScopeSpec",
    "TreeSpec",
    "Trie",
    "Unit",
    "draft_scope",
    "draft_tree",
    "replay",
    "role_words_for",
    "stem",
    "tokenize",
    "walk",
]
