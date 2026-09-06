"""DSP 物化拓扑的确定性内容寻址。"""

from __future__ import annotations

import hashlib
import json

from .contracts import (
    MaterializationSlot,
    MaterializationTopologyError,
    MaterializationTopologySnapshot,
)


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _slot_sort_key(slot: MaterializationSlot) -> tuple[str, str, str, str]:
    return (
        slot.semantic_target_ref,
        slot.required_host_type,
        slot.document_ref,
        slot.materialization_slot_id,
    )


def _slot_payload(slot: MaterializationSlot) -> dict[str, str]:
    return {
        "materialization_slot_id": slot.materialization_slot_id,
        "semantic_target_ref": slot.semantic_target_ref,
        "required_host_type": slot.required_host_type,
        "document_ref": slot.document_ref,
        "requirement": slot.requirement.value,
    }


def compute_topology_snapshot_hash(snapshot: MaterializationTopologySnapshot) -> str:
    """忽略输入槽顺序，对完整拓扑语义体计算 SHA-256。"""
    if not isinstance(snapshot, MaterializationTopologySnapshot):
        raise TypeError("snapshot must be MaterializationTopologySnapshot")
    payload = {
        "version": "MATERIALIZATION_TOPOLOGY_V1",
        "topology_environment_id": snapshot.topology_environment_id,
        "topology_revision": snapshot.topology_revision,
        "slots": [
            _slot_payload(slot)
            for slot in sorted(snapshot.slots, key=_slot_sort_key)
        ],
    }
    return _sha256_json(payload)


def validate_materialization_topology_snapshot(
    snapshot: MaterializationTopologySnapshot,
) -> None:
    """重算快照哈希并拒绝任何陈旧或被替换的拓扑内容。"""
    if not isinstance(snapshot, MaterializationTopologySnapshot):
        raise TypeError("snapshot must be MaterializationTopologySnapshot")
    expected = compute_topology_snapshot_hash(snapshot)
    if snapshot.topology_snapshot_hash != expected:
        raise MaterializationTopologyError(
            "MATERIALIZATION_TOPOLOGY_INTEGRITY_INVALID",
            "materialization topology snapshot does not match its content hash",
        )
