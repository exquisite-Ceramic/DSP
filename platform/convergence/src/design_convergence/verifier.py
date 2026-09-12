"""Phase I provider-neutral exact cross-materialization convergence 判定。"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from .contracts import (
    ConvergenceEvidenceSet,
    ConvergenceResult,
    ConvergenceStatus,
    ConvergenceVerificationError,
)
from .evidence import build_convergence_evidence_set
from .hashing import (
    compute_convergence_evidence_set_hash,
    compute_convergence_result_hash,
)
from .profile import ConvergenceComparisonProfile


def _error(code: str, message: str) -> None:
    """统一抛出 convergence verifier 错误。"""
    raise ConvergenceVerificationError(code, message)


def _plain(value: Any) -> Any:
    """把 canonical 值规范化为稳定 JSON 结构。"""
    from collections.abc import Mapping, Sequence
    from enum import Enum

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


def _value_token(value: object) -> str:
    """把 canonical 值编码为 exact equality token。"""
    return json.dumps(
        _plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _validate_evidence_set(
    plan: object,
    profile: ConvergenceComparisonProfile,
    evidence_set: ConvergenceEvidenceSet,
) -> ConvergenceEvidenceSet:
    """先验证 evidence set 自身哈希，再重建 caller-bound closed-world coverage。"""
    if not isinstance(evidence_set, ConvergenceEvidenceSet):
        raise TypeError("evidence_set must be ConvergenceEvidenceSet")
    expected_hash = compute_convergence_evidence_set_hash(evidence_set)
    if evidence_set.evidence_set_hash != expected_hash:
        _error(
            "CONVERGENCE_EVIDENCE_INTEGRITY_INVALID",
            "convergence evidence set hash is invalid",
        )

    rebuilt = build_convergence_evidence_set(
        plan=plan,
        profile=profile,
        evidence_items=evidence_set.evidence_items,
    )
    if evidence_set.materialization_plan_hash != rebuilt.materialization_plan_hash:
        _error(
            "CONVERGENCE_PLAN_MISMATCH",
            "evidence set does not bind the supplied materialization plan",
        )
    if evidence_set.required_set_hash != rebuilt.required_set_hash:
        _error(
            "CONVERGENCE_REQUIRED_SET_MISMATCH",
            "evidence set does not bind the supplied required set",
        )
    if evidence_set.convergence_profile_hash != rebuilt.convergence_profile_hash:
        _error(
            "CONVERGENCE_PROFILE_MISMATCH",
            "evidence set does not bind the supplied convergence profile",
        )
    supplied_environment = (
        getattr(evidence_set.semantic_environment_ref, "environment_id", None),
        getattr(evidence_set.semantic_environment_ref, "content_hash", None),
    )
    rebuilt_environment = (
        getattr(rebuilt.semantic_environment_ref, "environment_id", None),
        getattr(rebuilt.semantic_environment_ref, "content_hash", None),
    )
    if supplied_environment != rebuilt_environment:
        _error(
            "CONVERGENCE_EVIDENCE_ENVIRONMENT_MISMATCH",
            "evidence set semantic environment differs from its evidence items",
        )
    return rebuilt


def _status_for_exact_fields(
    profile: ConvergenceComparisonProfile,
    evidence_set: ConvergenceEvidenceSet,
) -> ConvergenceStatus:
    """只按 profile-required canonical fields 做 exact equality。"""
    by_materialization = tuple(
        sorted(evidence_set.evidence_items, key=lambda item: item.materialization_id)
    )
    for rule in profile.field_rules:
        values: list[str] = []
        for item in by_materialization:
            field_by_path = {field.path: field for field in item.verified_fields}
            field = field_by_path.get(rule.path)
            if field is None or field.unit != rule.measurement_unit:
                return ConvergenceStatus.EVIDENCE_INSUFFICIENT
            values.append(_value_token(field.value))
        if len(set(values)) != 1:
            return ConvergenceStatus.DIVERGED
    return ConvergenceStatus.CONVERGED


class CrossHostConvergenceVerifier:
    """验证 immutable required set 的 provider-neutral exact canonical convergence。"""

    def verify(
        self,
        plan: object,
        profile: ConvergenceComparisonProfile,
        evidence_set: ConvergenceEvidenceSet,
    ) -> ConvergenceResult:
        """验证 closed-world lineage 后返回内容寻址 convergence 结果。"""
        rebuilt = _validate_evidence_set(plan, profile, evidence_set)
        status = _status_for_exact_fields(profile, rebuilt)
        draft = ConvergenceResult(
            status=status,
            materialization_plan_hash=rebuilt.materialization_plan_hash,
            required_set_hash=rebuilt.required_set_hash,
            convergence_profile_hash=rebuilt.convergence_profile_hash,
            evidence_set_hash=rebuilt.evidence_set_hash,
            convergence_result_hash="0" * 64,
        )
        return replace(
            draft,
            convergence_result_hash=compute_convergence_result_hash(draft),
        )


__all__ = ["CrossHostConvergenceVerifier"]
