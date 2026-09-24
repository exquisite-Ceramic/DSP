"""Task 8.3：Execution Saga/dispatch owner truth 的只读 recovery projection 契约。"""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_coordination import CoordinationError
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    HostDispatchStatus,
    SliceReconciliationStateV2,
    SliceReconciliationStatusV2,
    StoredExecutionSagaV2,
    build_host_dispatch_intent,
    compute_execution_saga_definition_hash_v2,
)

from tests.execution_reconciliation.saga_store_v2_contract import (
    build_saga_v2_contract_fixture,
)


def _projection_api():
    """延迟导入 Task 8.3 public surface，让 RED 精确落在 projection 尚未发布。"""
    from design_execution_coordination import (
        ExecutionRecoveryDisposition,
        ExecutionRecoveryProjection,
        project_execution_recovery,
    )

    return (
        ExecutionRecoveryDisposition,
        ExecutionRecoveryProjection,
        project_execution_recovery,
    )


def _single_slice_fixture():
    """从真实 Phase-I fixture 派生完整自洽的一-Slice immutable Saga 定义与初始快照。"""
    ctx, original = build_saga_v2_contract_fixture()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    slice_hash = execution_slice.execution_slice_hash
    assignments = tuple(
        item
        for item in original.slice_validation_assignments
        if item.execution_slice_hash == slice_hash
    )

    # 重新计算 definition hash 与 saga_id；不复用双-Slice definition 的旧 identity。
    draft = replace(
        original,
        saga_id="SGV2-DRAFT",
        ordered_slice_hashes=(slice_hash,),
        slice_dependencies=(),
        slice_validation_assignments=assignments,
        saga_definition_hash="0" * 64,
    )
    definition_hash = compute_execution_saga_definition_hash_v2(draft)
    definition = replace(
        draft,
        saga_id=f"SGV2-{definition_hash[:12]}",
        saga_definition_hash=definition_hash,
    )
    state = SliceReconciliationStateV2(
        execution_slice_hash=slice_hash,
        sequence_index=0,
        materialization_plan_hash=definition.materialization_plan_hash,
    )
    stored = StoredExecutionSagaV2(
        definition=definition,
        saga_revision=0,
        status=ExecutionSagaStatusV2.READY,
        slice_states=(state,),
    )
    intent = build_host_dispatch_intent(
        saga_id=definition.saga_id,
        execution_slice_hash=slice_hash,
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        expected_host_revision="41",
        prepared_at="2026-09-24T11:00:00Z",
    )
    return ctx, stored, intent


def _with_slice_state(
    stored: StoredExecutionSagaV2,
    *,
    slice_status: SliceReconciliationStatusV2,
    saga_status: ExecutionSagaStatusV2,
    admitted: bool,
    saga_revision: int = 1,
) -> StoredExecutionSagaV2:
    """用公开 immutable contracts 构造指定 durable Saga/Slice 组合。"""
    ctx, _ = build_saga_v2_contract_fixture()
    authority = ctx.authorities[0]
    state = stored.slice_states[0]
    state = replace(
        state,
        status=slice_status,
        materialization_id=(authority.materialization_id if admitted else None),
        approval_hash=(authority.approval_hash if admitted else None),
        grant_hash=(authority.grant_hash if admitted else None),
        binding_set_hash=(authority.binding_set_hash if admitted else None),
        admitted_host_instance_id=(authority.host_instance_id if admitted else None),
    )
    return replace(
        stored,
        saga_revision=saga_revision,
        status=saga_status,
        slice_states=(state,),
    )


def _intent_with_status(intent, status: HostDispatchStatus):
    """构造与 durable transition 单调性一致的 immutable dispatch revision。"""
    revision = {
        HostDispatchStatus.PREPARED: 0,
        HostDispatchStatus.DISPATCHED: 1,
        HostDispatchStatus.OUTCOME_UNKNOWN: 2,
        HostDispatchStatus.HOST_COMMITTED: 2,
        HostDispatchStatus.SAFE_TO_RETRY: 2,
        HostDispatchStatus.RECONCILED: 3,
    }[status]
    return replace(intent, status=status, intent_revision=revision)


def _project(stored: StoredExecutionSagaV2, intent):
    """调用尚待 Task 8.3 发布的 public read-only projection。"""
    _disposition_type, _projection_type, project = _projection_api()
    return project(
        stored,
        stored.definition.ordered_slice_hashes[0],
        intent,
    )


