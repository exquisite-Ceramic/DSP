"""Phase I materialized Step37 的确定性串行协调器。"""

from __future__ import annotations

from collections.abc import Sequence

from design_approval_scope import (
    ApprovalScopeBoundaryV2,
    ApprovalScopeError,
    validate_approval_scope_boundary_v2,
)
from design_changeset import (
    CanonicalChangeSet,
    ChangeSetError,
    validate_changeset_integrity_v2,
)
from design_convergence import (
    ConvergenceComparisonProfile,
    ConvergenceStatus,
    build_convergence_evidence_set,
    compute_convergence_profile_hash,
)
from design_execution_planning import ExecutionPlanV2, ExecutionSliceV2
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    SagaConvergenceOutcome,
    ScopeComparisonStatus,
    SliceReconciliationStatusV2,
    VerificationStatus,
)
from design_gateway_authorization import AdmittedExecutionAuthorityV2
from design_materialization_planning import (
    MaterializationPlan,
    compute_materialization_intent_hash,
    compute_materialization_plan_hash,
    compute_required_set_hash,
)
from design_provider_binding import (
    ProviderBindingError,
    ProviderBindingSetV2,
    validate_cross_materialization_identity,
    validate_provider_binding_set_v2,
)

from .contracts import (
    CoordinationError,
    HostCommitted,
    HostFailed,
    HostFailurePhase,
)
from .materialized_contracts import (
    MaterializedCoordinationResult,
    MaterializedCoordinationStatus,
)
from .readiness_contracts import ReadinessBarrierStatus

_ACTIVE_SLICE_STATUSES = frozenset(
    {
        SliceReconciliationStatusV2.ADMISSION_RESERVED,
        SliceReconciliationStatusV2.ADMITTED,
        SliceReconciliationStatusV2.HOST_COMMITTED,
        SliceReconciliationStatusV2.RECONCILING,
    }
)
_TERMINAL_STATUS_MAP = {
    ExecutionSagaStatusV2.SUCCEEDED: MaterializedCoordinationStatus.SUCCEEDED,
    ExecutionSagaStatusV2.FAILED: MaterializedCoordinationStatus.FAILED,
    ExecutionSagaStatusV2.PARTIALLY_COMMITTED: (
        MaterializedCoordinationStatus.PARTIALLY_COMMITTED
    ),
    ExecutionSagaStatusV2.DIVERGED: MaterializedCoordinationStatus.DIVERGED,
}


def _error(code: str, message: str) -> None:
    """统一抛出 materialized Step37 协调错误。"""
    raise CoordinationError(code, message)


def _validate_owner_truth(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundaryV2,
) -> None:
    """在任何 readiness/Host 调用前验证 Step28/29 V2 owner 真相。"""
    if not isinstance(changeset, CanonicalChangeSet):
        raise TypeError("canonical_changeset must be CanonicalChangeSet")
    if not isinstance(boundary, ApprovalScopeBoundaryV2):
        raise TypeError("approval_scope_boundary must be ApprovalScopeBoundaryV2")
    try:
        validate_approval_scope_boundary_v2(boundary)
        validate_changeset_integrity_v2(changeset, boundary)
    except (ApprovalScopeError, ChangeSetError) as exc:
        _error(
            "MATERIALIZATION_PLAN_HASH_MISMATCH",
            f"Step28/29 V2 owner integrity failed: {exc.code}",
        )


