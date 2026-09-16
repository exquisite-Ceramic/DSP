"""ExecutionSagaStoreV2 的可复用后端一致性契约。

这些 case 只断言 persistence port 的可观察领域语义，不依赖内存字典、SQL、连接池等
具体存储机制。任何新的 Saga V2 store backend 都必须复用同一组 contract cases。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest
from design_execution_reconciliation import (
    ActualDelta,
    ExecutionSagaBuilderV2,
    ExecutionSagaStatusV2,
    ReconciliationError,
    SagaConvergenceOutcome,
    ScopeComparisonResult,
    ScopeComparisonStatus,
    ScopeViolation,
    SemanticVerificationResult,
    SliceReconciliationStatusV2,
    ValidationTaskResult,
    VerificationStatus,
    compute_actual_delta_hash,
    compute_scope_comparison_hash,
    compute_semantic_verification_hash,
    compute_validation_task_result_hash,
)

from tests.execution_reconciliation.test_saga_v2_definition import _phase_i_context

ContractCase = Callable[[object, object, object], None]


def build_saga_v2_contract_fixture():
    """构造所有 backend 共用的冻结 Phase I Saga V2 定义与上下文。"""
    ctx = _phase_i_context()
    definition = ExecutionSagaBuilderV2().build(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
    )
    return ctx, definition


def _slice_state(stored, index: int):
    """按 canonical Slice 顺序读取持久状态。"""
    return stored.slice_states[index]


def _signed_delta(ctx, index: int, marker: int) -> ActualDelta:
    """构造与第 ``index`` 个 admitted Slice 完整 lineage 对齐的 ActualDelta。"""
    execution_slice = ctx.execution_plan.execution_slices[index]
    authority = ctx.authorities[index]
    draft = ActualDelta(
        actual_delta_id=f"AD-CONTRACT-{marker}",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=marker,
        revision_after=marker + 1,
        changes=(),
        actual_delta_hash="0" * 64,
    )
    return replace(draft, actual_delta_hash=compute_actual_delta_hash(draft))


def _signed_scope_result(
    execution_slice,
    delta: ActualDelta,
    status: ScopeComparisonStatus,
) -> ScopeComparisonResult:
    """构造合法的 WITHIN_SCOPE 或 SCOPE_BREACH scope evidence。"""
    violations = ()
    if status is ScopeComparisonStatus.SCOPE_BREACH:
        violations = (
            ScopeViolation(
                code="SAGA_STORE_CONTRACT_SCOPE_BREACH",
                actual_change_hash="f" * 64,
            ),
        )
    draft = ScopeComparisonResult(
        status=status,
        actual_delta_hash=delta.actual_delta_hash,
        approved_scope_hash=delta.approved_scope_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        matched_changes=(),
        violations=violations,
        comparison_hash="0" * 64,
    )
    return replace(draft, comparison_hash=compute_scope_comparison_hash(draft))


def _signed_verification_result(
    stored,
    execution_slice,
    delta: ActualDelta,
    status: VerificationStatus,
) -> SemanticVerificationResult:
    """根据 Saga 定义中的 exact validation assignment 构造签名验证结果。"""
    assignment = next(
        item
        for item in stored.definition.slice_validation_assignments
        if item.execution_slice_hash == execution_slice.execution_slice_hash
    )
    task_results = []
    for task_id in assignment.validation_task_ids:
        draft_task = ValidationTaskResult(
            validation_task_id=task_id,
            status=status,
            observations=("saga store backend contract",),
            failure_codes=() if status is VerificationStatus.PASSED else ("CONTRACT_VERIFY",),
            task_result_hash="0" * 64,
        )
        task_results.append(
            replace(
                draft_task,
                task_result_hash=compute_validation_task_result_hash(draft_task),
            )
        )

    draft = SemanticVerificationResult(
        verification_id="SVR-CONTRACT-DRAFT",
        changeset_hash=stored.definition.changeset_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        actual_delta_hash=delta.actual_delta_hash,
        evidence_bundle_hash=(
            "a" if execution_slice.host_runtime_ref.host_type == "autocad" else "b"
        )
        * 64,
        task_results=tuple(task_results),
        status=status,
        verification_hash="0" * 64,
    )
    verification_hash = compute_semantic_verification_hash(draft)
    return replace(
        draft,
        verification_id=f"SVR-{verification_hash[:12]}",
        verification_hash=verification_hash,
    )


def _reserve_and_admit(store, ctx, stored, index: int):
    """推进一个 Slice 到 ADMITTED，并返回最新 Saga。"""
    execution_slice = ctx.execution_plan.execution_slices[index]
    stored = store.reserve_slice_admission(
        stored.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at=f"2026-09-16T20:0{index}:00Z",
    )
    return store.confirm_slice_admitted(
        stored.definition.saga_id,
        ctx.authorities[index],
        expected_revision=stored.saga_revision,
    )


def _drive_to_reconciling(store, ctx, stored, index: int):
    """推进一个 Slice 到 RECONCILING，并返回 commit evidence。"""
    execution_slice = ctx.execution_plan.execution_slices[index]
    stored = _reserve_and_admit(store, ctx, stored, index)
    delta = _signed_delta(ctx, index, index + 1)
    stored = store.record_host_commit(
        stored.definition.saga_id,
        delta,
        expected_revision=stored.saga_revision,
        committed_at=f"2026-09-16T20:1{index}:00Z",
    )
    stored = store.begin_reconciliation(
        stored.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=stored.saga_revision,
    )
    return stored, delta


def _drive_local_success(store, ctx, stored, index: int):
    """推进一个 Slice 到 SUCCEEDED；最后一个 Slice 会进入 CONVERGENCE_PENDING。"""
    execution_slice = ctx.execution_plan.execution_slices[index]
    stored, delta = _drive_to_reconciling(store, ctx, stored, index)
    scope_result = _signed_scope_result(
        execution_slice,
        delta,
        ScopeComparisonStatus.WITHIN_SCOPE,
    )
    stored = store.record_scope_result(
        stored.definition.saga_id,
        scope_result,
        expected_revision=stored.saga_revision,
    )
    verification = _signed_verification_result(
        stored,
        execution_slice,
        delta,
        VerificationStatus.PASSED,
    )
    return store.record_verification_result(
        stored.definition.saga_id,
        verification,
        expected_revision=stored.saga_revision,
        reconciled_at=f"2026-09-16T20:2{index}:00Z",
    )


def assert_initial_state_contract(store, _ctx, definition) -> None:
    """首次 create、重复 create 与 get 必须具有完全一致的可观察语义。"""
    stored = store.create_saga(definition)
    assert stored.definition == definition
    assert stored.saga_revision == 0
    assert stored.status is ExecutionSagaStatusV2.READY
    assert tuple(item.sequence_index for item in stored.slice_states) == (0, 1)
    assert all(
        item.status is SliceReconciliationStatusV2.NOT_STARTED
        for item in stored.slice_states
    )
    assert store.create_saga(definition) == stored
    assert store.get_saga(definition.saga_id) == stored


def assert_reservation_replay_contract(store, _ctx, definition) -> None:
    """相同 reservation evidence 可 replay，不同 evidence + stale revision 必须冲突。"""
    stored = store.create_saga(definition)
    first_hash = definition.ordered_slice_hashes[0]
    reserved_at = "2026-09-16T21:00:00Z"
    reserved = store.reserve_slice_admission(
        definition.saga_id,
        first_hash,
        expected_revision=stored.saga_revision,
        reserved_at=reserved_at,
    )
    assert reserved.saga_revision == stored.saga_revision + 1
    assert _slice_state(reserved, 0).status is SliceReconciliationStatusV2.ADMISSION_RESERVED

    replay = store.reserve_slice_admission(
        definition.saga_id,
        first_hash,
        expected_revision=stored.saga_revision,
        reserved_at=reserved_at,
    )
    assert replay == reserved

    with pytest.raises(ReconciliationError) as exc:
        store.reserve_slice_admission(
            definition.saga_id,
            first_hash,
            expected_revision=stored.saga_revision,
            reserved_at="2026-09-16T21:00:01Z",
        )
    assert exc.value.code == "SAGA_CONFLICT"
    assert store.get_saga(definition.saga_id) == reserved


def assert_authority_lineage_contract(store, ctx, definition) -> None:
    """admission 必须持久化 exact materialization / approval / grant / binding lineage。"""
    stored = store.create_saga(definition)
    admitted = _reserve_and_admit(store, ctx, stored, 0)
    authority = ctx.authorities[0]
    state = _slice_state(admitted, 0)

    assert state.materialization_id == authority.materialization_id
    assert state.approval_hash == authority.approval_hash
    assert state.grant_hash == authority.grant_hash
    assert state.binding_set_hash == authority.binding_set_hash
    assert state.admitted_host_instance_id == authority.host_instance_id
    assert state.status is SliceReconciliationStatusV2.ADMITTED

    # 完全相同 authority 是 evidence replay；旧 revision 不得让 replay 误报 CAS 冲突。
    replay = store.confirm_slice_admitted(
        definition.saga_id,
        authority,
        expected_revision=admitted.saga_revision - 1,
    )
    assert replay == admitted


def assert_host_commit_and_reconciliation_contract(store, ctx, definition) -> None:
    """Host commit evidence 与 reconciliation 状态必须可持久读取且 replay-safe。"""
    stored = store.create_saga(definition)
    stored = _reserve_and_admit(store, ctx, stored, 0)
    execution_slice = ctx.execution_plan.execution_slices[0]
    delta = _signed_delta(ctx, 0, 1)
    before_commit_revision = stored.saga_revision

    committed = store.record_host_commit(
        definition.saga_id,
        delta,
        expected_revision=before_commit_revision,
        committed_at="2026-09-16T21:10:00Z",
    )
    assert _slice_state(committed, 0).status is SliceReconciliationStatusV2.HOST_COMMITTED
    assert _slice_state(committed, 0).actual_delta_hash == delta.actual_delta_hash

    replay = store.record_host_commit(
        definition.saga_id,
        delta,
        expected_revision=before_commit_revision,
        committed_at="2026-09-16T21:10:00Z",
    )
    assert replay == committed

    reconciling = store.begin_reconciliation(
        definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=committed.saga_revision,
    )
    assert _slice_state(reconciling, 0).status is SliceReconciliationStatusV2.RECONCILING
    assert store.get_saga(definition.saga_id) == reconciling


def assert_scope_breach_contract(store, ctx, definition) -> None:
    """commit 后 scope breach 必须原子进入 PARTIALLY_COMMITTED 并阻断后继 Slice。"""
    stored = store.create_saga(definition)
    stored, delta = _drive_to_reconciling(store, ctx, stored, 0)
    execution_slice = ctx.execution_plan.execution_slices[0]
    breach = _signed_scope_result(
        execution_slice,
        delta,
        ScopeComparisonStatus.SCOPE_BREACH,
    )

    failed = store.record_scope_result(
        definition.saga_id,
        breach,
        expected_revision=stored.saga_revision,
    )
    assert failed.status is ExecutionSagaStatusV2.PARTIALLY_COMMITTED
    assert _slice_state(failed, 0).status is SliceReconciliationStatusV2.SCOPE_BREACH
    assert _slice_state(failed, 0).scope_comparison_hash == breach.comparison_hash
    assert _slice_state(failed, 1).status is SliceReconciliationStatusV2.BLOCKED


def assert_verification_failure_contract(store, ctx, definition) -> None:
    """WITHIN_SCOPE 后的 non-PASSED verification 必须保持 committed truth 并阻断后继。"""
    stored = store.create_saga(definition)
    stored, delta = _drive_to_reconciling(store, ctx, stored, 0)
    execution_slice = ctx.execution_plan.execution_slices[0]
    scope_result = _signed_scope_result(
        execution_slice,
        delta,
        ScopeComparisonStatus.WITHIN_SCOPE,
    )
    stored = store.record_scope_result(
        definition.saga_id,
        scope_result,
        expected_revision=stored.saga_revision,
    )
    verification = _signed_verification_result(
        stored,
        execution_slice,
        delta,
        VerificationStatus.FAILED,
    )

    failed = store.record_verification_result(
        definition.saga_id,
        verification,
        expected_revision=stored.saga_revision,
        reconciled_at="2026-09-16T21:20:00Z",
    )
    assert failed.status is ExecutionSagaStatusV2.PARTIALLY_COMMITTED
    assert _slice_state(failed, 0).status is SliceReconciliationStatusV2.VERIFY_FAILED
    assert _slice_state(failed, 0).verification_hash == verification.verification_hash
    assert _slice_state(failed, 0).actual_delta_hash == delta.actual_delta_hash
    assert _slice_state(failed, 1).status is SliceReconciliationStatusV2.BLOCKED


def assert_precommit_failure_contract(store, ctx, definition) -> None:
    """首个 Slice commit 前失败必须是 FAILED，且同证据 replay 不增加 revision。"""
    stored = store.create_saga(definition)
    stored = _reserve_and_admit(store, ctx, stored, 0)
    failed_at = "2026-09-16T21:30:00Z"
    before_failure_revision = stored.saga_revision

    failed = store.fail_slice_before_commit(
        definition.saga_id,
        definition.ordered_slice_hashes[0],
        expected_revision=before_failure_revision,
        failed_at=failed_at,
    )
    assert failed.status is ExecutionSagaStatusV2.FAILED
    assert _slice_state(failed, 0).status is SliceReconciliationStatusV2.FAILED_BEFORE_COMMIT
    assert _slice_state(failed, 0).actual_delta_hash is None
    assert _slice_state(failed, 1).status is SliceReconciliationStatusV2.BLOCKED

    replay = store.fail_slice_before_commit(
        definition.saga_id,
        definition.ordered_slice_hashes[0],
        expected_revision=before_failure_revision,
        failed_at=failed_at,
    )
    assert replay == failed


def _assert_convergence_contract(store, ctx, definition, outcome: SagaConvergenceOutcome) -> None:
    """所有 REQUIRED Slice 本地成功后，只由 convergence outcome 决定最终终态。"""
    stored = store.create_saga(definition)
    stored = _drive_local_success(store, ctx, stored, 0)
    assert stored.status is ExecutionSagaStatusV2.EXECUTING
    stored = _drive_local_success(store, ctx, stored, 1)
    assert stored.status is ExecutionSagaStatusV2.CONVERGENCE_PENDING

    result_hash = ("c" if outcome is SagaConvergenceOutcome.CONVERGED else "d") * 64
    terminal = store.record_convergence_outcome(
        definition.saga_id,
        outcome,
        result_hash,
        expected_revision=stored.saga_revision,
    )
    expected_status = (
        ExecutionSagaStatusV2.SUCCEEDED
        if outcome is SagaConvergenceOutcome.CONVERGED
        else ExecutionSagaStatusV2.DIVERGED
    )
    assert terminal.status is expected_status
    assert terminal.convergence_outcome is outcome
    assert terminal.convergence_result_hash == result_hash
    assert store.get_saga(definition.saga_id) == terminal


def assert_converged_contract(store, ctx, definition) -> None:
    """CONVERGED outcome 的公共 backend contract。"""
    _assert_convergence_contract(store, ctx, definition, SagaConvergenceOutcome.CONVERGED)


def assert_diverged_contract(store, ctx, definition) -> None:
    """DIVERGED outcome 的公共 backend contract。"""
    _assert_convergence_contract(store, ctx, definition, SagaConvergenceOutcome.DIVERGED)


SAGA_STORE_V2_CONTRACT_CASES: tuple[tuple[str, ContractCase], ...] = (
    ("initial_state", assert_initial_state_contract),
    ("reservation_replay_and_cas", assert_reservation_replay_contract),
    ("authority_lineage", assert_authority_lineage_contract),
    ("host_commit_and_reconciliation", assert_host_commit_and_reconciliation_contract),
    ("scope_breach", assert_scope_breach_contract),
    ("verification_failure", assert_verification_failure_contract),
    ("precommit_failure", assert_precommit_failure_contract),
    ("converged", assert_converged_contract),
    ("diverged", assert_diverged_contract),
)


__all__ = [
    "SAGA_STORE_V2_CONTRACT_CASES",
    "build_saga_v2_contract_fixture",
]
