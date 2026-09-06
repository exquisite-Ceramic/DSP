"""从 Step33 已验证 post-state 构造 canonical convergence 证据。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from .contracts import (
    CanonicalFieldEvidence,
    ConvergenceEvidenceSet,
    ConvergenceVerificationError,
    MaterializationCanonicalEvidence,
)
from .hashing import (
    compute_convergence_evidence_set_hash,
    compute_convergence_profile_hash,
    compute_materialization_canonical_evidence_hash,
)
from .profile import ConvergenceComparisonProfile

_MISSING = object()


def _error(code: str, message: str) -> None:
    """统一抛出 convergence 证据错误。"""
    raise ConvergenceVerificationError(code, message)


def _environment_identity(value: object) -> tuple[object, object]:
    """读取 semantic environment 的稳定身份。"""
    return (
        getattr(value, "environment_id", None),
        getattr(value, "content_hash", None),
    )


def _validate_profile(profile: ConvergenceComparisonProfile) -> None:
    """重算 Task4 owner profile hash。"""
    if not isinstance(profile, ConvergenceComparisonProfile):
        raise TypeError("profile must be ConvergenceComparisonProfile")
    expected = compute_convergence_profile_hash(profile.profile_version, profile.field_rules)
    if profile.profile_hash != expected:
        _error("CONVERGENCE_PROFILE_MISMATCH", "convergence profile hash is invalid")


def _validate_plan(plan: object) -> None:
    """重算 materialization plan 的 owner hashes。"""
    from design_materialization_planning import (
        MaterializationPlan,
        compute_materialization_intent_hash,
        compute_materialization_plan_hash,
        compute_required_set_hash,
    )

    if not isinstance(plan, MaterializationPlan):
        raise TypeError("plan must be MaterializationPlan")
    for intent in plan.intents:
        if intent.intent_hash != compute_materialization_intent_hash(intent):
            _error(
                "CONVERGENCE_PLAN_INTEGRITY_INVALID",
                "materialization intent hash is invalid",
            )
    expected_required = compute_required_set_hash(plan.intents)
    if plan.required_set_hash != expected_required:
        _error(
            "CONVERGENCE_PLAN_INTEGRITY_INVALID",
            "required set hash is invalid",
        )
    expected_plan = compute_materialization_plan_hash(
        changeset_hash=plan.changeset_hash,
        approved_scope_hash=plan.approved_scope_hash,
        topology_snapshot_hash=plan.topology_snapshot_hash,
        intents=plan.intents,
        required_set_hash=plan.required_set_hash,
        convergence_profile_hash=plan.convergence_profile_hash,
    )
    if plan.materialization_plan_hash != expected_plan:
        _error(
            "CONVERGENCE_PLAN_INTEGRITY_INVALID",
            "materialization plan hash is invalid",
        )


def _validate_materialization_evidence_integrity(
    evidence: MaterializationCanonicalEvidence,
) -> None:
    """验证单个 canonical evidence 的内容寻址完整性。"""
    if not isinstance(evidence, MaterializationCanonicalEvidence):
        raise TypeError("evidence_items must contain MaterializationCanonicalEvidence")
    expected = compute_materialization_canonical_evidence_hash(evidence)
    if evidence.evidence_hash != expected:
        _error(
            "CONVERGENCE_EVIDENCE_INTEGRITY_INVALID",
            "materialization canonical evidence hash is invalid",
        )


def _path_value(subject: object, path: str) -> object:
    """按 canonical dotted path 读取 provider-neutral subject 字段。"""
    current: object = subject
    for segment in path.split("."):
        if not segment:
            return _MISSING
        if isinstance(current, Mapping):
            if segment not in current:
                return _MISSING
            current = current[segment]
        else:
            if not hasattr(current, segment):
                return _MISSING
            current = getattr(current, segment)
    return current


def _profile_subject_id(
    execution_slice: object,
    profile: ConvergenceComparisonProfile,
) -> str:
    """要求所有 profile rule 在 Phase I 解析到同一 canonical semantic_id。"""
    units = tuple(getattr(execution_slice, "execution_units", ()))
    if len(units) != 1:
        _error(
            "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
            "Phase I convergence requires exactly one execution unit per materialization",
        )
    arguments = getattr(units[0], "arguments", None)
    if not isinstance(arguments, Mapping):
        _error(
            "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
            "execution unit arguments are unavailable",
        )

    resolved: list[str] = []
    for rule in profile.field_rules:
        raw = arguments.get(rule.subjects_from_argument)
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, (str, bytes, bytearray))
        ):
            _error(
                "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
                "profile subject selector does not resolve a canonical sequence",
            )
        values = tuple(raw)
        if len(values) != 1 or not isinstance(values[0], str) or not values[0]:
            _error(
                "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
                "Phase I convergence requires exactly one semantic target",
            )
        resolved.append(values[0])
    if not resolved or len(set(resolved)) != 1:
        _error(
            "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
            "profile rules do not resolve one common semantic target",
        )
    return resolved[0]


def _subject_for_bundle(bundle: object, semantic_id: str) -> object:
    """解析 exact post-execution snapshot-bound semantic subject。"""
    snapshot = getattr(bundle, "post_execution_snapshot_ref", None)
    projection = getattr(bundle, "post_execution_projection_ref", None)
    candidates = tuple(
        subject
        for subject in getattr(bundle, "subject_evidence", ())
        if getattr(subject, "semantic_id", None) == semantic_id
        and getattr(subject, "snapshot_id", None) == getattr(snapshot, "snapshot_id", None)
        and getattr(subject, "snapshot_hash", None) == getattr(snapshot, "hash", None)
        and getattr(subject, "projection_ref", None) == projection
    )
    if len(candidates) != 1:
        _error(
            "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
            "exact post-execution semantic subject is unresolved",
        )
    return candidates[0]


def _verified_fields(
    subject: object,
    profile: ConvergenceComparisonProfile,
) -> tuple[CanonicalFieldEvidence, ...]:
    """只抽取 convergence profile 明确要求的 canonical measurement 字段。"""
    fields: list[CanonicalFieldEvidence] = []
    for rule in profile.field_rules:
        raw = _path_value(subject, rule.path)
        if not isinstance(raw, Mapping) or "value" not in raw or "unit" not in raw:
            _error(
                "CONVERGENCE_EVIDENCE_FIELD_MISSING",
                f"required canonical field is unavailable: {rule.path}",
            )
        unit = raw["unit"]
        if not isinstance(unit, str) or not unit.strip():
            _error(
                "CONVERGENCE_EVIDENCE_FIELD_MISSING",
                f"required canonical field has no unit: {rule.path}",
            )
        fields.append(
            CanonicalFieldEvidence(
                path=rule.path,
                value=raw["value"],
                unit=unit,
            )
        )
    return tuple(sorted(fields, key=lambda item: item.path))


def _validate_local_verification(
    execution_slice: object,
    actual_delta: object,
    verification_result: object,
    verification_evidence_bundle: object,
) -> None:
    """复用 Step33 owner hash，确认输入确实是同一份本地 PASS 证据。"""
    from design_execution_reconciliation import (
        ActualDelta,
        ReconciliationError,
        SemanticVerificationResult,
        VerificationEvidenceBundle,
        VerificationStatus,
        compute_semantic_verification_hash,
        compute_validation_task_result_hash,
        validate_actual_delta_integrity,
        validate_verification_evidence_bundle_integrity,
    )
    from design_execution_planning import ExecutionSliceV2

    if not isinstance(execution_slice, ExecutionSliceV2):
        raise TypeError("execution_slice must be ExecutionSliceV2")
    if not isinstance(actual_delta, ActualDelta):
        raise TypeError("actual_delta must be ActualDelta")
    if not isinstance(verification_result, SemanticVerificationResult):
        raise TypeError("verification_result must be SemanticVerificationResult")
    if not isinstance(verification_evidence_bundle, VerificationEvidenceBundle):
        raise TypeError("verification_evidence_bundle must be VerificationEvidenceBundle")

    try:
        validate_actual_delta_integrity(actual_delta)
        validate_verification_evidence_bundle_integrity(verification_evidence_bundle)
    except ReconciliationError as exc:
        _error(
            "CONVERGENCE_EVIDENCE_INTEGRITY_INVALID",
            f"Step33 evidence integrity failed: {exc.code}",
        )

    if any(
        item.task_result_hash != compute_validation_task_result_hash(item)
        for item in verification_result.task_results
    ):
        _error(
            "CONVERGENCE_EVIDENCE_INTEGRITY_INVALID",
            "semantic verification task result hash is invalid",
        )
    if verification_result.verification_hash != compute_semantic_verification_hash(
        verification_result
    ):
        _error(
            "CONVERGENCE_EVIDENCE_INTEGRITY_INVALID",
            "semantic verification result hash is invalid",
        )
    if verification_result.status is not VerificationStatus.PASSED or any(
        item.status is not VerificationStatus.PASSED
        for item in verification_result.task_results
    ):
        _error(
            "CONVERGENCE_EVIDENCE_LOCAL_VERIFICATION_NOT_PASSED",
            "local semantic verification must be PASSED",
        )

    slice_hash = execution_slice.execution_slice_hash
    delta_hash = actual_delta.actual_delta_hash
    joins = (
        (slice_hash, actual_delta.execution_slice_hash),
        (slice_hash, verification_result.execution_slice_hash),
        (slice_hash, verification_evidence_bundle.execution_slice_hash),
        (delta_hash, verification_result.actual_delta_hash),
        (delta_hash, verification_evidence_bundle.actual_delta_hash),
        (
            verification_result.evidence_bundle_hash,
            verification_evidence_bundle.evidence_bundle_hash,
        ),
        (verification_result.changeset_hash, actual_delta.changeset_hash),
        (verification_result.changeset_hash, verification_evidence_bundle.changeset_hash),
    )
    if any(expected != actual for expected, actual in joins):
        _error(
            "CONVERGENCE_EVIDENCE_LINEAGE_MISMATCH",
            "Step33 local verification lineage does not join exactly",
        )


def build_materialization_canonical_evidence(
    *,
    materialization_id: str,
    execution_slice: object,
    actual_delta: object,
    verification_result: object,
    verification_evidence_bundle: object,
    convergence_profile: ConvergenceComparisonProfile,
) -> MaterializationCanonicalEvidence:
    """从 exact Step33 PASS bundle 构造一个 materialization canonical evidence。"""
    _validate_profile(convergence_profile)
    _validate_local_verification(
        execution_slice,
        actual_delta,
        verification_result,
        verification_evidence_bundle,
    )
    if materialization_id != getattr(execution_slice, "materialization_id", None):
        _error(
            "CONVERGENCE_EVIDENCE_LINEAGE_MISMATCH",
            "materialization id does not match ExecutionSliceV2",
        )

    semantic_id = _profile_subject_id(execution_slice, convergence_profile)
    subject = _subject_for_bundle(verification_evidence_bundle, semantic_id)
    draft = MaterializationCanonicalEvidence(
        materialization_id=materialization_id,
        semantic_id=semantic_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        actual_delta_hash=actual_delta.actual_delta_hash,
        verification_hash=verification_result.verification_hash,
        semantic_environment_ref=verification_evidence_bundle.semantic_environment_ref,
        post_execution_projection_ref=(
            verification_evidence_bundle.post_execution_projection_ref
        ),
        canonical_kind=subject.canonical_kind,
        verified_fields=_verified_fields(subject, convergence_profile),
        evidence_hash="0" * 64,
    )
    return replace(
        draft,
        evidence_hash=compute_materialization_canonical_evidence_hash(draft),
    )


def build_convergence_evidence_set(
    *,
    plan: object,
    profile: ConvergenceComparisonProfile,
    evidence_items: Sequence[MaterializationCanonicalEvidence],
) -> ConvergenceEvidenceSet:
    """按 immutable required set 构造 closed-world convergence evidence set。"""
    _validate_plan(plan)
    _validate_profile(profile)
    if plan.convergence_profile_hash != profile.profile_hash:
        _error(
            "CONVERGENCE_PROFILE_MISMATCH",
            "materialization plan does not bind the supplied convergence profile",
        )

    items = tuple(evidence_items)
    if not items:
        _error(
            "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
            "evidence_items cannot be empty",
        )
    for item in items:
        _validate_materialization_evidence_integrity(item)

    expected_by_id = {intent.materialization_id: intent for intent in plan.intents}
    actual_ids = tuple(item.materialization_id for item in items)
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected_by_id):
        _error(
            "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
            "evidence set must cover every required materialization exactly once",
        )

    expected_paths = {rule.path for rule in profile.field_rules}
    for item in items:
        intent = expected_by_id[item.materialization_id]
        if tuple(intent.semantic_targets) != (item.semantic_id,):
            _error(
                "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
                "materialization evidence semantic target differs from immutable intent",
            )
        if {field.path for field in item.verified_fields} != expected_paths:
            _error(
                "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
                "materialization evidence does not cover the exact profile field set",
            )

    environment = _environment_identity(items[0].semantic_environment_ref)
    if environment == (None, None) or any(
        _environment_identity(item.semantic_environment_ref) != environment
        for item in items[1:]
    ):
        _error(
            "CONVERGENCE_EVIDENCE_ENVIRONMENT_MISMATCH",
            "all materialization evidence must use the same semantic environment",
        )

    draft = ConvergenceEvidenceSet(
        materialization_plan_hash=plan.materialization_plan_hash,
        required_set_hash=plan.required_set_hash,
        convergence_profile_hash=profile.profile_hash,
        semantic_environment_ref=items[0].semantic_environment_ref,
        evidence_items=items,
        evidence_set_hash="0" * 64,
    )
    return replace(
        draft,
        evidence_set_hash=compute_convergence_evidence_set_hash(draft),
    )


__all__ = [
    "build_convergence_evidence_set",
    "build_materialization_canonical_evidence",
]
