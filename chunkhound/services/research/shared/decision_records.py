"""Local, content-free decision records for research chunk selection."""

from typing import Any

from loguru import logger

from chunkhound.core import decision_log
from chunkhound.services.research.shared.chunk_dedup import get_chunk_id


def _chunk_reference(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": get_chunk_id(chunk),
        "file_path": chunk.get("file_path"),
        "start_line": chunk.get("start_line"),
        "end_line": chunk.get("end_line"),
    }


def record_chunk_rerank(
    *,
    query: str,
    node_id: int | None,
    depth: int | None,
    path_filter: str | None,
    method: str,
    n_rerank_queries: int,
    semantic_results: list[dict[str, Any]],
    regex_results: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> None:
    """Record the returned pool without copying any chunk content."""
    if not decision_log.is_enabled():
        return
    try:
        semantic_ids = {get_chunk_id(chunk) for chunk in semantic_results}
        decision_log.record(
            "chunk_rerank",
            {
                "query": query,
                "node_id": node_id,
                "depth": depth,
                "has_path_filter": bool(path_filter),
                "method": method,
                "n_rerank_queries": n_rerank_queries,
                "n_semantic": len(semantic_results),
                "n_regex": len(regex_results),
                "n_pool": len(chunks),
                "chunks": [
                    {
                        **_chunk_reference(chunk),
                        "source": (
                            "semantic"
                            if get_chunk_id(chunk) in semantic_ids
                            else "regex"
                        ),
                        "rerank_score": chunk.get("rerank_score"),
                        "similarity": chunk.get("similarity"),
                    }
                    for chunk in chunks
                ],
            },
        )
    except Exception:
        logger.debug("Could not record chunk rerank decision")


def record_elbow_filter(
    stage: str,
    candidates: list[dict[str, Any]],
    kept: list[dict[str, Any]],
    stats: dict[str, Any],
    score_key: str | None = None,
) -> None:
    """Record an identity-based partition, sorted by the filter's score."""
    if not decision_log.is_enabled():
        return
    try:
        # Import lazily: exploration's package exports the instrumented strategies.
        from chunkhound.services.research.shared.exploration.elbow_filter import (
            get_unified_score,
        )

        def score(chunk: dict[str, Any]) -> Any:
            return (
                get_unified_score(chunk)
                if score_key is None
                else chunk.get(score_key, 0.0)
            )

        kept_ids = {id(chunk) for chunk in kept}
        partitions: dict[str, list[dict[str, Any]]] = {"kept": [], "dropped": []}
        for chunk in sorted(candidates, key=score, reverse=True):
            partition = "kept" if id(chunk) in kept_ids else "dropped"
            partitions[partition].append(
                {**_chunk_reference(chunk), "score": score(chunk)}
            )
        decision_log.record(
            "elbow_filter",
            {
                "stage": stage,
                "score_key": "unified" if score_key is None else score_key,
                "method": stats.get("method"),
                "reason": stats.get("reason"),
                "n_candidates": len(candidates),
                "n_kept": len(kept),
                "cutoff_score": stats.get("cutoff_score"),
                "elbow_index": stats.get("elbow_index"),
                **partitions,
            },
        )
    except Exception:
        logger.debug("Could not record elbow filter decision")
