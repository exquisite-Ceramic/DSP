"""Phase I Step33 V2 的本地 scope/semantic reconciliation 服务。"""

from __future__ import annotations

from dataclasses import dataclass

from design_approval_scope import (
    ApprovalScopeBoundaryV2,
    ApprovalScopeError,
    validate_approval_scope_boundary_v2,
)
from design_changeset import (
    CanonicalChangeSet,
    ChangeSetError,
    ValidationTask,
    validate_changeset_integrity_v2,
)
from design_execution_planning import ExecutionPlanV2, ExecutionSliceV2
from design_gateway_authorization import AdmittedExecutionAuthorityV2
from design_materialization_planning import MaterializationPlan

from .contracts import (
    ActualDelta,
    ReconciliationError,
    ScopeComparisonResult,
    SemanticVerificationResult,
    VerificationEvidenceBundle,
)
from .hashing import validate_actual_delta_integrity
from .saga_v2 import ExecutionSagaControllerV2
from .scope_comparator import _evaluate_scope_effects
from .verifier import _evaluate_semantic_verification


def _lineage_error(message: str) -> None:
    """统一抛出 V2 exact lineage 不匹配错误。"""
    raise ReconciliationError("RECONCILIATION_LINEAGE_MISMATCH", message)


def _input_error(message: str, *, upstream_code: str | None = None) -> None:
    """统一抛出 V2 evaluator 输入完整性错误。"""
    raise ReconciliationError(
        "RECONCILIATION_INPUT_INVALID",
        message,
        upstream_code=upstream_code,
    )


def _validate_owner_truth(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundaryV2,
) -> None:
    """在 evaluator 前调用 Step28/29 V2 owner validator。"""
    try:
        validate_approval_scope_boundary_v2(boundary)
    except ApprovalScopeError as exc:
        _input_error("Step28 V2 boundary integrity failed", upstream_code=exc.code)
    try:
        validate_changeset_integrity_v2(changeset, boundary)
    except ChangeSetError as exc:
        _input_error("Step29 V2 ChangeSet integrity failed", upstream_code=exc.code)


def _validate_local_lineage(
    *,
    canonical_changeset: CanonicalChangeSet,
    approval_scope_boundary: ApprovalScopeBoundaryV2,
    execution_slice: ExecutionSliceV2,
    authority: AdmittedExecutionAuthorityV2,
    actual_delta: ActualDelta,
) -> None:
    """验证 materialization/Slice/grant/binding/Host/document 的 exact join。"""
    if not isinstance(canonical_changeset, CanonicalChangeSet):
        raise TypeError("canonical_changeset must be CanonicalChangeSet")
    if not isinstance(approval_scope_boundary, ApprovalScopeBoundaryV2):
        raise TypeError("approval_scope_boundary must be ApprovalScopeBoundaryV2")
    if not isinstance(execution_slice, ExecutionSliceV2):
        raise TypeError("execution_slice must be ExecutionSliceV2")
    if not isinstance(authority, AdmittedExecutionAuthorityV2):
        raise TypeError("authority must be AdmittedExecutionAuthorityV2")
    if not isinstance(actual_delta, ActualDelta):
        raise TypeError("actual_delta must be ActualDelta")

    _validate_owner_truth(canonical_changeset, approval_scope_boundary)
    validate_actual_delta_integrity(actual_delta)

    if (
        execution_slice.materialization_id != authority.materialization_id
        or execution_slice.materialization_plan_hash
        != authority.materialization_plan_hash
        or execution_slice.execution_slice_hash != authority.execution_slice_hash
        or execution_slice.changeset_hash != authority.changeset_hash
        or execution_slice.approved_scope_ref.scope_hash
        != authority.approved_scope_hash
        or execution_slice.host_runtime_ref.host_instance_id
        != authority.host_instance_id
    ):
        _lineage_error("ExecutionSliceV2 does not match admitted materialization authority")
    if (
        canonical_changeset.changeset_hash != authority.changeset_hash
        or approval_scope_boundary.changeset_hash != authority.changeset_hash
        or approval_scope_boundary.scope_hash != authority.approved_scope_hash
    ):
        _lineage_error("Step28/29 V2 lineage does not match admitted authority")

    joins = (
        ("grant_hash", authority.grant_hash, actual_delta.grant_hash),
        ("binding_set_hash", authority.binding_set_hash, actual_delta.binding_set_hash),
        (
            "execution_slice_hash",
            authority.execution_slice_hash,
            actual_delta.execution_slice_hash,
        ),
        ("changeset_hash", authority.changeset_hash, actual_delta.changeset_hash),
        (
            "approved_scope_hash",
            authority.approved_scope_hash,
            actual_delta.approved_scope_hash,
        ),
        ("host_instance_id", authority.host_instance_id, actual_delta.host_instance_id),
    )
    for field_name, expected, actual in joins:
        if expected != actual:
            _lineage_error(f"V2 authority and ActualDelta {field_name} differ")
    if execution_slice.host_runtime_ref.document_ref != actual_delta.document_ref:
        _lineage_error("ExecutionSliceV2 document does not match ActualDelta document")

    unit_hashes = {
        item.execution_unit_hash for item in execution_slice.execution_units
    }
    for change in actual_delta.changes:
        source_hash = change.source_execution_unit_hash
        if source_hash is not None and source_hash not in unit_hashes:
            _lineage_error(
                "ActualChange source_execution_unit_hash is outside admitted SliceV2"
            )


