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


__all__ = ["InMemorySnapshotRegistry", "SnapshotRegistryError"]
