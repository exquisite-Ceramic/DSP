"""DSP 物化拓扑公开 API。"""

from .contracts import (
    MaterializationRequirement,
    MaterializationSlot,
    MaterializationTopologyError,
    MaterializationTopologySnapshot,
)
from .hashing import (
    compute_topology_snapshot_hash,
    validate_materialization_topology_snapshot,
)
from .registry import MaterializationTopologyRegistry

__all__ = [
    "MaterializationRequirement",
    "MaterializationSlot",
    "MaterializationTopologyError",
    "MaterializationTopologyRegistry",
    "MaterializationTopologySnapshot",
    "compute_topology_snapshot_hash",
    "validate_materialization_topology_snapshot",
]
