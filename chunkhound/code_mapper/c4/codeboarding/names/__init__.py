# Copied from CodeBoarding (MIT, see ../LICENSE) at 13adc4a0: static_analyzer/clustering/names/__init__.py.
# Changes: imports point at chunkhound.code_mapper.c4.codeboarding.names; dropped units_from_graph(s).
"""Partition a repository by what its qualified names say: one tree, replayed everywhere.

See ``docs/design/name-tree.md``.
"""

from chunkhound.code_mapper.c4.codeboarding.names.draft import (
    AffinityGrouper,
    CandidateGroup,
    Grouper,
    GroupingContext,
    KinshipGrouper,
    draft_scope,
    draft_tree,
    role_words_for,
)
from chunkhound.code_mapper.c4.codeboarding.names.frontier import (
    Candidate,
    Frontier,
    walk,
)
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
    "ROLE_WORDS",
    "AffinityGrouper",
    "Candidate",
    "CandidateGroup",
    "ComponentRule",
    "Frontier",
    "Grouper",
    "GroupingContext",
    "KinshipGrouper",
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
