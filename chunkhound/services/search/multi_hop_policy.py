"""Pure multi-hop stopping and search-strategy selection rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from chunkhound.core.config.research_config import (
    MIN_EXPANSION_CANDIDATES,
    MIN_RELEVANCE_FLOOR,
    SCORE_DROP_THRESHOLD,
)


class StopReason(str, Enum):
    """Reasons an iterative multi-hop search can stop."""

    TIME_LIMIT = "time_limit"
    RESULT_LIMIT = "result_limit"
    INSUFFICIENT_CANDIDATES = "insufficient_candidates"
    NO_NEW_CANDIDATES = "no_new_candidates"
    RERANK_ERROR = "rerank_error"
    SCORE_DROP = "score_drop"
    MIN_RELEVANCE = "min_relevance"


@dataclass(frozen=True)
class MultiHopPolicy:
    """Immutable thresholds, independent of providers and I/O."""

    min_candidates: int = MIN_EXPANSION_CANDIDATES
    score_drop_threshold: float = SCORE_DROP_THRESHOLD
    min_relevance_floor: float = MIN_RELEVANCE_FLOOR

    @classmethod
    def from_config(cls, config: Any = None) -> MultiHopPolicy:
        """Accept partial configs, falling back independently for each field."""
        return cls(
            min_candidates=getattr(
                config, "multi_hop_min_candidates", MIN_EXPANSION_CANDIDATES
            ),
            score_drop_threshold=getattr(
                config, "multi_hop_score_degradation", SCORE_DROP_THRESHOLD
            ),
            min_relevance_floor=getattr(
                config, "multi_hop_min_relevance", MIN_RELEVANCE_FLOOR
            ),
        )

    def before_expansion(
        self,
        *,
        elapsed_s: float,
        time_limit: float,
        n_results: int,
        result_limit: int | None,
        n_candidates: int,
    ) -> StopReason | None:
        """Check budgets and candidate quality, in their original priority order."""
        if elapsed_s >= time_limit:
            return StopReason.TIME_LIMIT
        if result_limit is not None and n_results >= result_limit:
            return StopReason.RESULT_LIMIT
        if n_candidates < self.min_candidates:
            return StopReason.INSUFFICIENT_CANDIDATES
        return None

    def after_rerank(
        self, *, max_score_drop: float | None, min_top_score: float
    ) -> StopReason | None:
        """Check tracked-score degradation before the current top-score floor."""
        if max_score_drop is not None and max_score_drop >= self.score_drop_threshold:
            return StopReason.SCORE_DROP
        if min_top_score < self.min_relevance_floor:
            return StopReason.MIN_RELEVANCE
        return None


def select_search_strategy(
    force_strategy: str | None, supports_reranking: bool
) -> tuple[str, str]:
    """Choose a strategy, falling back when forced multi-hop lacks a reranker."""
    if force_strategy == "single_hop":
        return "single_hop", "forced"
    if not supports_reranking:
        return "single_hop", "no_reranker"
    if force_strategy == "multi_hop":
        return "multi_hop", "forced"
    return "multi_hop", "provider_supports_reranking"
