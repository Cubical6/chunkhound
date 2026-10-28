# Copied from CodeBoarding (MIT, see ../LICENSE) at 13adc4a0: infra/clustering_ids.py.
# Changes: kept only what names/ uses: ScopeId, ComponentId, ROOT_SCOPE_ID, CodeBoardingClusterIds;
# `type X = ...` statements became `TypeAlias` (Python 3.10); dropped ClusterId, GroupId, GraphClusterIds,
# from_graph_id(s) and is_self_or_descendant, which belong to the call-graph clustering.
"""Identifier types and operations shared across clustering layers."""

from typing import TypeAlias

ScopeId: TypeAlias = str
ComponentId: TypeAlias = str

ROOT_SCOPE_ID: ScopeId = "root"


class CodeBoardingClusterIds:
    @classmethod
    def prefix_for_scope(cls, scope_id: ScopeId) -> ComponentId:
        return "" if scope_id == ROOT_SCOPE_ID else scope_id

    @classmethod
    def sort(cls, cluster_ids: set[ComponentId]) -> list[ComponentId]:
        return sorted(cluster_ids, key=_cluster_id_sort_key)

    @classmethod
    def qualify_local_id(cls, local_cluster_id: ComponentId, source_cluster_id_prefix: str = "") -> ComponentId:
        if not source_cluster_id_prefix:
            return local_cluster_id
        return f"{source_cluster_id_prefix}.{local_cluster_id}"

    @classmethod
    def qualify_local_ids(
        cls, local_cluster_ids: list[ComponentId], source_cluster_id_prefix: str = ""
    ) -> list[ComponentId]:
        return [cls.qualify_local_id(cluster_id, source_cluster_id_prefix) for cluster_id in local_cluster_ids]


def _cluster_id_sort_key(cluster_id: ComponentId) -> tuple[tuple[int, int | str], ...]:
    parts = tuple((0, int(part)) if part.isdigit() else (1, part) for part in cluster_id.split("."))
    return ((0, len(parts)), *parts)