def _validate_materialization_plan(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundaryV2,
    plan: MaterializationPlan,
    profile: ConvergenceComparisonProfile,
) -> None:
    """重算 Task5/Task4 owner hash 并验证计划 lineage。"""
    if not isinstance(plan, MaterializationPlan):
        raise TypeError("materialization_plan must be MaterializationPlan")
    if not isinstance(profile, ConvergenceComparisonProfile):
        raise TypeError("convergence_profile must be ConvergenceComparisonProfile")

    for intent in plan.intents:
        if intent.intent_hash != compute_materialization_intent_hash(intent):
            _error(
                "MATERIALIZATION_PLAN_HASH_MISMATCH",
                "materialization intent hash is invalid",
            )
    expected_required = compute_required_set_hash(plan.intents)
    if plan.required_set_hash != expected_required:
        _error(
            "MATERIALIZATION_REQUIRED_SET_MISMATCH",
            "materialization required-set hash is invalid",
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
            "MATERIALIZATION_PLAN_HASH_MISMATCH",
            "materialization plan hash is invalid",
        )
    expected_profile = compute_convergence_profile_hash(
        profile.profile_version,
        profile.field_rules,
    )
    if profile.profile_hash != expected_profile:
        _error(
            "CONVERGENCE_PROFILE_MISMATCH",
            "convergence profile hash is invalid",
        )
    if (
        plan.changeset_hash != changeset.changeset_hash
        or plan.approved_scope_hash != boundary.scope_hash
    ):
        _error(
            "MATERIALIZATION_PLAN_HASH_MISMATCH",
            "materialization plan does not join Step28/29 V2",
        )
    if plan.convergence_profile_hash != profile.profile_hash:
        _error(
            "CONVERGENCE_PROFILE_MISMATCH",
            "materialization plan does not bind the supplied convergence profile",
        )


def _slice_index(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundaryV2,
    plan: MaterializationPlan,
    execution_plan: ExecutionPlanV2,
) -> dict[str, ExecutionSliceV2]:
    """验证 Task5→Step30 V2 的 closed-world materialization 投影。"""
    if not isinstance(execution_plan, ExecutionPlanV2):
        raise TypeError("execution_plan must be ExecutionPlanV2")
    if (
        execution_plan.changeset_hash != changeset.changeset_hash
        or execution_plan.approval_scope_ref.scope_hash != boundary.scope_hash
        or execution_plan.materialization_plan_hash != plan.materialization_plan_hash
        or execution_plan.required_set_hash != plan.required_set_hash
        or execution_plan.convergence_profile_hash != plan.convergence_profile_hash
    ):
        _error(
            "MATERIALIZATION_PLAN_HASH_MISMATCH",
            "ExecutionPlanV2 lineage differs from immutable materialization plan",
        )
    if execution_plan.ordering_policy != "stable_host_type_then_slot.v1":
        _error(
            "MATERIALIZATION_PLAN_HASH_MISMATCH",
            "ExecutionPlanV2 ordering policy differs from Phase I frozen order",
        )

    intents = {item.materialization_id: item for item in plan.intents}
    supplied = tuple(execution_plan.execution_slices)
    supplied_ids = tuple(item.materialization_id for item in supplied)
    if (
        len(supplied_ids) != len(set(supplied_ids))
        or set(supplied_ids) != set(intents)
    ):
        _error(
            "MATERIALIZATION_REQUIRED_SET_MISMATCH",
            "ExecutionPlanV2 does not exactly cover the required materialization set",
        )

    result: dict[str, ExecutionSliceV2] = {}
    for execution_slice in supplied:
        if not isinstance(execution_slice, ExecutionSliceV2):
            raise TypeError("execution_plan must contain ExecutionSliceV2 values")
        intent = intents[execution_slice.materialization_id]
        if (
            execution_slice.materialization_plan_hash != plan.materialization_plan_hash
            or execution_slice.materialization_slot_id != intent.materialization_slot_id
            or execution_slice.host_runtime_ref.host_type != intent.required_host_type
            or execution_slice.changeset_hash != changeset.changeset_hash
            or execution_slice.approved_scope_ref.scope_hash != boundary.scope_hash
            or len(execution_slice.execution_units) != 1
        ):
            _error(
                "MATERIALIZATION_PLAN_HASH_MISMATCH",
                f"ExecutionSliceV2 lineage mismatch for {execution_slice.materialization_id}",
            )
        unit = execution_slice.execution_units[0]
        if (
            unit.materialization_id != intent.materialization_id
            or unit.materialization_plan_hash != plan.materialization_plan_hash
            or unit.materialization_slot_id != intent.materialization_slot_id
            or unit.required_host_type != intent.required_host_type
            or tuple(unit.targets) != tuple(intent.semantic_targets)
        ):
            _error(
                "MATERIALIZATION_PLAN_HASH_MISMATCH",
                f"ExecutionUnitV2 differs from intent {intent.materialization_id}",
            )
        result[execution_slice.materialization_id] = execution_slice
    return result


