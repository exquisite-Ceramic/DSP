"""Phase I Step33 V2 的确定性 Saga builder 与持久控制器。"""

from __future__ import annotations

from itertools import pairwise

from design_approval_scope import (
    ApprovalScopeBoundaryV2,
    ApprovalScopeError,
    validate_approval_scope_boundary_v2,
)
from design_changeset import (
    CanonicalChangeSet,
    ChangeSetError,
    ValidationTaskKind,
    validate_changeset_integrity_v2,
)
from design_execution_planning import ExecutionPlanV2, ExecutionSliceV2
from design_materialization_planning import (
    MaterializationPlan,
    compute_materialization_plan_hash,
    compute_required_set_hash,
)
from semantic_runtime import SemanticEnvironmentRef

from .contracts import (
    ActualDelta,
    ReconciliationError,
    ScopeComparisonResult,
    SemanticVerificationResult,
)
from .saga_contracts import SliceDependency, SliceValidationAssignment
from .saga_contracts_v2 import (
    ExecutionSagaDefinitionV2,
    compute_execution_saga_definition_hash_v2,
)
from .saga_state_v2 import SagaConvergenceOutcome, StoredExecutionSagaV2


def _invalid(message: str, *, upstream_code: str | None = None) -> None:
    """统一抛出 Saga V2 不可变 lineage 错误。"""
    raise ReconciliationError(
        "SAGA_INTEGRITY_INVALID",
        message,
        upstream_code=upstream_code,
    )


def _aspect_values(values) -> tuple[str, ...]:
    """把 canonical aspect 枚举规范化为稳定字符串。"""
    return tuple(sorted(getattr(item, "value", str(item)) for item in values))


def _validate_upstream(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundaryV2,
) -> None:
    """调用 Step28/29 V2 owner validator，不复制其哈希算法。"""
    if not isinstance(changeset, CanonicalChangeSet):
        raise TypeError("changeset must be CanonicalChangeSet")
    if not isinstance(boundary, ApprovalScopeBoundaryV2):
        raise TypeError("boundary must be ApprovalScopeBoundaryV2")
    try:
        validate_approval_scope_boundary_v2(boundary)
    except ApprovalScopeError as exc:
        _invalid("Step28 V2 boundary integrity failed", upstream_code=exc.code)
    try:
        validate_changeset_integrity_v2(changeset, boundary)
    except ChangeSetError as exc:
        _invalid("Step29 V2 ChangeSet integrity failed", upstream_code=exc.code)


def _validate_materialization_plan(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundaryV2,
    plan: MaterializationPlan,
) -> None:
    """重算 Task5 owner hash，并验证计划与 Step28/29 lineage 的 exact join。"""
    if not isinstance(plan, MaterializationPlan):
        raise TypeError("materialization_plan must be MaterializationPlan")
    expected_required_set_hash = compute_required_set_hash(plan.intents)
    if plan.required_set_hash != expected_required_set_hash:
        _invalid("MaterializationPlan required_set_hash is invalid")
    expected_plan_hash = compute_materialization_plan_hash(
        changeset_hash=plan.changeset_hash,
        approved_scope_hash=plan.approved_scope_hash,
        topology_snapshot_hash=plan.topology_snapshot_hash,
        intents=plan.intents,
        required_set_hash=plan.required_set_hash,
        convergence_profile_hash=plan.convergence_profile_hash,
    )
    if plan.materialization_plan_hash != expected_plan_hash:
        _invalid("MaterializationPlan body does not match its content hash")
    if plan.changeset_hash != changeset.changeset_hash:
        _invalid("MaterializationPlan ChangeSet does not match Step29 V2")
    if plan.approved_scope_hash != boundary.scope_hash:
        _invalid("MaterializationPlan scope does not match Step28 V2")
    if plan.topology_snapshot_hash != boundary.topology_snapshot_hash:
        _invalid("MaterializationPlan topology does not match Step28 V2")


def _scope_rule(boundary: ApprovalScopeBoundaryV2, execution_slice: ExecutionSliceV2):
    """解析 Slice 已冻结的 exact document-scoped Step28 rule。"""
    rule_id = execution_slice.approved_scope_ref.execution_slice_scope_rule_id
    candidates = tuple(
        item
        for item in boundary.execution_slice_scopes
        if item.slice_scope_rule_id == rule_id
        and item.document_ref == execution_slice.host_runtime_ref.document_ref
    )
    if len(candidates) != 1:
        _invalid("ExecutionSliceV2 exact Step28 scope rule is unresolved")
    return candidates[0]


