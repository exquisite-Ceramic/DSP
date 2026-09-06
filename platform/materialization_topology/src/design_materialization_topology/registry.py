"""DSP 物化拓扑快照的进程内参考注册表。"""

from __future__ import annotations

from threading import RLock

from .contracts import MaterializationTopologyError, MaterializationTopologySnapshot
from .hashing import validate_materialization_topology_snapshot


class MaterializationTopologyRegistry:
    """按拓扑命名空间和修订号保存不可变快照。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshots: dict[tuple[str, int], MaterializationTopologySnapshot] = {}

    def register(self, snapshot: MaterializationTopologySnapshot) -> None:
        """注册一个完整快照；同内容重放幂等，不同内容同修订失败关闭。"""
        validate_materialization_topology_snapshot(snapshot)
        key = (snapshot.topology_environment_id, snapshot.topology_revision)
        with self._lock:
            existing = self._snapshots.get(key)
            if existing is None:
                self._snapshots[key] = snapshot
                return
            if existing == snapshot:
                return
            raise MaterializationTopologyError(
                "MATERIALIZATION_TOPOLOGY_MISMATCH",
                "topology environment and revision already bind different content",
            )

    def get(
        self,
        topology_environment_id: str,
        topology_revision: int,
    ) -> MaterializationTopologySnapshot:
        """读取精确拓扑修订，不进行运行时 Host 可用性发现。"""
        if not isinstance(topology_environment_id, str) or not topology_environment_id.strip():
            raise ValueError("topology_environment_id is required")
        if (
            not isinstance(topology_revision, int)
            or isinstance(topology_revision, bool)
            or topology_revision < 0
        ):
            raise ValueError("topology_revision must be a non-negative integer")
        key = (topology_environment_id.strip(), topology_revision)
        with self._lock:
            snapshot = self._snapshots.get(key)
        if snapshot is None:
            raise MaterializationTopologyError(
                "MATERIALIZATION_TOPOLOGY_NOT_FOUND",
                "materialization topology snapshot was not found",
            )
        return snapshot