def _binding_index(
    plan: MaterializationPlan,
    slices: dict[str, ExecutionSliceV2],
    binding_sets: Sequence[ProviderBindingSetV2],
) -> dict[str, ProviderBindingSetV2]:
    """在 readiness 前验证 Step31 V2 closed-world binding identity。"""
    normalized = tuple(binding_sets)
    if any(not isinstance(item, ProviderBindingSetV2) for item in normalized):
        raise TypeError("binding_sets must contain ProviderBindingSetV2 values")
    try:
        validate_cross_materialization_identity(plan, normalized)
    except ProviderBindingError as exc:
        _error(
            "MATERIALIZATION_BINDING_MISMATCH",
            f"cross-materialization binding validation failed: {exc.code}",
        )
    result = {item.materialization_id: item for item in normalized}
    if len(result) != len(normalized):
        _error(
            "MATERIALIZATION_BINDING_MISMATCH",
            "duplicate materialization binding sets are forbidden",
        )
    for materialization_id, binding_set in result.items():
        execution_slice = slices.get(materialization_id)
        if execution_slice is None:
            _error(
                "MATERIALIZATION_BINDING_MISMATCH",
                f"binding set is outside required set: {materialization_id}",
            )
        try:
            validate_provider_binding_set_v2(binding_set, execution_slice)
        except ProviderBindingError as exc:
            _error(
                "MATERIALIZATION_BINDING_MISMATCH",
                f"provider binding set validation failed: {exc.code}",
            )
    return result


def _authority_index(
    plan: MaterializationPlan,
    slices: dict[str, ExecutionSliceV2],
    bindings: dict[str, ProviderBindingSetV2],
    authorities: Sequence[AdmittedExecutionAuthorityV2],
) -> dict[str, AdmittedExecutionAuthorityV2]:
    """验证 Step32 V2 authority 与 exact Slice/binding/Host lineage。"""
    normalized = tuple(authorities)
    if any(not isinstance(item, AdmittedExecutionAuthorityV2) for item in normalized):
        raise TypeError("authorities must contain AdmittedExecutionAuthorityV2 values")
    supplied_ids = tuple(item.materialization_id for item in normalized)
    expected_ids = {intent.materialization_id for intent in plan.intents}
    if (
        len(supplied_ids) != len(set(supplied_ids))
        or set(supplied_ids) != expected_ids
    ):
        _error(
            "MATERIALIZATION_AUTHORITY_MISMATCH",
            "authorities do not exactly cover the required materialization set",
        )
    result = {item.materialization_id: item for item in normalized}
    for materialization_id, authority in result.items():
        execution_slice = slices[materialization_id]
        binding_set = bindings[materialization_id]
        if (
            authority.materialization_plan_hash != plan.materialization_plan_hash
            or authority.changeset_hash != plan.changeset_hash
            or authority.approved_scope_hash != plan.approved_scope_hash
            or authority.execution_slice_hash != execution_slice.execution_slice_hash
            or authority.binding_set_hash != binding_set.binding_set_hash
            or authority.host_instance_id
            != execution_slice.host_runtime_ref.host_instance_id
        ):
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                f"authority lineage mismatch for {materialization_id}",
            )
    return result