def _validate_execution_plan(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundaryV2,
    materialization_plan: MaterializationPlan,
    execution_plan: ExecutionPlanV2,
) -> None:
    """不复制 Step30 hash 算法，只验证 closed-world materialization/Slice lineage。"""
    if not isinstance(execution_plan, ExecutionPlanV2):
        raise TypeError("execution_plan must be ExecutionPlanV2")
    if execution_plan.changeset_id != changeset.changeset_id:
        _invalid("ExecutionPlanV2 changeset_id does not match Step29 V2")
    if execution_plan.changeset_hash != changeset.changeset_hash:
        _invalid("ExecutionPlanV2 ChangeSet hash does not match Step29 V2")
    if (
        execution_plan.approval_scope_ref.scope_id != boundary.scope_id
        or execution_plan.approval_scope_ref.scope_hash != boundary.scope_hash
    ):
        _invalid("ExecutionPlanV2 approved scope does not match Step28 V2")
    if execution_plan.materialization_plan_hash != materialization_plan.materialization_plan_hash:
        _invalid("ExecutionPlanV2 materialization plan hash differs")
    if execution_plan.required_set_hash != materialization_plan.required_set_hash:
        _invalid("ExecutionPlanV2 required set hash differs")
    if execution_plan.convergence_profile_hash != materialization_plan.convergence_profile_hash:
        _invalid("ExecutionPlanV2 convergence profile hash differs")
    if execution_plan.topology_snapshot_hash != materialization_plan.topology_snapshot_hash:
        _invalid("ExecutionPlanV2 topology hash differs")
    if execution_plan.ordering_policy != "stable_host_type_then_slot.v1":
        _invalid("ExecutionPlanV2 ordering policy is not the frozen Phase I policy")

    intents = {item.materialization_id: item for item in materialization_plan.intents}
    if len(intents) != len(materialization_plan.intents):
        _invalid("MaterializationPlan contains duplicate materialization ids")
    slices = tuple(execution_plan.execution_slices)
    if len(slices) != len(intents):
        _invalid("ExecutionPlanV2 must contain exactly one Slice per materialization")
    seen: set[str] = set()
    operations = {
        item.operation_id: item
        for item in (changeset.root_operation, *changeset.derived_operations)
    }
    for execution_slice in slices:
        if not isinstance(execution_slice, ExecutionSliceV2):
            raise TypeError("execution_plan contains non-ExecutionSliceV2 values")
        intent = intents.get(execution_slice.materialization_id)
        if intent is None or execution_slice.materialization_id in seen:
            _invalid("ExecutionPlanV2 materialization coverage is not exact")
        seen.add(execution_slice.materialization_id)
        if execution_slice.materialization_plan_hash != materialization_plan.materialization_plan_hash:
            _invalid("ExecutionSliceV2 materialization plan hash differs")
        if execution_slice.materialization_slot_id != intent.materialization_slot_id:
            _invalid("ExecutionSliceV2 materialization slot differs from Task5 intent")
        if execution_slice.host_runtime_ref.host_type != intent.required_host_type:
            _invalid("ExecutionSliceV2 Host type differs from Task5 intent")
        if (
            execution_slice.changeset_id != changeset.changeset_id
            or execution_slice.changeset_hash != changeset.changeset_hash
        ):
            _invalid("ExecutionSliceV2 does not join the exact Step29 V2 ChangeSet")
        if execution_slice.approved_scope_ref.scope_hash != boundary.scope_hash:
            _invalid("ExecutionSliceV2 does not join the exact Step28 V2 scope")
        scope_rule = _scope_rule(boundary, execution_slice)
        if len(execution_slice.execution_units) != 1:
            _invalid("Phase I ExecutionSliceV2 requires exactly one execution unit")
        unit = execution_slice.execution_units[0]
        operation = operations.get(unit.source_operation_id)
        if operation is None:
            _invalid("ExecutionUnitV2 source operation is unresolved")
        if (
            unit.materialization_id != intent.materialization_id
            or unit.materialization_plan_hash != materialization_plan.materialization_plan_hash
            or unit.materialization_slot_id != intent.materialization_slot_id
            or unit.required_host_type != intent.required_host_type
            or unit.source_operation_id != intent.source_operation_id
            or unit.source_operation_hash != intent.source_operation_hash
            or tuple(unit.targets) != tuple(intent.semantic_targets)
            or _aspect_values(unit.expected_effects) != tuple(intent.expected_effects)
        ):
            _invalid("ExecutionUnitV2 does not exactly project its Task5 intent")
        if (
            unit.canonical_operation != operation.canonical_operation
            or unit.canonical_operation_version != operation.canonical_operation_version
            or unit.canonical_definition_fingerprint
            != operation.canonical_definition_fingerprint
            or tuple(unit.targets) != tuple(operation.targets)
            or dict(unit.arguments) != dict(operation.arguments)
        ):
            _invalid("ExecutionUnitV2 semantic body differs from Step29 V2 operation")
        allowed_rule_ids = {
            *scope_rule.existing_rule_ids,
            *scope_rule.creation_rule_ids,
            *scope_rule.deletion_rule_ids,
        }
        if set(unit.scope_rule_ids) != allowed_rule_ids:
            _invalid("ExecutionUnitV2 scope authority differs from exact Slice scope rule")
    if seen != set(intents):
        _invalid("ExecutionPlanV2 does not cover the immutable required set")


