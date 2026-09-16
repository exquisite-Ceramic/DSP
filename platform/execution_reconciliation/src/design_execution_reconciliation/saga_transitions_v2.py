"""Execution Saga V2 的纯领域状态转换引擎。

这里集中承载 Saga V2 的全部可观察状态机语义。存储实现只能负责加载、CAS 持久化与保存，
不得各自复制 transition 规则，否则内存与 PostgreSQL 后端会演化成两套业务状态机。
"""

from __future__ import annotations

import re
from dataclasses import replace

from design_gateway_authorization import AdmittedExecutionAuthorityV2

from .contracts import (
    ActualDelta,
    ReconciliationError,
    ScopeComparisonResult,
    ScopeComparisonStatus,
    SemanticVerificationResult,
    VerificationStatus,
)
from .hashing import (
    compute_scope_comparison_hash,
    compute_semantic_verification_hash,
    compute_validation_task_result_hash,
    validate_actual_delta_integrity,
)
from .saga_contracts_v2 import (
    ExecutionSagaDefinitionV2,
    compute_execution_saga_definition_hash_v2,
)
from .saga_state_v2 import (
    ExecutionSagaStatusV2,
    SagaConvergenceOutcome,
    SliceReconciliationStateV2,
    SliceReconciliationStatusV2,
    StoredExecutionSagaV2,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIVE_SLICE_STATUSES = frozenset(
    {
        SliceReconciliationStatusV2.ADMISSION_RESERVED,
        SliceReconciliationStatusV2.ADMITTED,
        SliceReconciliationStatusV2.HOST_COMMITTED,
        SliceReconciliationStatusV2.RECONCILING,
    }
)


def _error(code: str, message: str) -> None:
    """统一抛出 Saga V2 领域错误。"""
    raise ReconciliationError(code, message)


def _require_revision(value: object) -> int:
    """校验严格 CAS revision。"""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _error("SAGA_CONFLICT", "expected_revision must be a non-negative integer")
    return value


def _require_digest(value: object, field_name: str) -> str:
    """校验外部结果摘要。"""
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        _error("SAGA_INTEGRITY_INVALID", f"{field_name} must be lowercase SHA-256 hex")
    return value


def _definition_integrity(definition: ExecutionSagaDefinitionV2) -> None:
    """验证 Saga V2 定义自身哈希、闭世界 Slice 与任务分配。"""
    if not isinstance(definition, ExecutionSagaDefinitionV2):
        raise TypeError("definition must be ExecutionSagaDefinitionV2")
    expected_hash = compute_execution_saga_definition_hash_v2(definition)
    if definition.saga_definition_hash != expected_hash:
        _error("SAGA_INTEGRITY_INVALID", "Saga V2 definition hash is invalid")
    if definition.saga_id != f"SGV2-{expected_hash[:12]}":
        _error("SAGA_INTEGRITY_INVALID", "Saga V2 id does not match its definition hash")

    slice_hashes = set(definition.ordered_slice_hashes)
    assignment_hashes = {
        item.execution_slice_hash for item in definition.slice_validation_assignments
    }
    if assignment_hashes != slice_hashes:
        _error(
            "SAGA_INTEGRITY_INVALID",
            "Saga V2 validation assignments must cover every Slice exactly once",
        )
    for dependency in definition.slice_dependencies:
        if (
            dependency.predecessor_slice_hash not in slice_hashes
            or dependency.successor_slice_hash not in slice_hashes
        ):
            _error(
                "SAGA_INTEGRITY_INVALID",
                "Saga V2 dependency references a Slice outside the definition",
            )


def _state_index(stored: StoredExecutionSagaV2, execution_slice_hash: str) -> int:
    """解析 Saga 内唯一 Slice state。"""
    for index, state in enumerate(stored.slice_states):
        if state.execution_slice_hash == execution_slice_hash:
            return index
    _error("SAGA_INTEGRITY_INVALID", "execution Slice is not part of this Saga V2")


def _assignment_task_ids(
    definition: ExecutionSagaDefinitionV2,
    execution_slice_hash: str,
) -> tuple[str, ...]:
    """读取一个 Slice 的 exact 本地 validation task 集。"""
    matches = tuple(
        item.validation_task_ids
        for item in definition.slice_validation_assignments
        if item.execution_slice_hash == execution_slice_hash
    )
    if len(matches) != 1:
        _error("SAGA_INTEGRITY_INVALID", "Slice validation assignment is unresolved")
    return matches[0]


def _rebuild(
    stored: StoredExecutionSagaV2,
    *,
    status: ExecutionSagaStatusV2 | None = None,
    slice_states: tuple[SliceReconciliationStateV2, ...] | None = None,
    convergence_outcome: SagaConvergenceOutcome | None = None,
    convergence_result_hash: str | None = None,
    preserve_convergence: bool = True,
) -> StoredExecutionSagaV2:
    """以 revision+1 重建不可变 Saga V2 快照。"""
    if preserve_convergence:
        outcome = stored.convergence_outcome
        result_hash = stored.convergence_result_hash
    else:
        outcome = convergence_outcome
        result_hash = convergence_result_hash
    return StoredExecutionSagaV2(
        definition=stored.definition,
        saga_revision=stored.saga_revision + 1,
        status=stored.status if status is None else status,
        slice_states=stored.slice_states if slice_states is None else slice_states,
        convergence_outcome=outcome,
        convergence_result_hash=result_hash,
    )


def _with_state(
    stored: StoredExecutionSagaV2,
    index: int,
    state: SliceReconciliationStateV2,
    *,
    saga_status: ExecutionSagaStatusV2 | None = None,
) -> StoredExecutionSagaV2:
    """替换一个 Slice state 并递增 Saga revision。"""
    states = list(stored.slice_states)
    states[index] = state
    return _rebuild(
        stored,
        status=saga_status,
        slice_states=tuple(states),
    )


def _blocked_after(
    stored: StoredExecutionSagaV2,
    failed_index: int,
    failed_state: SliceReconciliationStateV2,
) -> tuple[SliceReconciliationStateV2, ...]:
    """失败后阻止尚未开始的后继 materialization。"""
    states = list(stored.slice_states)
    states[failed_index] = failed_state
    for index in range(failed_index + 1, len(states)):
        if states[index].status is SliceReconciliationStatusV2.NOT_STARTED:
            states[index] = replace(
                states[index],
                status=SliceReconciliationStatusV2.BLOCKED,
            )
    return tuple(states)


def _authority_matches_state(
    authority: AdmittedExecutionAuthorityV2,
    state: SliceReconciliationStateV2,
) -> bool:
    """判断重复 admission 是否携带完全相同的不可变证据。"""
    return (
        state.materialization_id == authority.materialization_id
        and state.materialization_plan_hash == authority.materialization_plan_hash
        and state.approval_hash == authority.approval_hash
        and state.grant_hash == authority.grant_hash
        and state.binding_set_hash == authority.binding_set_hash
        and state.admitted_host_instance_id == authority.host_instance_id
        and state.admitted_at == authority.admitted_at
    )


def _require_cas(stored: StoredExecutionSagaV2, expected_revision: int) -> None:
    """要求调用方观察到的 revision 与当前 Saga revision 完全一致。"""
    expected = _require_revision(expected_revision)
    if stored.saga_revision != expected:
        _error("SAGA_CONFLICT", "Saga V2 revision changed before transition")


def _require_no_other_active(
    stored: StoredExecutionSagaV2,
    execution_slice_hash: str,
) -> None:
    """冻结 Phase I 串行执行语义：同一时刻只有一个活跃 Slice。"""
    for state in stored.slice_states:
        if (
            state.execution_slice_hash != execution_slice_hash
            and state.status in _ACTIVE_SLICE_STATUSES
        ):
            _error("SAGA_CONFLICT", "another Saga V2 Slice is already active")


def _require_next_eligible(
    stored: StoredExecutionSagaV2,
    execution_slice_hash: str,
) -> None:
    """要求 admission 选择最低 canonical eligible Slice。"""
    predecessors: dict[str, set[str]] = {
        value: set() for value in stored.definition.ordered_slice_hashes
    }
    for dependency in stored.definition.slice_dependencies:
        predecessors[dependency.successor_slice_hash].add(
            dependency.predecessor_slice_hash
        )
    status_by_hash = {
        state.execution_slice_hash: state.status for state in stored.slice_states
    }
    eligible = tuple(
        state.execution_slice_hash
        for state in stored.slice_states
        if state.status is SliceReconciliationStatusV2.NOT_STARTED
        and all(
            status_by_hash[item] is SliceReconciliationStatusV2.SUCCEEDED
            for item in predecessors[state.execution_slice_hash]
        )
    )
    if not eligible or execution_slice_hash != eligible[0]:
        _error(
            "SAGA_CONFLICT",
            "Slice is not the lowest canonical eligible admission candidate",
        )


def create_initial_saga_v2(
    definition: ExecutionSagaDefinitionV2,
    *,
    existing: StoredExecutionSagaV2 | None = None,
) -> StoredExecutionSagaV2:
    """创建初始 Saga；相同定义允许 replay，不同定义绑定同一 id 时冲突。"""
    if not isinstance(definition, ExecutionSagaDefinitionV2):
        raise TypeError("definition must be ExecutionSagaDefinitionV2")
    if existing is not None:
        if existing.definition == definition:
            return existing
        _error("SAGA_CONFLICT", "Saga V2 id already binds another definition")

    _definition_integrity(definition)
    states = tuple(
        SliceReconciliationStateV2(
            execution_slice_hash=slice_hash,
            sequence_index=index,
            materialization_plan_hash=definition.materialization_plan_hash,
        )
        for index, slice_hash in enumerate(definition.ordered_slice_hashes)
    )
    return StoredExecutionSagaV2(
        definition=definition,
        saga_revision=0,
        status=ExecutionSagaStatusV2.READY,
        slice_states=states,
    )


def reserve_slice_admission_transition(
    stored: StoredExecutionSagaV2,
    execution_slice_hash: str,
    *,
    expected_revision: int,
    reserved_at: str,
) -> StoredExecutionSagaV2:
    """纯函数形式执行 Slice admission reservation。"""
    index = _state_index(stored, execution_slice_hash)
    state = stored.slice_states[index]
    if state.reserved_at is not None:
        if state.reserved_at == reserved_at:
            return stored
        _error("SAGA_CONFLICT", "Slice reservation evidence differs")
    _require_cas(stored, expected_revision)
    if stored.status not in {
        ExecutionSagaStatusV2.READY,
        ExecutionSagaStatusV2.EXECUTING,
    }:
        _error("SAGA_CONFLICT", "Saga V2 cannot reserve another Slice")
    _require_no_other_active(stored, execution_slice_hash)
    _require_next_eligible(stored, execution_slice_hash)
    if state.status is not SliceReconciliationStatusV2.NOT_STARTED:
        _error("SAGA_CONFLICT", "Slice is not available for reservation")
    updated = replace(
        state,
        status=SliceReconciliationStatusV2.ADMISSION_RESERVED,
        reserved_at=reserved_at,
    )
    return _with_state(
        stored,
        index,
        updated,
        saga_status=ExecutionSagaStatusV2.EXECUTING,
    )


def confirm_slice_admitted_transition(
    stored: StoredExecutionSagaV2,
    authority: AdmittedExecutionAuthorityV2,
    *,
    expected_revision: int,
) -> StoredExecutionSagaV2:
    """纯函数形式确认 Gateway admission authority。"""
    if not isinstance(authority, AdmittedExecutionAuthorityV2):
        raise TypeError("authority must be AdmittedExecutionAuthorityV2")
    index = _state_index(stored, authority.execution_slice_hash)
    state = stored.slice_states[index]
    if state.grant_hash is not None:
        if _authority_matches_state(authority, state):
            return stored
        _error("SAGA_CONFLICT", "Slice admission evidence differs")
    _require_cas(stored, expected_revision)
    if state.status is not SliceReconciliationStatusV2.ADMISSION_RESERVED:
        _error("SAGA_CONFLICT", "Slice has no active admission reservation")
    if (
        authority.changeset_hash != stored.definition.changeset_hash
        or authority.approved_scope_hash != stored.definition.approved_scope_hash
        or authority.materialization_plan_hash != stored.definition.materialization_plan_hash
        or authority.materialization_plan_hash != state.materialization_plan_hash
    ):
        _error(
            "SAGA_INTEGRITY_INVALID",
            "V2 authority does not join immutable Saga materialization lineage",
        )
    updated = replace(
        state,
        status=SliceReconciliationStatusV2.ADMITTED,
        materialization_id=authority.materialization_id,
        approval_hash=authority.approval_hash,
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        admitted_host_instance_id=authority.host_instance_id,
        admitted_at=authority.admitted_at,
    )
    return _with_state(stored, index, updated)


def record_host_commit_transition(
    stored: StoredExecutionSagaV2,
    actual_delta: ActualDelta,
    *,
    expected_revision: int,
    committed_at: str,
) -> StoredExecutionSagaV2:
    """纯函数形式持久化 Host commit 的不可变证据。"""
    validate_actual_delta_integrity(actual_delta)
    index = _state_index(stored, actual_delta.execution_slice_hash)
    state = stored.slice_states[index]
    if state.actual_delta_hash is not None:
        if (
            state.actual_delta_hash == actual_delta.actual_delta_hash
            and state.committed_at == committed_at
        ):
            return stored
        _error("SAGA_CONFLICT", "Host commit evidence differs")
    _require_cas(stored, expected_revision)
    if state.status is not SliceReconciliationStatusV2.ADMITTED:
        _error("SAGA_CONFLICT", "Slice must be ADMITTED before Host commit")
    if (
        actual_delta.grant_hash != state.grant_hash
        or actual_delta.binding_set_hash != state.binding_set_hash
        or actual_delta.changeset_hash != stored.definition.changeset_hash
        or actual_delta.approved_scope_hash != stored.definition.approved_scope_hash
        or actual_delta.host_instance_id != state.admitted_host_instance_id
    ):
        _error(
            "SAGA_INTEGRITY_INVALID",
            "ActualDelta does not join admitted Saga V2 authority",
        )
    updated = replace(
        state,
        status=SliceReconciliationStatusV2.HOST_COMMITTED,
        actual_delta_hash=actual_delta.actual_delta_hash,
        committed_at=committed_at,
    )
    return _with_state(stored, index, updated)


def begin_reconciliation_transition(
    stored: StoredExecutionSagaV2,
    execution_slice_hash: str,
    *,
    expected_revision: int,
) -> StoredExecutionSagaV2:
    """纯函数形式进入 reconciliation。"""
    index = _state_index(stored, execution_slice_hash)
    state = stored.slice_states[index]
    if state.status is SliceReconciliationStatusV2.RECONCILING:
        return stored
    _require_cas(stored, expected_revision)
    if state.status is not SliceReconciliationStatusV2.HOST_COMMITTED:
        _error("SAGA_CONFLICT", "Slice has no committed Host evidence")
    updated = replace(state, status=SliceReconciliationStatusV2.RECONCILING)
    return _with_state(stored, index, updated)


def record_scope_result_transition(
    stored: StoredExecutionSagaV2,
    result: ScopeComparisonResult,
    *,
    expected_revision: int,
) -> StoredExecutionSagaV2:
    """纯函数形式记录 approved-scope 比较结果。"""
    if not isinstance(result, ScopeComparisonResult):
        raise TypeError("result must be ScopeComparisonResult")
    if result.comparison_hash != compute_scope_comparison_hash(result):
        _error("SAGA_INTEGRITY_INVALID", "scope comparison hash is invalid")
    index = _state_index(stored, result.execution_slice_hash)
    state = stored.slice_states[index]
    if state.scope_comparison_hash is not None:
        if state.scope_comparison_hash == result.comparison_hash:
            return stored
        _error("SAGA_CONFLICT", "scope comparison evidence differs")
    _require_cas(stored, expected_revision)
    if state.status is not SliceReconciliationStatusV2.RECONCILING:
        _error("SAGA_CONFLICT", "Slice is not reconciling")
    if (
        result.actual_delta_hash != state.actual_delta_hash
        or result.approved_scope_hash != stored.definition.approved_scope_hash
    ):
        _error(
            "SAGA_INTEGRITY_INVALID",
            "scope result does not join committed Saga V2 evidence",
        )
    if result.status is ScopeComparisonStatus.WITHIN_SCOPE:
        updated_state = replace(
            state,
            scope_comparison_hash=result.comparison_hash,
        )
        return _with_state(stored, index, updated_state)

    failed_state = replace(
        state,
        status=SliceReconciliationStatusV2.SCOPE_BREACH,
        scope_comparison_hash=result.comparison_hash,
    )
    return _rebuild(
        stored,
        status=ExecutionSagaStatusV2.PARTIALLY_COMMITTED,
        slice_states=_blocked_after(stored, index, failed_state),
    )


def record_verification_result_transition(
    stored: StoredExecutionSagaV2,
    result: SemanticVerificationResult,
    *,
    expected_revision: int,
    reconciled_at: str,
) -> StoredExecutionSagaV2:
    """纯函数形式记录语义验证结果并推进本地 Slice 状态。"""
    if not isinstance(result, SemanticVerificationResult):
        raise TypeError("result must be SemanticVerificationResult")
    if result.verification_hash != compute_semantic_verification_hash(result):
        _error("SAGA_INTEGRITY_INVALID", "semantic verification hash is invalid")
    for task_result in result.task_results:
        if task_result.task_result_hash != compute_validation_task_result_hash(task_result):
            _error("SAGA_INTEGRITY_INVALID", "validation task result hash is invalid")

    index = _state_index(stored, result.execution_slice_hash)
    state = stored.slice_states[index]
    if state.verification_hash is not None:
        if (
            state.verification_hash == result.verification_hash
            and state.reconciled_at == reconciled_at
        ):
            return stored
        _error("SAGA_CONFLICT", "semantic verification evidence differs")
    _require_cas(stored, expected_revision)
    if state.status is not SliceReconciliationStatusV2.RECONCILING:
        _error("SAGA_CONFLICT", "Slice is not reconciling")
    if state.scope_comparison_hash is None:
        _error(
            "SAGA_CONFLICT",
            "semantic verification requires persisted WITHIN_SCOPE evidence",
        )
    if (
        result.changeset_hash != stored.definition.changeset_hash
        or result.actual_delta_hash != state.actual_delta_hash
    ):
        _error(
            "SAGA_INTEGRITY_INVALID",
            "verification result does not join committed Saga V2 evidence",
        )
    expected_tasks = _assignment_task_ids(
        stored.definition,
        result.execution_slice_hash,
    )
    actual_tasks = tuple(item.validation_task_id for item in result.task_results)
    if actual_tasks != expected_tasks:
        _error(
            "SAGA_INTEGRITY_INVALID",
            "verification must cover exact tasks assigned to this materialization",
        )
    all_tasks_passed = all(
        item.status is VerificationStatus.PASSED for item in result.task_results
    )
    if result.status is VerificationStatus.PASSED:
        if not all_tasks_passed:
            _error(
                "SAGA_INTEGRITY_INVALID",
                "PASSED verification contains a non-PASSED task",
            )
        succeeded_state = replace(
            state,
            status=SliceReconciliationStatusV2.SUCCEEDED,
            verification_hash=result.verification_hash,
            reconciled_at=reconciled_at,
        )
        states = list(stored.slice_states)
        states[index] = succeeded_state
        all_succeeded = all(
            item.status is SliceReconciliationStatusV2.SUCCEEDED for item in states
        )
        final_status = (
            ExecutionSagaStatusV2.CONVERGENCE_PENDING
            if all_succeeded
            else ExecutionSagaStatusV2.EXECUTING
        )
        return _rebuild(
            stored,
            status=final_status,
            slice_states=tuple(states),
        )

    failed_state = replace(
        state,
        status=SliceReconciliationStatusV2.VERIFY_FAILED,
        verification_hash=result.verification_hash,
        reconciled_at=reconciled_at,
    )
    return _rebuild(
        stored,
        status=ExecutionSagaStatusV2.PARTIALLY_COMMITTED,
        slice_states=_blocked_after(stored, index, failed_state),
    )


def fail_slice_before_commit_transition(
    stored: StoredExecutionSagaV2,
    execution_slice_hash: str,
    *,
    expected_revision: int,
    failed_at: str,
) -> StoredExecutionSagaV2:
    """纯函数形式记录 Host commit 之前的失败。"""
    index = _state_index(stored, execution_slice_hash)
    state = stored.slice_states[index]
    if state.status is SliceReconciliationStatusV2.FAILED_BEFORE_COMMIT:
        if state.failed_at == failed_at:
            return stored
        _error("SAGA_CONFLICT", "pre-commit failure evidence differs")
    _require_cas(stored, expected_revision)
    if state.status not in {
        SliceReconciliationStatusV2.ADMISSION_RESERVED,
        SliceReconciliationStatusV2.ADMITTED,
    }:
        _error(
            "SAGA_CONFLICT",
            "Slice may fail-before-commit only before Host commit",
        )
    if state.actual_delta_hash is not None:
        _error("SAGA_CONFLICT", "committed Slice cannot fail-before-commit")
    failed_state = replace(
        state,
        status=SliceReconciliationStatusV2.FAILED_BEFORE_COMMIT,
        failed_at=failed_at,
    )
    prior_committed = any(
        item.actual_delta_hash is not None for item in stored.slice_states[:index]
    )
    final_status = (
        ExecutionSagaStatusV2.PARTIALLY_COMMITTED
        if prior_committed
        else ExecutionSagaStatusV2.FAILED
    )
    return _rebuild(
        stored,
        status=final_status,
        slice_states=_blocked_after(stored, index, failed_state),
    )


def record_convergence_outcome_transition(
    stored: StoredExecutionSagaV2,
    outcome: SagaConvergenceOutcome,
    convergence_result_hash: str,
    *,
    expected_revision: int,
) -> StoredExecutionSagaV2:
    """纯函数形式完成 Saga convergence。"""
    if not isinstance(outcome, SagaConvergenceOutcome):
        raise TypeError("outcome must be SagaConvergenceOutcome")
    result_hash = _require_digest(
        convergence_result_hash,
        "convergence_result_hash",
    )
    if stored.convergence_result_hash is not None:
        if (
            stored.convergence_outcome is outcome
            and stored.convergence_result_hash == result_hash
        ):
            return stored
        _error("SAGA_CONFLICT", "convergence outcome evidence differs")
    _require_cas(stored, expected_revision)
    if stored.status is not ExecutionSagaStatusV2.CONVERGENCE_PENDING:
        _error("SAGA_CONFLICT", "Saga V2 is not convergence-pending")
    if not all(
        item.status is SliceReconciliationStatusV2.SUCCEEDED
        for item in stored.slice_states
    ):
        _error(
            "SAGA_CONFLICT",
            "convergence cannot finalize before all REQUIRED Slices succeed locally",
        )
    final_status = (
        ExecutionSagaStatusV2.SUCCEEDED
        if outcome is SagaConvergenceOutcome.CONVERGED
        else ExecutionSagaStatusV2.DIVERGED
    )
    return _rebuild(
        stored,
        status=final_status,
        convergence_outcome=outcome,
        convergence_result_hash=result_hash,
        preserve_convergence=False,
    )


__all__ = [
    "begin_reconciliation_transition",
    "confirm_slice_admitted_transition",
    "create_initial_saga_v2",
    "fail_slice_before_commit_transition",
    "record_convergence_outcome_transition",
    "record_host_commit_transition",
    "record_scope_result_transition",
    "record_verification_result_transition",
    "reserve_slice_admission_transition",
]
