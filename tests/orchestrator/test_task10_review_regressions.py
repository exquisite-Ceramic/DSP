"""Task 10 review：补齐 execution recovery 合法中断窗口与外部恢复回读证据。"""

from __future__ import annotations

import os

import pytest
from design_execution_coordination import (
    HostFailed,
    HostFailurePhase,
    MaterializedCoordinationStatus,
    UnknownOutcomeRecovery,
    project_execution_recovery,
)
from design_execution_reconciliation import (
    ExecutionReconciliationServiceV2,
    HostDispatchStatus,
    InMemoryExecutionSagaStoreV2,
    InMemoryHostDispatchIntentStore,
)
from design_gateway_authorization import GatewayAuthorizationServiceV2
from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
from design_orchestrator.recovery import decide_apply_resume
from design_orchestrator.workflow_contracts import WorkflowCheckpointView, WorkflowPhase

from tests.execution_coordination.test_task8_execution_recovery_projection import (
    _single_slice_fixture,
)

requires_postgres = pytest.mark.skipif(
    not os.getenv("DSP_TEST_POSTGRES_DSN"),
    reason="DSP_TEST_POSTGRES_DSN is required",
)


class _BeforeCommitRecoveryProbe:
    """外部只读 recovery probe：明确证明原 Host mutation 未提交。"""

    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def resolve(self, execution_slice, dispatch_context):
        """记录 exact durable dispatch identity，并返回 BEFORE_COMMIT 正向证据。"""

        self.calls.append((execution_slice, dispatch_context))
        return HostFailed(
            phase=HostFailurePhase.BEFORE_COMMIT,
            failure_ref="TASK10_EXTERNAL_RECOVERY_NOT_COMMITTED",
            failed_at="2026-09-24T14:55:00Z",
        )


def _execution_owner_reader(
    *,
    saga_store: InMemoryExecutionSagaStoreV2,
    dispatch_store: InMemoryHostDispatchIntentStore,
) -> CanonicalWorkflowOwnerPorts:
    """只组合本回归会读取的真实 execution owner 依赖，其余 seam 不参与测试。"""

    unused = object()
    return CanonicalWorkflowOwnerPorts(
        snapshot_registry=unused,
        freshness_resolver=unused,
        workflow_artifact_store=unused,
        host_revision_observation=unused,
        canonical_operations=(),
        impact_analyzer=unused,
        impact_store=unused,
        approval_scope_planner=unused,
        approval_scope_store=unused,
        changeset_builder=unused,
        changeset_store=unused,
        materialization_planner=unused,
        materialization_plan_store=unused,
        topology_registry=unused,
        topology_environment_id=unused,
        topology_revision=unused,
        execution_plan_store=unused,
        revision_barrier=unused,
        gateway_authorization=unused,
        gateway_authorization_store=unused,
        coordination_clock=unused,
        provider_binding_store=unused,
        dispatch_intent_store=dispatch_store,
        execution_recovery_projection=project_execution_recovery,
        saga_store=saga_store,
        execution_coordinator=unused,
        reconciliation_service=unused,
        convergence_verifier=unused,
        semantic_reconstruction=unused,
        preview_port=unused,
        approval_admission=unused,
        materialization_routing=unused,
        provider_execution_snapshot=unused,
    )


@pytest.mark.parametrize(
    "confirm_admission",
    (False, True),
    ids=("ADMISSION_RESERVED", "ADMITTED"),
)
def test_pre_dispatch_crash_window_without_intent_routes_to_safe_wait(
    confirm_admission: bool,
) -> None:
    """真实 owner 的 pre-dispatch crash window 必须进入 RECOVER_OR_WAIT，而不是查询异常。"""

    ctx, initial, _intent = _single_slice_fixture()
    saga_store = InMemoryExecutionSagaStoreV2()
    stored = saga_store.create_saga(initial.definition)
    reconciliation = ExecutionReconciliationServiceV2(store=saga_store)
    slice_hash = stored.definition.ordered_slice_hashes[0]

    stored = reconciliation.reserve_slice_admission(
        stored.definition.saga_id,
        slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at="2026-09-24T14:30:00Z",
    )
    if confirm_admission:
        stored = reconciliation.confirm_slice_admitted(
            stored.definition.saga_id,
            ctx.authorities[0],
            expected_revision=stored.saga_revision,
        )

    dispatch_store = InMemoryHostDispatchIntentStore()
    assert (
        dispatch_store.get_for_saga_slice(stored.definition.saga_id, slice_hash)
        is None
    )

    adapter = _execution_owner_reader(
        saga_store=saga_store,
        dispatch_store=dispatch_store,
    )
    view = adapter.get_execution_owner_state(stored.definition.saga_id)
    checkpoint = WorkflowCheckpointView(
        task_id=f"task-review-{'admitted' if confirm_admission else 'reserved'}",
        phase=WorkflowPhase.APPLY_WAIT,
        saga_id=stored.definition.saga_id,
    )

    decision = decide_apply_resume(checkpoint=checkpoint, execution=view)

    assert decision.route == "RECOVER_OR_WAIT"
    assert dispatch_store.get_for_saga_slice(stored.definition.saga_id, slice_hash) is None