def _assigned_tasks(definition, changeset, execution_slice_hash: str):
    """从 Saga V2 definition 解析当前 materialization 的 exact Step29 tasks。"""
    assignments = tuple(
        item
        for item in definition.slice_validation_assignments
        if item.execution_slice_hash == execution_slice_hash
    )
    if len(assignments) != 1:
        _error(
            "SAGA_INTEGRITY_INVALID",
            "Slice validation assignment is unresolved",
        )
    tasks_by_id = {
        item.validation_task_id: item for item in changeset.validation_tasks
    }
    try:
        return tuple(
            tasks_by_id[task_id]
            for task_id in assignments[0].validation_task_ids
        )
    except KeyError as exc:
        _error(
            "SAGA_INTEGRITY_INVALID",
            f"Saga validation assignment references unknown task {exc.args[0]}",
        )


def _result(
    stored,
    status: MaterializedCoordinationStatus,
    *,
    active_slice_hash: str | None = None,
    failure_ref: str | None = None,
    convergence_result_hash: str | None = None,
) -> MaterializedCoordinationResult:
    """从 durable Saga V2 revision 构造 materialized coordination result。"""
    return MaterializedCoordinationResult(
        saga_id=stored.definition.saga_id,
        saga_revision=stored.saga_revision,
        status=status,
        active_slice_hash=active_slice_hash,
        failure_ref=failure_ref,
        convergence_result_hash=convergence_result_hash,
    )


def _terminal_result(stored, failure_ref: str | None = None):
    """把已持久化的 Saga V2 终态投影到独立 materialized surface。"""
    status = _TERMINAL_STATUS_MAP.get(stored.status)
    if status is None:
        return None
    return _result(
        stored,
        status,
        failure_ref=failure_ref,
        convergence_result_hash=stored.convergence_result_hash,
    )