def _resolve_slice_scope(
    boundary: ApprovalScopeBoundaryV2,
    execution_slice: ExecutionSliceV2,
):
    """解析 V2 Slice 已冻结的 exact document scope rule。"""
    scope_rule_id = execution_slice.approved_scope_ref.execution_slice_scope_rule_id
    candidates = tuple(
        item
        for item in boundary.execution_slice_scopes
        if item.slice_scope_rule_id == scope_rule_id
        and item.document_ref == execution_slice.host_runtime_ref.document_ref
    )
    if len(candidates) != 1:
        _input_error("exact Step28 V2 ExecutionSliceScopeRule cannot be resolved")
    return candidates[0]


def _evaluate_scope(
    boundary: ApprovalScopeBoundaryV2,
    execution_slice: ExecutionSliceV2,
    actual_delta: ActualDelta,
) -> ScopeComparisonResult:
    """调用 V1/V2 共享的 provider-neutral scope 效果判断。"""
    return _evaluate_scope_effects(
        boundary=boundary,
        execution_slice=execution_slice,
        actual_delta=actual_delta,
        slice_scope=_resolve_slice_scope(boundary, execution_slice),
    )


@dataclass(frozen=True, slots=True)
class _VerificationContextV2:
    """只承载共享 semantic evaluator 需要的 provider-neutral 字段。"""

    admitted_execution_authority: AdmittedExecutionAuthorityV2
    approval_scope_boundary: ApprovalScopeBoundaryV2
    canonical_changeset: CanonicalChangeSet
    actual_delta: ActualDelta
    validation_tasks: tuple[ValidationTask, ...]
    verification_evidence_bundle: VerificationEvidenceBundle
    verified_at: str


def _evaluate_semantics(context: _VerificationContextV2) -> SemanticVerificationResult:
    """调用 V1/V2 共享的 provider-neutral semantic evaluator。"""
    return _evaluate_semantic_verification(context)


class ExecutionReconciliationServiceV2:
    """把 Saga V2 CAS facade 与 provider-neutral 本地 evaluator 组合在一起。"""

    def __init__(self, *, store) -> None:
        self._controller = ExecutionSagaControllerV2(store)

    def create_saga(
        self,
        changeset: CanonicalChangeSet,
        boundary: ApprovalScopeBoundaryV2,
        materialization_plan: MaterializationPlan,
        execution_plan: ExecutionPlanV2,
    ):
        return self._controller.create_saga(
            changeset,
            boundary,
            materialization_plan,
            execution_plan,
        )

    def get_saga(self, saga_id: str):
        return self._controller.get_saga(saga_id)

    def reserve_slice_admission(self, *args, **kwargs):
        return self._controller.reserve_slice_admission(*args, **kwargs)

    def confirm_slice_admitted(self, *args, **kwargs):
        return self._controller.confirm_slice_admitted(*args, **kwargs)

    def record_host_commit(self, *args, **kwargs):
        return self._controller.record_host_commit(*args, **kwargs)

    def begin_reconciliation(self, *args, **kwargs):
        return self._controller.begin_reconciliation(*args, **kwargs)

    def record_scope_result(self, *args, **kwargs):
        return self._controller.record_scope_result(*args, **kwargs)

    def record_verification_result(self, *args, **kwargs):
        return self._controller.record_verification_result(*args, **kwargs)

    def fail_slice_before_commit(self, *args, **kwargs):
        return self._controller.fail_slice_before_commit(*args, **kwargs)

    def record_convergence_outcome(self, *args, **kwargs):
        return self._controller.record_convergence_outcome(*args, **kwargs)

    def compare_scope(
        self,
        *,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundaryV2,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        actual_delta: ActualDelta,
    ) -> ScopeComparisonResult:
        _validate_local_lineage(
            canonical_changeset=canonical_changeset,
            approval_scope_boundary=approval_scope_boundary,
            execution_slice=execution_slice,
            authority=authority,
            actual_delta=actual_delta,
        )
        return _evaluate_scope(
            approval_scope_boundary,
            execution_slice,
            actual_delta,
        )

    def verify_semantics(
        self,
        *,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundaryV2,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        actual_delta: ActualDelta,
        validation_tasks: tuple[ValidationTask, ...],
        verification_evidence_bundle: VerificationEvidenceBundle,
        verified_at: str,
    ) -> SemanticVerificationResult:
        _validate_local_lineage(
            canonical_changeset=canonical_changeset,
            approval_scope_boundary=approval_scope_boundary,
            execution_slice=execution_slice,
            authority=authority,
            actual_delta=actual_delta,
        )
        if not isinstance(verification_evidence_bundle, VerificationEvidenceBundle):
            raise TypeError(
                "verification_evidence_bundle must be VerificationEvidenceBundle"
            )
        tasks = tuple(validation_tasks)
        if any(not isinstance(item, ValidationTask) for item in tasks):
            raise TypeError("validation_tasks must contain ValidationTask values")
        if not isinstance(verified_at, str) or not verified_at.strip():
            raise ValueError("verified_at is required")
        context = _VerificationContextV2(
            admitted_execution_authority=authority,
            approval_scope_boundary=approval_scope_boundary,
            canonical_changeset=canonical_changeset,
            actual_delta=actual_delta,
            validation_tasks=tuple(
                sorted(tasks, key=lambda item: item.validation_task_id)
            ),
            verification_evidence_bundle=verification_evidence_bundle,
            verified_at=verified_at.strip(),
        )
        return _evaluate_semantics(context)


__all__ = ["ExecutionReconciliationServiceV2"]