@requires_postgres
def test_explicit_external_recovery_is_visible_through_fresh_workflow_services(
    task10_postgres_execution_owner_factory,
) -> None:
    """显式 external recovery 后，fresh services 必须重读到更新后的 owner truth。"""

    # PostgreSQL/LangGraph 辅助模块只在此用例真正启用时导入；轻量 deterministic lane
    # 仍可收集并执行上面的 pre-dispatch 回归，不需要安装 runtime 依赖。
    from tests.orchestrator import test_real_owner_workflow_end_to_end as real_owner
    from tests.orchestrator import test_task10_durable_recovery as task10

    task_id = "task10-review-explicit-external-recovery"
    seed = real_owner._build_real_owner_case(task_id)
    real_owner._close_case(seed)
    host_port = task10._UnknownOutcomeHostPort()

    # runtime A 先制造真实 durable OUTCOME_UNKNOWN；后续 recovery 不得复用其连接。
    saga_a, dispatch_a = task10_postgres_execution_owner_factory()
    runtime_a = task10._fresh_runtime(
        seed,
        saga_store=saga_a,
        dispatch_store=dispatch_a,
        host_port=host_port,
    )
    try:
        waiting = task10._advance_to_execution(seed, runtime_a.runtime, task_id)
        assert waiting.phase is WorkflowPhase.APPLY_WAIT
        assert waiting.saga_id is not None
        assert waiting.execution_plan_ref is not None
        assert len(host_port.calls) == 1

        graph_values = task10._checkpoint_values(runtime_a.checkpointer, task_id)
        grant_value = graph_values.get("grant_ref")
        assert isinstance(grant_value, dict)
        grant_hash = grant_value.get("content_hash")
        assert isinstance(grant_hash, str) and grant_hash
        saga_id = waiting.saga_id
        execution_plan_ref = waiting.execution_plan_ref
    finally:
        runtime_a.artifact_store.close()
        runtime_a.checkpointer.close()
        task10._close_store(dispatch_a)
        task10._close_store(saga_a)

    # recovery boundary 必须逐项从 public owner truth 解析 exact inputs；禁止从 Host call
    # 参数或 runtime A 局部对象偷带 execution lineage。
    saga_recovery, dispatch_recovery = task10_postgres_execution_owner_factory()
    probe = _BeforeCommitRecoveryProbe()
    try:
        stored_saga = saga_recovery.get_saga(saga_id)
        assert stored_saga is not None

        execution_plan = seed.execution_store.get(execution_plan_ref.ref_id)
        assert execution_plan.execution_plan_hash == execution_plan_ref.content_hash
        assert len(execution_plan.execution_slices) == 1
        execution_slice = execution_plan.execution_slices[0]

        grant = seed.gateway_store.get_grant_v2(grant_hash)
        assert grant is not None
        gateway = GatewayAuthorizationServiceV2(seed.gateway_store)
        authority = gateway.admit_execution_grant(grant_hash, grant.issued_at)
        binding_set = seed.provider_store.get_by_hash(authority.binding_set_hash)
        assert binding_set is not None

        dispatch_intent = dispatch_recovery.get_for_saga_slice(
            saga_id,
            execution_slice.execution_slice_hash,
        )
        assert dispatch_intent is not None
        assert dispatch_intent.status is HostDispatchStatus.OUTCOME_UNKNOWN

        changeset = seed.changeset_store.get(execution_plan.changeset_id)
        boundary = seed.scope_store.get_boundary(
            execution_plan.approval_scope_ref.scope_id
        )
        recovery = UnknownOutcomeRecovery(
            reconciliation=ExecutionReconciliationServiceV2(store=saga_recovery),
            dispatch_intents=dispatch_recovery,
            outcome_probe=probe,
            evidence_port=real_owner._EvidenceBoundary(),
            canonical_changeset=changeset,
            approval_scope_boundary=boundary,
            clock=real_owner._ExecutionClock(),
        )

        recovered = recovery.recover(
            stored_saga=stored_saga,
            execution_slice=execution_slice,
            authority=authority,
            binding_set=binding_set,
            dispatch_intent=dispatch_intent,
        )
        assert recovered.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED
        assert recovered.failure_ref == "TASK10_EXTERNAL_RECOVERY_NOT_COMMITTED"
        assert len(probe.calls) == 1
        assert len(host_port.calls) == 1

        updated_intent = dispatch_recovery.get_for_saga_slice(
            saga_id,
            execution_slice.execution_slice_hash,
        )
        assert updated_intent is not None
        assert updated_intent.dispatch_intent_id == dispatch_intent.dispatch_intent_id
        assert updated_intent.status is HostDispatchStatus.SAFE_TO_RETRY
    finally:
        task10._close_store(dispatch_recovery)
        task10._close_store(saga_recovery)

    # fresh services 使用新的 PostgreSQL Saga/dispatch connections 重新读取同一 owner truth；
    # 不调用 workflow 自动 recovery，也不授权新的 Host mutation。
    saga_b, dispatch_b = task10_postgres_execution_owner_factory()
    runtime_b = task10._fresh_runtime(
        seed,
        saga_store=saga_b,
        dispatch_store=dispatch_b,
        host_port=host_port,
    )
    try:
        execution_view = runtime_b.services.get_execution_owner_state(saga_id)
        assert execution_view.active_dispatch_recovery is not None
        assert execution_view.active_dispatch_recovery.state.value == "SAFE_TO_RETRY"

        decision = decide_apply_resume(checkpoint=waiting, execution=execution_view)
        assert decision.route == "RECOVER_OR_WAIT"
        assert len(host_port.calls) == 1

        reread_intent = dispatch_b.get_for_saga_slice(
            saga_id,
            execution_slice.execution_slice_hash,
        )
        assert reread_intent is not None
        assert reread_intent.dispatch_intent_id == dispatch_intent.dispatch_intent_id
        assert reread_intent.status is HostDispatchStatus.SAFE_TO_RETRY
    finally:
        runtime_b.artifact_store.close()
        runtime_b.checkpointer.close()
        task10._close_store(dispatch_b)
        task10._close_store(saga_b)