def _validation_assignments(
    changeset: CanonicalChangeSet,
    execution_plan: ExecutionPlanV2,
) -> tuple[SliceValidationAssignment, ...]:
    """把同一 canonical operation 的本地验证任务复制到每个 REQUIRED materialization。"""
    tasks_by_slice: dict[str, list[str]] = {
        item.execution_slice_hash: [] for item in execution_plan.execution_slices
    }
    covered_task_ids: set[str] = set()
    for task in changeset.validation_tasks:
        matched_slices: list[str] = []
        for execution_slice in execution_plan.execution_slices:
            unit = execution_slice.execution_units[0]
            if task.kind is ValidationTaskKind.CANONICAL_OPERATION:
                matches = (
                    task.canonical_operation_ref
                    == f"{unit.canonical_operation}@{unit.canonical_operation_version}"
                    and tuple(task.subject_semantic_ids) == tuple(unit.targets)
                )
            else:
                matches = set(task.subject_semantic_ids).issubset(set(unit.targets))
            if matches:
                matched_slices.append(execution_slice.execution_slice_hash)
        if not matched_slices:
            _invalid(
                f"ValidationTask {task.validation_task_id} has no local materialization owner"
            )
        covered_task_ids.add(task.validation_task_id)
        for slice_hash in matched_slices:
            tasks_by_slice[slice_hash].append(task.validation_task_id)
    if covered_task_ids != {
        item.validation_task_id for item in changeset.validation_tasks
    }:
        _invalid("not every Step29 V2 ValidationTask has a local Slice assignment")
    return tuple(
        SliceValidationAssignment(
            execution_slice_hash=execution_slice.execution_slice_hash,
            validation_task_ids=tuple(
                sorted(tasks_by_slice[execution_slice.execution_slice_hash])
            ),
        )
        for execution_slice in execution_plan.execution_slices
    )


def _dependencies(execution_plan: ExecutionPlanV2) -> tuple[SliceDependency, ...]:
    """把 Step30 V2 冻结顺序投影成严格串行 materialization 依赖。"""
    hashes = tuple(
        item.execution_slice_hash for item in execution_plan.execution_slices
    )
    return tuple(
        SliceDependency(
            predecessor_slice_hash=predecessor,
            successor_slice_hash=successor,
            reason_refs=("MATERIALIZATION_ORDER",),
        )
        for predecessor, successor in pairwise(hashes)
    )


