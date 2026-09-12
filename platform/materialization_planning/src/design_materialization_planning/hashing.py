"""Phase I 物化 intent、required set 与 plan 的确定性内容寻址。"""

from __future__ import annotations

import hashlib
import json

from .contracts import MaterializationIntent


def _sha256_json(payload: object) -> str:
    """对 canonical JSON 语义体计算 SHA-256。"""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _intent_sort_key(intent: MaterializationIntent) -> tuple[str, str, str]:
    """冻结 Host/slot/materialization 的跨运行稳定顺序。"""
    return (
        intent.required_host_type,
        intent.materialization_slot_id,
        intent.materialization_id,
    )


def _intent_semantic_payload(intent: MaterializationIntent) -> dict[str, object]:
    """返回不含 construction id/hash 的 intent 语义体。"""
    if not isinstance(intent, MaterializationIntent):
        raise TypeError("intent must be MaterializationIntent")
    return {
        "version": "MATERIALIZATION_INTENT_V1",
        "source_operation_id": intent.source_operation_id,
        "source_operation_hash": intent.source_operation_hash,
        "semantic_targets": sorted(intent.semantic_targets),
        "materialization_slot_id": intent.materialization_slot_id,
        "required_host_type": intent.required_host_type,
        "expected_effects": sorted(intent.expected_effects),
    }


def compute_materialization_intent_hash(intent: MaterializationIntent) -> str:
    """计算单个 materialization intent 的内容哈希。"""
    return _sha256_json(_intent_semantic_payload(intent))


def _required_identity_payload(intent: MaterializationIntent) -> dict[str, object]:
    """投影 required set 所需的完整不可变 materialization 身份。"""
    if not isinstance(intent, MaterializationIntent):
        raise TypeError("intents must contain only MaterializationIntent values")
    return {
        "materialization_id": intent.materialization_id,
        "intent_hash": intent.intent_hash,
        "materialization_slot_id": intent.materialization_slot_id,
        "required_host_type": intent.required_host_type,
        "semantic_targets": sorted(intent.semantic_targets),
    }


def compute_required_set_hash(intents: tuple[MaterializationIntent, ...]) -> str:
    """从排序后的 REQUIRED materialization 身份计算 closed-world 集合哈希。"""
    normalized = tuple(intents)
    if not normalized:
        raise ValueError("intents requires at least one MaterializationIntent")
    ordered = sorted(normalized, key=_intent_sort_key)
    payload = {
        "version": "MATERIALIZATION_REQUIRED_SET_V1",
        "required_materializations": [
            _required_identity_payload(intent) for intent in ordered
        ],
    }
    return _sha256_json(payload)


def compute_materialization_plan_hash(
    *,
    changeset_hash: str,
    approved_scope_hash: str,
    topology_snapshot_hash: str,
    intents: tuple[MaterializationIntent, ...],
    required_set_hash: str,
    convergence_profile_hash: str,
) -> str:
    """绑定完整 Phase I lineage 并对 intent 输入顺序做 canonical 化。"""
    normalized = tuple(intents)
    if not normalized:
        raise ValueError("intents requires at least one MaterializationIntent")
    ordered = sorted(normalized, key=_intent_sort_key)
    payload = {
        "version": "MATERIALIZATION_PLAN_V1",
        "changeset_hash": changeset_hash,
        "approved_scope_hash": approved_scope_hash,
        "topology_snapshot_hash": topology_snapshot_hash,
        "intents": [
            {
                **_required_identity_payload(intent),
                "source_operation_id": intent.source_operation_id,
                "source_operation_hash": intent.source_operation_hash,
                "expected_effects": sorted(intent.expected_effects),
            }
            for intent in ordered
        ],
        "required_set_hash": required_set_hash,
        "convergence_profile_hash": convergence_profile_hash,
    }
    return _sha256_json(payload)


__all__ = [
    "compute_materialization_intent_hash",
    "compute_materialization_plan_hash",
    "compute_required_set_hash",
]