class MaterializedExecutionSagaCoordinator:
    """顺序协调 Phase I REQUIRED materializations，不拥有 Host/Step33 语义。"""

    def __init__(
        self,
        *,
        readiness_barrier,
        reconciliation,
        host_registry,
        evidence_port,
        convergence_verifier,
        clock,
    ) -> None:
        for name, value, method in (
            ("readiness_barrier", readiness_barrier, "check_all"),
            ("reconciliation", reconciliation, "create_saga"),
            ("host_registry", host_registry, "resolve"),
            ("evidence_port", evidence_port, "build_bundle"),
            ("convergence_verifier", convergence_verifier, "verify"),
            ("clock", clock, "now"),
        ):
            if value is None or not callable(getattr(value, method, None)):
                raise TypeError(f"{name} must provide {method}")
        if not callable(getattr(evidence_port, "build_evidence", None)):
            raise TypeError("evidence_port must provide build_evidence")
        self._readiness_barrier = readiness_barrier
        self._reconciliation = reconciliation
        self._host_registry = host_registry
        self._evidence_port = evidence_port
        self._convergence_verifier = convergence_verifier
        self._clock = clock

    def execute(
        self,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundaryV2,
        materialization_plan: MaterializationPlan,
        execution_plan: ExecutionPlanV2,
        binding_sets: Sequence[ProviderBindingSetV2],
        authorities: Sequence[AdmittedExecutionAuthorityV2],
        convergence_profile: ConvergenceComparisonProfile,
    ) -> MaterializedCoordinationResult:
        """按 readiness→Host→Step33→convergence 的冻结顺序执行 Phase I Saga。"""
        _validate_owner_truth(canonical_changeset, approval_scope_boundary)
        _validate_materialization_plan(
            canonical_changeset,
            approval_scope_boundary,
            materialization_plan,
            convergence_profile,
        )
        slices = _slice_index(
            canonical_changeset,
            approval_scope_boundary,
            materialization_plan,
            execution_plan,
        )
        bindings = _binding_index(materialization_plan, slices, binding_sets)
        admitted = _authority_index(
            materialization_plan,
            slices,
            bindings,
            authorities,
        )

        readiness = self._readiness_barrier.check_all(
            materialization_plan,
            execution_plan,
            tuple(binding_sets),
            tuple(authorities),
        )
        if readiness.status is ReadinessBarrierStatus.NOT_READY:
            return MaterializedCoordinationResult(
                saga_id="NOT_CREATED",
                saga_revision=0,
                status=MaterializedCoordinationStatus.READINESS_FAILED,
                active_slice_hash=None,
                failure_ref=readiness.failure_ref,
                convergence_result_hash=None,
            )
        if readiness.status is not ReadinessBarrierStatus.READY:
            _error("READINESS_FAILED", "readiness barrier returned an invalid status")

        stored = self._reconciliation.create_saga(
            canonical_changeset,
            approval_scope_boundary,
            materialization_plan,
            execution_plan,
        )
        definition = stored.definition
        if (
            definition.changeset_hash != canonical_changeset.changeset_hash
            or definition.approved_scope_hash != approval_scope_boundary.scope_hash
            or definition.materialization_plan_hash
            != materialization_plan.materialization_plan_hash
            or definition.required_set_hash != materialization_plan.required_set_hash
            or definition.execution_plan_hash != execution_plan.execution_plan_hash
        ):
            _error(
                "SAGA_INTEGRITY_INVALID",
                "Saga V2 definition does not join supplied materialized execution lineage",
            )

        terminal = _terminal_result(stored)
        if terminal is not None:
            return terminal
        active = tuple(
            state
            for state in stored.slice_states
            if state.status in _ACTIVE_SLICE_STATUSES
        )
        if active:
            return _result(
                stored,
                MaterializedCoordinationStatus.RECOVERY_REQUIRED,
                active_slice_hash=active[0].execution_slice_hash,
            )
        if stored.status is not ExecutionSagaStatusV2.READY:
            return _result(
                stored,
                MaterializedCoordinationStatus.RECOVERY_REQUIRED,
                failure_ref="MATERIALIZED_FORWARD_RESUME_REQUIRES_EVIDENCE",
            )

        evidence_items = []
        for execution_slice in execution_plan.execution_slices:
            materialization_id = execution_slice.materialization_id
            binding_set = bindings[materialization_id]
            authority = admitted[materialization_id]
            stored = self._reconciliation.reserve_slice_admission(
                definition.saga_id,
                execution_slice.execution_slice_hash,
                expected_revision=stored.saga_revision,
                reserved_at=self._clock.now(),
            )
            stored = self._reconciliation.confirm_slice_admitted(
                definition.saga_id,
                authority,
                expected_revision=stored.saga_revision,
            )

            host_port = self._host_registry.resolve(execution_slice.host_runtime_ref)
            if host_port is None or not callable(getattr(host_port, "execute", None)):
                _error("HOST_RESULT_INVALID", "materialized Host execution port is unavailable")
            host_result = host_port.execute(execution_slice, authority, binding_set)
            if isinstance(host_result, HostFailed):
                if host_result.phase is HostFailurePhase.COMMIT_STATE_UNKNOWN:
                    return _result(
                        stored,
                        MaterializedCoordinationStatus.RECOVERY_REQUIRED,
                        active_slice_hash=execution_slice.execution_slice_hash,
                        failure_ref=host_result.failure_ref,
                    )
                if host_result.phase is HostFailurePhase.BEFORE_COMMIT:
                    stored = self._reconciliation.fail_slice_before_commit(
                        definition.saga_id,
                        execution_slice.execution_slice_hash,
                        expected_revision=stored.saga_revision,
                        failed_at=host_result.failed_at,
                    )
                    terminal = _terminal_result(stored, host_result.failure_ref)
                    if terminal is None:
                        _error(
                            "SAGA_INTEGRITY_INVALID",
                            "pre-commit failure did not produce a terminal Saga V2 state",
                        )
                    return terminal
                _error("HOST_RESULT_INVALID", "unsupported Host failure phase")
            if not isinstance(host_result, HostCommitted):
                _error("HOST_RESULT_INVALID", "Host execution returned an invalid result")

            actual_delta = host_result.actual_delta
            stored = self._reconciliation.record_host_commit(
                definition.saga_id,
                actual_delta,
                expected_revision=stored.saga_revision,
                committed_at=host_result.committed_at,
            )
            stored = self._reconciliation.begin_reconciliation(
                definition.saga_id,
                execution_slice.execution_slice_hash,
                expected_revision=stored.saga_revision,
            )
            scope_result = self._reconciliation.compare_scope(
                canonical_changeset=canonical_changeset,
                approval_scope_boundary=approval_scope_boundary,
                execution_slice=execution_slice,
                authority=authority,
                actual_delta=actual_delta,
            )
            stored = self._reconciliation.record_scope_result(
                definition.saga_id,
                scope_result,
                expected_revision=stored.saga_revision,
            )
            if scope_result.status is not ScopeComparisonStatus.WITHIN_SCOPE:
                terminal = _terminal_result(stored, scope_result.comparison_hash)
                if terminal is None:
                    _error(
                        "SAGA_INTEGRITY_INVALID",
                        "scope breach did not produce a terminal Saga V2 state",
                    )
                return terminal

            verification_bundle = self._evidence_port.build_bundle(
                execution_slice=execution_slice,
                actual_delta=actual_delta,
                canonical_changeset=canonical_changeset,
                approval_scope_boundary=approval_scope_boundary,
            )
            verification = self._reconciliation.verify_semantics(
                canonical_changeset=canonical_changeset,
                approval_scope_boundary=approval_scope_boundary,
                execution_slice=execution_slice,
                authority=authority,
                actual_delta=actual_delta,
                validation_tasks=_assigned_tasks(
                    definition,
                    canonical_changeset,
                    execution_slice.execution_slice_hash,
                ),
                verification_evidence_bundle=verification_bundle,
                verified_at=self._clock.now(),
            )
            stored = self._reconciliation.record_verification_result(
                definition.saga_id,
                verification,
                expected_revision=stored.saga_revision,
                reconciled_at=self._clock.now(),
            )
            if verification.status is not VerificationStatus.PASSED:
                terminal = _terminal_result(stored, verification.verification_hash)
                if terminal is None:
                    _error(
                        "SAGA_INTEGRITY_INVALID",
                        "local verification failure did not produce a terminal Saga V2 state",
                    )
                return terminal

            evidence_items.append(
                self._evidence_port.build_evidence(
                    materialization_id=materialization_id,
                    execution_slice=execution_slice,
                    actual_delta=actual_delta,
                    verification_result=verification,
                    verification_bundle=verification_bundle,
                    convergence_profile=convergence_profile,
                )
            )

        if stored.status is not ExecutionSagaStatusV2.CONVERGENCE_PENDING:
            _error(
                "SAGA_INTEGRITY_INVALID",
                "all local materializations completed without CONVERGENCE_PENDING",
            )
        evidence_set = build_convergence_evidence_set(
            plan=materialization_plan,
            profile=convergence_profile,
            evidence_items=tuple(evidence_items),
        )
        convergence = self._convergence_verifier.verify(
            materialization_plan,
            convergence_profile,
            evidence_set,
        )
        if convergence.status is ConvergenceStatus.CONVERGED:
            outcome = SagaConvergenceOutcome.CONVERGED
            failure_ref = None
        elif convergence.status is ConvergenceStatus.DIVERGED:
            outcome = SagaConvergenceOutcome.DIVERGED
            failure_ref = "CONVERGENCE_DIVERGED"
        else:
            outcome = SagaConvergenceOutcome.DIVERGED
            failure_ref = "CONVERGENCE_EVIDENCE_INSUFFICIENT"
        stored = self._reconciliation.record_convergence_outcome(
            definition.saga_id,
            outcome,
            convergence.convergence_result_hash,
            expected_revision=stored.saga_revision,
        )
        final_status = _TERMINAL_STATUS_MAP.get(stored.status)
        if final_status is None:
            _error(
                "SAGA_INTEGRITY_INVALID",
                "convergence finalization did not produce a terminal Saga V2 state",
            )
        return _result(
            stored,
            final_status,
            failure_ref=failure_ref,
            convergence_result_hash=convergence.convergence_result_hash,
        )


__all__ = ["MaterializedExecutionSagaCoordinator"]