def _assert_conflict(stored: StoredExecutionSagaV2, intent) -> None:
    """统一断言 owner evidence mismatch 的稳定机器码。"""
    with pytest.raises(CoordinationError) as exc_info:
        _project(stored, intent)
    assert exc_info.value.code == "HOST_RECOVERY_EVIDENCE_CONFLICT"


def test_duplicate_requested_slice_is_rejected_by_public_definition_invariant() -> None:
    """重复 Slice 在 projection 之前就被 immutable Saga definition 构造器拒绝。"""
    _ctx, stored, _intent = _single_slice_fixture()
    slice_hash = stored.definition.ordered_slice_hashes[0]

    with pytest.raises(ValueError, match="must be unique"):
        replace(
            stored.definition,
            ordered_slice_hashes=(slice_hash, slice_hash),
        )


def test_projection_rejects_missing_requested_slice() -> None:
    """请求不属于 Saga definition 的 Slice 必须以 SAGA_INTEGRITY_INVALID fail closed。"""
    _ctx, stored, intent = _single_slice_fixture()
    _disposition_type, _projection_type, project = _projection_api()

    with pytest.raises(CoordinationError) as exc_info:
        project(stored, "f" * 64, intent)
    assert exc_info.value.code == "SAGA_INTEGRITY_INVALID"


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("saga_id", "SGV2-WRONG"),
        ("execution_slice_hash", "9" * 64),
        ("grant_hash", "8" * 64),
        ("binding_set_hash", "7" * 64),
        ("host_instance_id", "host-wrong"),
    ),
)
def test_projection_rejects_dispatch_identity_or_admitted_lineage_mismatch(
    field_name: str,
    replacement: str,
) -> None:
    """Saga/Slice/grant/binding/Host 任一 lineage mismatch 都必须统一 fail closed。"""
    _ctx, stored, intent = _single_slice_fixture()
    stored = _with_slice_state(
        stored,
        slice_status=SliceReconciliationStatusV2.ADMITTED,
        saga_status=ExecutionSagaStatusV2.EXECUTING,
        admitted=True,
    )

    _assert_conflict(stored, replace(intent, **{field_name: replacement}))


@pytest.mark.parametrize(
    ("slice_status", "saga_status", "admitted", "expected"),
    (
        (
            SliceReconciliationStatusV2.NOT_STARTED,
            ExecutionSagaStatusV2.READY,
            False,
            None,
        ),
        (
            SliceReconciliationStatusV2.ADMISSION_RESERVED,
            ExecutionSagaStatusV2.EXECUTING,
            False,
            "RECOVERY_REQUIRED",
        ),
        (
            SliceReconciliationStatusV2.ADMITTED,
            ExecutionSagaStatusV2.EXECUTING,
            True,
            "RECOVERY_REQUIRED",
        ),
        (
            SliceReconciliationStatusV2.BLOCKED,
            ExecutionSagaStatusV2.FAILED,
            False,
            None,
        ),
        (
            SliceReconciliationStatusV2.HOST_COMMITTED,
            ExecutionSagaStatusV2.EXECUTING,
            True,
            "ERROR",
        ),
        (
            SliceReconciliationStatusV2.RECONCILING,
            ExecutionSagaStatusV2.EXECUTING,
            True,
            "ERROR",
        ),
        (
            SliceReconciliationStatusV2.SUCCEEDED,
            ExecutionSagaStatusV2.CONVERGENCE_PENDING,
            True,
            "ERROR",
        ),
        (
            SliceReconciliationStatusV2.FAILED_BEFORE_COMMIT,
            ExecutionSagaStatusV2.FAILED,
            True,
            "ERROR",
        ),
        (
            SliceReconciliationStatusV2.SCOPE_BREACH,
            ExecutionSagaStatusV2.PARTIALLY_COMMITTED,
            True,
            "ERROR",
        ),
        (
            SliceReconciliationStatusV2.VERIFY_FAILED,
            ExecutionSagaStatusV2.PARTIALLY_COMMITTED,
            True,
            "ERROR",
        ),
    ),
)
def test_absent_dispatch_intent_matrix(
    slice_status: SliceReconciliationStatusV2,
    saga_status: ExecutionSagaStatusV2,
    admitted: bool,
    expected: str | None,
) -> None:
    """intent 缺失只能落入冻结的合法 crash window；post-effect evidence loss 必须报错。"""
    _ctx, stored, _intent = _single_slice_fixture()
    stored = _with_slice_state(
        stored,
        slice_status=slice_status,
        saga_status=saga_status,
        admitted=admitted,
    )

    if expected == "ERROR":
        _assert_conflict(stored, None)
        return

    projection = _project(stored, None)
    assert (
        None if projection.disposition is None else projection.disposition.value
    ) == expected


