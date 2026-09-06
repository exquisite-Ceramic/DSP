"""Convergence profile、证据与结果的 canonical SHA-256 哈希。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from enum import Enum
from hashlib import sha256
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .contracts import (
        ConvergenceEvidenceSet,
        ConvergenceResult,
        MaterializationCanonicalEvidence,
    )
    from .profile import ConvergenceFieldRule


def _required_text(value: object, *, field_name: str) -> str:
    """规范化哈希输入中的必填文本。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _sha256_json(material: object) -> str:
    """对 canonical JSON 语义体计算 SHA-256。"""
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _plain(value: Any) -> Any:
    """把只读容器与枚举规范化为 JSON 可哈希语义值。"""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


def _reference_payload(value: object) -> object:
    """读取 semantic reference 的稳定公开 payload。"""
    payload = getattr(value, "payload", None)
    if callable(payload):
        return _plain(payload())
    raise TypeError("semantic reference must expose payload()")


def _rule_payload(rule: ConvergenceFieldRule) -> dict[str, str]:
    """把规则投影成与 dataclass 实现细节无关的 canonical payload。"""
    from .profile import ConvergenceFieldRule

    if not isinstance(rule, ConvergenceFieldRule):
        raise TypeError("field_rules entries must be ConvergenceFieldRule")
    return {
        "subjects_from_argument": rule.subjects_from_argument,
        "path": rule.path,
        "expected_argument": rule.expected_argument,
        "measurement_unit": rule.measurement_unit,
        "comparison_mode": rule.comparison_mode.value,
    }


def compute_convergence_profile_hash(
    profile_version: str,
    field_rules: tuple[ConvergenceFieldRule, ...],
) -> str:
    """按语义内容排序规则后计算稳定 SHA-256。"""
    version = _required_text(profile_version, field_name="profile_version")
    rules = tuple(field_rules)
    if not rules:
        raise ValueError("field_rules requires at least one rule")
    payloads = sorted(
        (_rule_payload(rule) for rule in rules),
        key=lambda item: (
            item["subjects_from_argument"],
            item["path"],
            item["expected_argument"],
            item["measurement_unit"],
            item["comparison_mode"],
        ),
    )
    material = {
        "profile_version": version,
        "field_rules": payloads,
    }
    return _sha256_json(material)


def compute_materialization_canonical_evidence_hash(
    evidence: MaterializationCanonicalEvidence,
) -> str:
    """计算单个 materialization canonical post-state 证据哈希。"""
    from .contracts import MaterializationCanonicalEvidence

    if not isinstance(evidence, MaterializationCanonicalEvidence):
        raise TypeError("evidence must be MaterializationCanonicalEvidence")
    fields = [
        {
            "path": item.path,
            "value": _plain(item.value),
            "unit": item.unit,
        }
        for item in sorted(evidence.verified_fields, key=lambda item: item.path)
    ]
    return _sha256_json(
        {
            "version": "MATERIALIZATION_CANONICAL_EVIDENCE_V1",
            "materialization_id": evidence.materialization_id,
            "semantic_id": evidence.semantic_id,
            "execution_slice_hash": evidence.execution_slice_hash,
            "actual_delta_hash": evidence.actual_delta_hash,
            "verification_hash": evidence.verification_hash,
            "semantic_environment_ref": _reference_payload(
                evidence.semantic_environment_ref
            ),
            "post_execution_projection_ref": _reference_payload(
                evidence.post_execution_projection_ref
            ),
            "canonical_kind": evidence.canonical_kind,
            "verified_fields": fields,
        }
    )


def compute_convergence_evidence_set_hash(
    evidence_set: ConvergenceEvidenceSet,
) -> str:
    """绑定完整 required-set evidence coverage 并计算稳定哈希。"""
    from .contracts import ConvergenceEvidenceSet

    if not isinstance(evidence_set, ConvergenceEvidenceSet):
        raise TypeError("evidence_set must be ConvergenceEvidenceSet")
    ordered = sorted(
        evidence_set.evidence_items,
        key=lambda item: (item.materialization_id, item.semantic_id),
    )
    return _sha256_json(
        {
            "version": "CONVERGENCE_EVIDENCE_SET_V1",
            "materialization_plan_hash": evidence_set.materialization_plan_hash,
            "required_set_hash": evidence_set.required_set_hash,
            "convergence_profile_hash": evidence_set.convergence_profile_hash,
            "semantic_environment_ref": _reference_payload(
                evidence_set.semantic_environment_ref
            ),
            "evidence_hashes": [item.evidence_hash for item in ordered],
        }
    )


def compute_convergence_result_hash(result: ConvergenceResult) -> str:
    """计算 convergence 判定的 provider-neutral 内容哈希。"""
    from .contracts import ConvergenceResult

    if not isinstance(result, ConvergenceResult):
        raise TypeError("result must be ConvergenceResult")
    return _sha256_json(
        {
            "version": "CONVERGENCE_RESULT_V1",
            "status": result.status.value,
            "materialization_plan_hash": result.materialization_plan_hash,
            "required_set_hash": result.required_set_hash,
            "convergence_profile_hash": result.convergence_profile_hash,
            "evidence_set_hash": result.evidence_set_hash,
        }
    )


__all__ = [
    "compute_convergence_evidence_set_hash",
    "compute_convergence_profile_hash",
    "compute_convergence_result_hash",
    "compute_materialization_canonical_evidence_hash",
]
