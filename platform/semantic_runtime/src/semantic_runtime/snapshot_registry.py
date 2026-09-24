"""Semantic Runtime owner-local immutable snapshot reference registry."""

from __future__ import annotations

from .freshness import SemanticSnapshot, SnapshotKind, SnapshotSet


class SnapshotRegistryError(ValueError):
    """Semantic snapshot reference lookup/integrity failure with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _validate_snapshot_identity(snapshot: SemanticSnapshot) -> None:
    """Validate the content-addressed id/hash relation owned by Semantic Runtime."""
    if not isinstance(snapshot, SemanticSnapshot):
        raise TypeError("snapshot must be SemanticSnapshot")
    prefix = "CS" if snapshot.kind is SnapshotKind.CONTEXT else "PS"
    if snapshot.snapshot_id != f"{prefix}-{snapshot.hash[:12]}":
        raise SnapshotRegistryError(
            "SNAPSHOT_REFERENCE_INTEGRITY_INVALID",
            "snapshot id does not match its owner hash",
        )


def _validate_snapshot_set_identity(snapshot_set: SnapshotSet) -> None:
    """Validate SnapshotSet's content-addressed id/hash relation."""
    if not isinstance(snapshot_set, SnapshotSet):
        raise TypeError("snapshot_set must be SnapshotSet")
    if snapshot_set.snapshot_set_id != f"PSS-{snapshot_set.hash[:12]}":
        raise SnapshotRegistryError(
            "SNAPSHOT_SET_REFERENCE_INTEGRITY_INVALID",
            "snapshot-set id does not match its owner hash",
        )


class InMemorySnapshotRegistry:
    """Reference in-memory registry for owner-issued immutable snapshot artifacts."""

    def __init__(self) -> None:
        self._snapshots: dict[str, SemanticSnapshot] = {}
        self._snapshot_sets: dict[str, SnapshotSet] = {}

    def put_snapshot(self, snapshot: SemanticSnapshot) -> None:
        """Persist one immutable snapshot; exact replay is idempotent."""
        existing = self._snapshots.get(snapshot.snapshot_id)
        if existing is not None and existing != snapshot:
            raise SnapshotRegistryError(
                "SNAPSHOT_REFERENCE_CONFLICT",
                f"snapshot reference conflicts with existing content: {snapshot.snapshot_id}",
            )
        _validate_snapshot_identity(snapshot)
        if existing is None:
            self._snapshots[snapshot.snapshot_id] = snapshot

    def get_snapshot(self, snapshot_id: str) -> SemanticSnapshot:
        """Resolve one authoritative snapshot reference and re-check owner identity."""
        try:
            snapshot = self._snapshots[snapshot_id]
        except KeyError as exc:
            raise SnapshotRegistryError(
                "SNAPSHOT_REFERENCE_NOT_FOUND",
                f"snapshot reference is unresolved: {snapshot_id}",
            ) from exc
        _validate_snapshot_identity(snapshot)
        return snapshot

    def get_snapshot_for_freshness_contract(
        self,
        contract_id: str,
        contract_hash: str,
    ) -> SemanticSnapshot:
        """按 owner-owned freshness contract identity 解析唯一 authoritative snapshot。

        Adapter 重建后只能依赖 owner 已持久化的 contract/snapshot lineage，不能维护
        ``operation_ref -> snapshot`` 之类 process-local 私有字典。若同一 contract 在不同
        Host revision 上产生多个快照，本方法拒绝猜测“最新”值并 fail closed。
        """

        normalized_id = str(contract_id).strip()
        normalized_hash = str(contract_hash).strip()
        if not normalized_id or not normalized_hash:
            raise ValueError("contract_id and contract_hash are required")
        matches = [
            snapshot
            for snapshot in self._snapshots.values()
            if snapshot.freshness_contract_id == normalized_id
            and snapshot.freshness_contract_hash == normalized_hash
        ]
        if not matches:
            raise SnapshotRegistryError(
                "SNAPSHOT_CONTRACT_REFERENCE_NOT_FOUND",
                f"freshness contract snapshot is unresolved: {normalized_id}",
            )
        if len(matches) != 1:
            raise SnapshotRegistryError(
                "SNAPSHOT_CONTRACT_REFERENCE_AMBIGUOUS",
                f"freshness contract resolves to multiple snapshots: {normalized_id}",
            )
        snapshot = matches[0]
        _validate_snapshot_identity(snapshot)
        return snapshot

    def put_snapshot_set(self, snapshot_set: SnapshotSet) -> None:
        """Persist one immutable PlanningSnapshot set; exact replay is idempotent."""
        existing = self._snapshot_sets.get(snapshot_set.snapshot_set_id)
        if existing is not None and existing != snapshot_set:
            raise SnapshotRegistryError(
                "SNAPSHOT_SET_REFERENCE_CONFLICT",
                "snapshot-set reference conflicts with existing content: "
                f"{snapshot_set.snapshot_set_id}",
            )
        _validate_snapshot_set_identity(snapshot_set)
        if existing is None:
            self._snapshot_sets[snapshot_set.snapshot_set_id] = snapshot_set

    def get_snapshot_set(self, snapshot_set_id: str) -> SnapshotSet:
        """Resolve one authoritative SnapshotSet and re-check owner identity."""
        try:
            snapshot_set = self._snapshot_sets[snapshot_set_id]
        except KeyError as exc:
            raise SnapshotRegistryError(
                "SNAPSHOT_SET_REFERENCE_NOT_FOUND",
                f"snapshot-set reference is unresolved: {snapshot_set_id}",
            ) from exc
        _validate_snapshot_set_identity(snapshot_set)
        return snapshot_set

    def get_snapshot_set_for_member(self, snapshot_id: str) -> SnapshotSet:
        """解析唯一包含指定 PlanningSnapshot 的 authoritative SnapshotSet。

        Task 6 当前 operation freshness 生成单成员 SnapshotSet；如果未来一个 planning
        snapshot 同时属于多个合法集合，调用方必须携带更精确的 owner ref，而不是由 registry
        任意选择其中一个。
        """

        normalized_id = str(snapshot_id).strip()
        if not normalized_id:
            raise ValueError("snapshot_id is required")
        matches = [
            snapshot_set
            for snapshot_set in self._snapshot_sets.values()
            if normalized_id in snapshot_set.member_snapshot_ids
        ]
        if not matches:
            raise SnapshotRegistryError(
                "SNAPSHOT_SET_MEMBER_REFERENCE_NOT_FOUND",
                f"snapshot-set member is unresolved: {normalized_id}",
            )
        if len(matches) != 1:
            raise SnapshotRegistryError(
                "SNAPSHOT_SET_MEMBER_REFERENCE_AMBIGUOUS",
                f"snapshot belongs to multiple snapshot sets: {normalized_id}",
            )
        snapshot_set = matches[0]
        _validate_snapshot_set_identity(snapshot_set)
        return snapshot_set


__all__ = ["InMemorySnapshotRegistry", "SnapshotRegistryError"]