@pytest.mark.parametrize(
    ("dispatch_status", "expected"),
    (
        (HostDispatchStatus.PREPARED, "RECOVERY_REQUIRED"),
        (HostDispatchStatus.DISPATCHED, "RECOVERY_REQUIRED"),
        (HostDispatchStatus.OUTCOME_UNKNOWN, "OUTCOME_UNKNOWN"),
        (HostDispatchStatus.HOST_COMMITTED, "RECOVERY_REQUIRED"),
        (HostDispatchStatus.SAFE_TO_RETRY, "SAFE_TO_RETRY"),
    ),
)
def test_nonterminal_dispatch_status_matrix(
    dispatch_status: HostDispatchStatus,
    expected: str,
) -> None:
    """非终态 Saga 下 dispatch status 必须投影成完整、闭世界的 active recovery truth。"""
    _ctx, stored, intent = _single_slice_fixture()
    stored = _with_slice_state(
        stored,
        slice_status=SliceReconciliationStatusV2.ADMITTED,
        saga_status=ExecutionSagaStatusV2.EXECUTING,
        admitted=True,
    )

    projection = _project(stored, _intent_with_status(intent, dispatch_status))
    assert projection.disposition is not None
    assert projection.disposition.value == expected


@pytest.mark.parametrize(
    ("saga_status", "slice_status", "dispatch_status"),
    (
        (
            ExecutionSagaStatusV2.SUCCEEDED,
            SliceReconciliationStatusV2.SUCCEEDED,
            HostDispatchStatus.HOST_COMMITTED,
        ),
        (
            ExecutionSagaStatusV2.SUCCEEDED,
            SliceReconciliationStatusV2.SUCCEEDED,
            HostDispatchStatus.RECONCILED,
        ),
        (
            ExecutionSagaStatusV2.FAILED,
            SliceReconciliationStatusV2.FAILED_BEFORE_COMMIT,
            HostDispatchStatus.SAFE_TO_RETRY,
        ),
    ),
)
def test_compatible_terminal_residual_evidence_has_no_active_recovery(
    saga_status: ExecutionSagaStatusV2,
    slice_status: SliceReconciliationStatusV2,
    dispatch_status: HostDispatchStatus,
) -> None:
    """兼容终态 evidence 可以保留 durable row，但不能被解释成 redispatch 指令。"""
    _ctx, stored, intent = _single_slice_fixture()
    stored = _with_slice_state(
        stored,
        slice_status=slice_status,
        saga_status=saga_status,
        admitted=True,
    )

    projection = _project(stored, _intent_with_status(intent, dispatch_status))
    assert projection.disposition is None


@pytest.mark.parametrize(
    "dispatch_status",
    (
        HostDispatchStatus.OUTCOME_UNKNOWN,
        HostDispatchStatus.PREPARED,
        HostDispatchStatus.DISPATCHED,
    ),
)
def test_terminal_saga_rejects_unresolved_or_backward_dispatch_evidence(
    dispatch_status: HostDispatchStatus,
) -> None:
    """terminal Saga/Slice 与 unresolved/backward dispatch evidence 不可同时为真。"""
    _ctx, stored, intent = _single_slice_fixture()
    stored = _with_slice_state(
        stored,
        slice_status=SliceReconciliationStatusV2.SUCCEEDED,
        saga_status=ExecutionSagaStatusV2.SUCCEEDED,
        admitted=True,
    )

    _assert_conflict(stored, _intent_with_status(intent, dispatch_status))


def build_reconciled_nonterminal_case():
    """构造 UnknownOutcomeRecovery 真实写序可达的 SUCCEEDED/CONVERGENCE_PENDING 组合。"""
    _ctx, stored, intent = _single_slice_fixture()
    stored = _with_slice_state(
        stored,
        slice_status=SliceReconciliationStatusV2.SUCCEEDED,
        saga_status=ExecutionSagaStatusV2.CONVERGENCE_PENDING,
        admitted=True,
        saga_revision=6,
    )
    reconciled = _intent_with_status(intent, HostDispatchStatus.RECONCILED)
    return stored, reconciled


def test_reconciled_intent_with_nonterminal_convergence_pending_has_no_active_recovery() -> None:
    """RECONCILED 表示 Host ambiguity 已收口；它不等于 Saga workflow 已经 terminal。"""
    stored, reconciled = build_reconciled_nonterminal_case()

    projection = _project(stored, reconciled)
    assert projection.disposition is None