class ExecutionSagaBuilderV2:
    """从冻结 Steps 28–30 与 Task5 plan 构造不可变 Saga V2 定义。"""

    def build(
        self,
        changeset: CanonicalChangeSet,
        boundary: ApprovalScopeBoundaryV2,
        materialization_plan: MaterializationPlan,
        execution_plan: ExecutionPlanV2,
    ) -> ExecutionSagaDefinitionV2:
        _validate_upstream(changeset, boundary)
        _validate_materialization_plan(changeset, boundary, materialization_plan)
        _validate_execution_plan(
            changeset,
            boundary,
            materialization_plan,
            execution_plan,
        )
        environment = changeset.semantic_environment_ref
        semantic_environment_ref = SemanticEnvironmentRef(
            environment.environment_id,
            environment.content_hash,
        )
        draft = ExecutionSagaDefinitionV2(
            saga_id="SGV2-DRAFT",
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
            semantic_environment_ref=semantic_environment_ref,
            materialization_plan_hash=materialization_plan.materialization_plan_hash,
            required_set_hash=materialization_plan.required_set_hash,
            execution_plan_hash=execution_plan.execution_plan_hash,
            ordered_slice_hashes=tuple(
                item.execution_slice_hash for item in execution_plan.execution_slices
            ),
            slice_dependencies=_dependencies(execution_plan),
            slice_validation_assignments=_validation_assignments(
                changeset,
                execution_plan,
            ),
            saga_definition_hash="0" * 64,
        )
        definition_hash = compute_execution_saga_definition_hash_v2(draft)
        return ExecutionSagaDefinitionV2(
            saga_id=f"SGV2-{definition_hash[:12]}",
            changeset_hash=draft.changeset_hash,
            approved_scope_hash=draft.approved_scope_hash,
            semantic_environment_ref=draft.semantic_environment_ref,
            materialization_plan_hash=draft.materialization_plan_hash,
            required_set_hash=draft.required_set_hash,
            execution_plan_hash=draft.execution_plan_hash,
            ordered_slice_hashes=draft.ordered_slice_hashes,
            slice_dependencies=draft.slice_dependencies,
            slice_validation_assignments=draft.slice_validation_assignments,
            saga_definition_hash=definition_hash,
        )


class ExecutionSagaControllerV2:
    """只编排 Saga V2 builder/store，不执行 Host 或 convergence 判断。"""

    def __init__(self, store, builder: ExecutionSagaBuilderV2 | None = None) -> None:
        if store is None:
            raise TypeError("store is required")
        self._store = store
        self._builder = builder or ExecutionSagaBuilderV2()

    def create_saga(
        self,
        changeset: CanonicalChangeSet,
        boundary: ApprovalScopeBoundaryV2,
        materialization_plan: MaterializationPlan,
        execution_plan: ExecutionPlanV2,
    ) -> StoredExecutionSagaV2:
        definition = self._builder.build(
            changeset,
            boundary,
            materialization_plan,
            execution_plan,
        )
        return self._store.create_saga(definition)

    def get_saga(self, saga_id: str) -> StoredExecutionSagaV2 | None:
        return self._store.get_saga(saga_id)

    def reserve_slice_admission(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        reserved_at: str,
    ) -> StoredExecutionSagaV2:
        return self._store.reserve_slice_admission(
            saga_id,
            execution_slice_hash,
            expected_revision=expected_revision,
            reserved_at=reserved_at,
        )

    def confirm_slice_admitted(
        self,
        saga_id: str,
        authority,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        return self._store.confirm_slice_admitted(
            saga_id,
            authority,
            expected_revision=expected_revision,
        )

    def record_host_commit(
        self,
        saga_id: str,
        actual_delta: ActualDelta,
        *,
        expected_revision: int,
        committed_at: str,
    ) -> StoredExecutionSagaV2:
        return self._store.record_host_commit(
            saga_id,
            actual_delta,
            expected_revision=expected_revision,
            committed_at=committed_at,
        )

    def begin_reconciliation(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        return self._store.begin_reconciliation(
            saga_id,
            execution_slice_hash,
            expected_revision=expected_revision,
        )

    def record_scope_result(
        self,
        saga_id: str,
        result: ScopeComparisonResult,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        return self._store.record_scope_result(
            saga_id,
            result,
            expected_revision=expected_revision,
        )

    def record_verification_result(
        self,
        saga_id: str,
        result: SemanticVerificationResult,
        *,
        expected_revision: int,
        reconciled_at: str,
    ) -> StoredExecutionSagaV2:
        return self._store.record_verification_result(
            saga_id,
            result,
            expected_revision=expected_revision,
            reconciled_at=reconciled_at,
        )

    def fail_slice_before_commit(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        failed_at: str,
    ) -> StoredExecutionSagaV2:
        return self._store.fail_slice_before_commit(
            saga_id,
            execution_slice_hash,
            expected_revision=expected_revision,
            failed_at=failed_at,
        )

    def record_convergence_outcome(
        self,
        saga_id: str,
        outcome: SagaConvergenceOutcome,
        convergence_result_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        return self._store.record_convergence_outcome(
            saga_id,
            outcome,
            convergence_result_hash,
            expected_revision=expected_revision,
        )


__all__ = ["ExecutionSagaBuilderV2", "ExecutionSagaControllerV2"]
