"""Revit 墙厚产品 vertical 的 execution/provider-binding 组合边界。

该模块只负责把现有 authoritative ChangeSet / Semantic Runtime planning snapshot
lineage 绑定到环境已经发布的 ProviderExecutionSnapshotV2。它不选择 provider、不重算
ExecutionSlice，也不把 revision 复制进新的 owner contract。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from design_execution_planning import ExecutionSliceV2
from design_provider_binding import (
    ProviderBindingMaterial,
    ProviderExecutionSnapshotV2,
    compute_provider_snapshot_hash_v2,
)
from semantic_runtime import SnapshotKind

_CANONICAL_REVISION_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")


def _canonical_revision(value: object) -> int:
    """把 Semantic Runtime 的 Host revision 严格解析为 canonical 非负整数。

    ``SemanticSnapshot.base_host_revision`` 是 provider-neutral 文本。此 vertical 的
    Revit Host contract 使用整数 revision，因此这里只接受 ``0`` 或无前导零的十进制
    正整数；禁止在 execution-time 对 ``031``、负数或任意文本做宽松转换。
    """

    if not isinstance(value, str) or _CANONICAL_REVISION_RE.fullmatch(value) is None:
        raise ValueError("planning snapshot revision must be canonical non-negative decimal")
    return int(value)


def _environment_identity(value: object) -> tuple[str, str]:
    """跨 owner 比较 semantic environment 的稳定 id/hash，而不依赖具体 wrapper 类型。"""

    environment_id = getattr(value, "environment_id", None)
    content_hash = getattr(value, "content_hash", None)
    if not isinstance(environment_id, str) or not environment_id.strip():
        raise ValueError("semantic environment requires environment_id")
    if not isinstance(content_hash, str) or not content_hash.strip():
        raise ValueError("semantic environment requires content_hash")
    return environment_id.strip(), content_hash.strip()


def _require_exact_provider_snapshot(
    snapshot: ProviderExecutionSnapshotV2,
    execution_slice: ExecutionSliceV2,
) -> None:
    """确认环境发布的 provider snapshot 只对应当前 exact ExecutionSliceV2。"""

    if not isinstance(snapshot, ProviderExecutionSnapshotV2):
        raise TypeError("provider_snapshot_factory must return ProviderExecutionSnapshotV2")
    if (
        snapshot.materialization_id != execution_slice.materialization_id
        or snapshot.materialization_plan_hash
        != execution_slice.materialization_plan_hash
        or snapshot.execution_slice_id != execution_slice.execution_slice_id
        or snapshot.execution_slice_hash != execution_slice.execution_slice_hash
        or snapshot.host_runtime_ref != execution_slice.host_runtime_ref
    ):
        raise ValueError("provider snapshot does not match exact ExecutionSliceV2 lineage")


class RevitWallThicknessProviderExecutionSnapshotBoundary:
    """把 authoritative planning revision 冻结进 Step31 V2 provider binding material。

    边界从 ChangeSet 的 exact refs 解析 SnapshotSet 与 PlanningSnapshot，并只把
    ``base_host_revision`` 写入已有 ``native_binding_metadata.expected_revision``。这样
    revision 自然参与 ProviderExecutionSnapshotV2 / ProviderBindingV2 内容哈希，而不需要
    扩充 ExecutionSlice、Grant、Saga 或 workflow checkpoint。
    """

    def __init__(
        self,
        *,
        changeset_store,
        snapshot_registry,
        provider_snapshot_factory: Callable[[ExecutionSliceV2], ProviderExecutionSnapshotV2],
    ) -> None:
        if changeset_store is None or not callable(getattr(changeset_store, "get", None)):
            raise TypeError("changeset_store must provide get")
        if snapshot_registry is None:
            raise TypeError("snapshot_registry is required")
        if not callable(getattr(snapshot_registry, "get_snapshot_set", None)):
            raise TypeError("snapshot_registry must provide get_snapshot_set")
        if not callable(getattr(snapshot_registry, "get_snapshot", None)):
            raise TypeError("snapshot_registry must provide get_snapshot")
        if not callable(provider_snapshot_factory):
            raise TypeError("provider_snapshot_factory must be callable")
        self._changeset_store = changeset_store
        self._snapshot_registry = snapshot_registry
        self._provider_snapshot_factory = provider_snapshot_factory

    def __call__(self, execution_slice: ExecutionSliceV2) -> ProviderExecutionSnapshotV2:
        """为一个 exact Revit Slice 发布带 hash-bound expected revision 的 snapshot。"""

        if not isinstance(execution_slice, ExecutionSliceV2):
            raise TypeError("execution_slice must be ExecutionSliceV2")
        if execution_slice.host_runtime_ref.host_type != "revit":
            raise ValueError("Revit provider snapshot boundary requires a Revit execution slice")

        changeset = self._changeset_store.get(execution_slice.changeset_id)
        if (
            changeset.changeset_id != execution_slice.changeset_id
            or changeset.changeset_hash != execution_slice.changeset_hash
        ):
            raise ValueError("ExecutionSliceV2 ChangeSet lineage does not match owner truth")

        snapshot_set_ref = changeset.snapshot_set_ref
        snapshot_set = self._snapshot_registry.get_snapshot_set(
            snapshot_set_ref.snapshot_set_id
        )
        if (
            snapshot_set.snapshot_set_id != snapshot_set_ref.snapshot_set_id
            or snapshot_set.hash != snapshot_set_ref.snapshot_set_hash
        ):
            raise ValueError("ChangeSet SnapshotSet lineage does not match owner truth")
        if _environment_identity(snapshot_set.semantic_environment_ref) != _environment_identity(
            snapshot_set_ref.semantic_environment
        ):
            raise ValueError("SnapshotSet semantic environment does not match ChangeSet ref")

        planning_ref = changeset.planning_snapshot_ref
        if planning_ref.snapshot_id not in tuple(snapshot_set.member_snapshot_ids):
            raise ValueError("PlanningSnapshot is outside authoritative SnapshotSet")
        planning = self._snapshot_registry.get_snapshot(planning_ref.snapshot_id)
        if (
            planning.snapshot_id != planning_ref.snapshot_id
            or planning.hash != planning_ref.snapshot_hash
        ):
            raise ValueError("ChangeSet PlanningSnapshot lineage does not match owner truth")
        if planning.kind is not SnapshotKind.PLANNING:
            raise ValueError("provider binding requires an authoritative PlanningSnapshot")
        if (
            planning.document_ref != execution_slice.host_runtime_ref.document_ref
            or planning_ref.document_ref != execution_slice.host_runtime_ref.document_ref
        ):
            raise ValueError("PlanningSnapshot document does not match Revit execution document")
        planning_environment = _environment_identity(planning.semantic_environment_ref)
        if planning_environment != _environment_identity(planning_ref.semantic_environment):
            raise ValueError("PlanningSnapshot semantic environment does not match ChangeSet ref")
        if planning_environment != _environment_identity(snapshot_set.semantic_environment_ref):
            raise ValueError("PlanningSnapshot semantic environment does not match SnapshotSet")

        expected_revision = _canonical_revision(planning.base_host_revision)
        base_snapshot = self._provider_snapshot_factory(execution_slice)
        _require_exact_provider_snapshot(base_snapshot, execution_slice)

        materials: dict[str, ProviderBindingMaterial] = {}
        for fingerprint, material in base_snapshot.candidate_binding_materials.items():
            metadata = dict(material.native_binding_metadata)
            metadata["expected_revision"] = expected_revision
            materials[fingerprint] = replace(
                material,
                native_binding_metadata=metadata,
            )

        provisional = replace(
            base_snapshot,
            candidate_binding_materials=materials,
            snapshot_hash="0" * 64,
        )
        return replace(
            provisional,
            snapshot_hash=compute_provider_snapshot_hash_v2(provisional),
        )


__all__ = ["RevitWallThicknessProviderExecutionSnapshotBoundary"]
