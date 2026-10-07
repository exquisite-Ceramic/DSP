"""Cross-Host Product Vertical Task 11：multi-slice execution recovery truth。"""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_coordination import project_execution_recovery
from design_execution_reconciliation import (
    ExecutionSagaBuilderV2,
    ExecutionSagaStatusV2,
    HostDispatchStatus,
    SliceReconciliationStateV2,
    SliceReconciliationStatusV2,
    StoredExecutionSagaV2,
    build_host_dispatch_intent,
)
from design_orchestrator.recovery import decide_apply_resume
from design_orchestrator.workflow_contracts import WorkflowCheckpointView, WorkflowPhase
from design_orchestrator.workflow_services import (
    ExecutionOwnerView,
    ExecutionSagaView,
    HostDispatchRecoveryState,
    HostDispatchRecoveryView,
)

from tests.execution_coordination._support import phase_i_readiness_inputs
from tests.orchestrator.test_canonical_owner_ports import _task6_adapter
from tests.orchestrator.test_workflow_resume_authoritative_truth import (
    _ResumeServices,
    _seed_after_execution_grant,
)


def _recovery(
    *,
    index: int,
    state: HostDispatchRecoveryState,
) -> HostDispatchRecoveryView:
    """构造有稳定 Slice/dispatch identity 的 workflow-facing recovery view。"""

    return HostDispatchRecoveryView(
        dispatch_intent_id=f"dispatch-task11-{index}",
        execution_slice_hash=f"{index + 1:x}" * 64,
        state=state,
    )


def _owner_view(
    *recoveries: HostDispatchRecoveryView,
    status: str = "EXECUTING",
) -> ExecutionOwnerView:
    """构造多 Slice execution-owner view，不人为挑选 active item。"""

    return ExecutionOwnerView(
        saga=ExecutionSagaView(
            saga_id="saga-task11",
            saga_revision=9,
            status=status,
            active_slice_hash=None,
        ),
        unresolved_dispatch_recoveries=tuple(recoveries),
    )


def _checkpoint() -> WorkflowCheckpointView:
    """返回已有 durable Saga identity 的 apply checkpoint。"""

    return WorkflowCheckpointView(
        task_id="task-task11",
        phase=WorkflowPhase.APPLY_WAIT,
        saga_id="saga-task11",
    )


def test_execution_owner_view_canonicalizes_legacy_single_recovery() -> None:
    """旧 active field 必须投影到 canonical tuple，保持单 Slice consumer 兼容。"""

    recovery = _recovery(
        index=0,
        state=HostDispatchRecoveryState.RECOVERY_REQUIRED,
    )
    view = ExecutionOwnerView(
        saga=ExecutionSagaView(
            saga_id="saga-task11",
            saga_revision=1,
            status="EXECUTING",
            active_slice_hash=recovery.execution_slice_hash,
        ),
        active_dispatch_recovery=recovery,
    )

    assert view.unresolved_dispatch_recoveries == (recovery,)
    assert view.active_dispatch_recovery == recovery


def test_execution_owner_view_projects_one_item_tuple_to_legacy_field() -> None:
    """新 tuple 只有一项时，legacy field 仍可继续读取同一个 recovery。"""

    recovery = _recovery(
        index=0,
        state=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
    )
    view = _owner_view(recovery)

    assert view.unresolved_dispatch_recoveries == (recovery,)
    assert view.active_dispatch_recovery == recovery


def test_execution_owner_view_rejects_conflicting_or_duplicate_representations() -> None:
    """multi-slice tuple 不能与 legacy single field 并存，也不能重复 Slice identity。"""

    first = _recovery(
        index=0,
        state=HostDispatchRecoveryState.RECOVERY_REQUIRED,
    )
    second = _recovery(
        index=1,
        state=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
    )

    with pytest.raises(ValueError):
        ExecutionOwnerView(
            saga=ExecutionSagaView(
                saga_id="saga-task11",
                saga_revision=1,
                status="EXECUTING",
                active_slice_hash=None,
            ),
            active_dispatch_recovery=first,
            unresolved_dispatch_recoveries=(first, second),
        )

    duplicate = replace(
        second,
        execution_slice_hash=first.execution_slice_hash,
    )
    with pytest.raises(ValueError):
        _owner_view(first, duplicate)


def test_outcome_unknown_on_one_slice_masks_no_other_slice_success() -> None:
    """任一 unresolved OUTCOME_UNKNOWN 都必须压过其它 Slice 已成功的局部事实。"""

    view = _owner_view(
        _recovery(
            index=1,
            state=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
        ),
        status="CONVERGENCE_PENDING",
    )
    decision = decide_apply_resume(checkpoint=_checkpoint(), execution=view)

    assert decision.route == "RECOVER_OR_WAIT"
    assert "OUTCOME_UNKNOWN" in decision.reason


def test_two_unresolved_slices_project_recover_or_wait_without_arbitrary_selection() -> None:
    """两个 unresolved Slice 必须整体阻止 redispatch，不允许挑任一 Slice 当作唯一 active。"""

    first = _recovery(
        index=0,
        state=HostDispatchRecoveryState.RECOVERY_REQUIRED,
    )
    second = _recovery(
        index=1,
        state=HostDispatchRecoveryState.SAFE_TO_RETRY,
    )
    view = _owner_view(first, second, status="READY")

    decision = decide_apply_resume(checkpoint=_checkpoint(), execution=view)

    assert view.active_dispatch_recovery is None
    assert view.unresolved_dispatch_recoveries == (first, second)
    assert decision.route == "RECOVER_OR_WAIT"
    assert first.dispatch_intent_id in decision.reason
    assert second.dispatch_intent_id in decision.reason


class _SagaStore:
    """只读返回一个真实双 Slice StoredExecutionSagaV2。"""

    def __init__(self, stored: StoredExecutionSagaV2) -> None:
        self.stored = stored

    def get_saga(self, saga_id: str):
        """按 exact saga id 返回 owner truth。"""

        if saga_id == self.stored.definition.saga_id:
            return self.stored
        return None


class _DispatchStore:
    """按 Saga/Slice exact key 返回 durable dispatch intent 并记录读取顺序。"""

    def __init__(self, by_slice) -> None:
        self.by_slice = dict(by_slice)
        self.calls: list[tuple[str, str]] = []

    def get_for_saga_slice(self, saga_id: str, slice_hash: str):
        """只读 exact dispatch identity。"""

        self.calls.append((saga_id, slice_hash))
        return self.by_slice.get(slice_hash)


def _stored_multi_slice_case():
    """构造一个 Slice 已 reconciled、另一个 outcome unknown 的真实双 Slice Saga。"""

    ctx = phase_i_readiness_inputs()
    definition = ExecutionSagaBuilderV2().build(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
    )
    states = []
    intents = []
    for index, (execution_slice, authority) in enumerate(
        zip(ctx.execution_plan.execution_slices, ctx.authorities, strict=True)
    ):
        state = SliceReconciliationStateV2(
            execution_slice_hash=execution_slice.execution_slice_hash,
            sequence_index=index,
            materialization_plan_hash=definition.materialization_plan_hash,
            status=(
                SliceReconciliationStatusV2.SUCCEEDED
                if index == 0
                else SliceReconciliationStatusV2.ADMITTED
            ),
            materialization_id=authority.materialization_id,
            approval_hash=authority.approval_hash,
            grant_hash=authority.grant_hash,
            binding_set_hash=authority.binding_set_hash,
            admitted_host_instance_id=authority.host_instance_id,
        )
        states.append(state)
        intent = build_host_dispatch_intent(
            saga_id=definition.saga_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            grant_hash=authority.grant_hash,
            binding_set_hash=authority.binding_set_hash,
            host_instance_id=authority.host_instance_id,
            document_ref=execution_slice.host_runtime_ref.document_ref,
            expected_host_revision=str(100 + index),
            prepared_at=f"2026-10-07T02:0{index}:00Z",
        )
        intent = replace(
            intent,
            status=(
                HostDispatchStatus.RECONCILED
                if index == 0
                else HostDispatchStatus.OUTCOME_UNKNOWN
            ),
            intent_revision=(3 if index == 0 else 2),
        )
        intents.append(intent)

    stored = StoredExecutionSagaV2(
        definition=definition,
        saga_revision=7,
        status=ExecutionSagaStatusV2.EXECUTING,
        slice_states=tuple(states),
    )
    return ctx, stored, tuple(intents)


def test_multi_slice_owner_projection_reads_every_slice_in_saga_order() -> None:
    """adapter 必须逐个投影 immutable Saga Slice，不能 arbitrary-select 一个 active Slice。"""

    _ctx, stored, intents = _stored_multi_slice_case()
    dispatch_store = _DispatchStore(
        {
            intent.execution_slice_hash: intent
            for intent in intents
        }
    )
    adapter, *_ = _task6_adapter(
        overrides={
            "saga_store": _SagaStore(stored),
            "dispatch_intent_store": dispatch_store,
            "execution_recovery_projection": project_execution_recovery,
        }
    )

    view = adapter.get_execution_owner_state(stored.definition.saga_id)

    assert dispatch_store.calls == [
        (stored.definition.saga_id, slice_hash)
        for slice_hash in stored.definition.ordered_slice_hashes
    ]
    assert tuple(
        item.execution_slice_hash
        for item in view.unresolved_dispatch_recoveries
    ) == (stored.definition.ordered_slice_hashes[1],)
    assert (
        view.unresolved_dispatch_recoveries[0].state
        is HostDispatchRecoveryState.OUTCOME_UNKNOWN
    )
    assert view.active_dispatch_recovery == view.unresolved_dispatch_recoveries[0]


def test_restart_with_existing_dispatch_does_not_call_execute_or_readiness() -> None:
    """fresh graph 恢复 unresolved multi-slice truth 时只能 wait，不能重新 begin/execute。"""

    view = _owner_view(
        _recovery(
            index=0,
            state=HostDispatchRecoveryState.RECOVERY_REQUIRED,
        ),
        _recovery(
            index=1,
            state=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
        ),
        status="EXECUTING",
    )
    services = _ResumeServices(view)
    graph, config = _seed_after_execution_grant(
        services=services,
        saga_id="saga-task11",
    )

    graph.invoke(None, config)

    assert services.begin_count == 0
    assert services.calls == ["refresh:saga-task11"]


def test_committed_slice_is_never_redispatched_after_composition_rebuild() -> None:
    """已有 Host-effect truth 时，即使聚合 Saga READY 也不能把恢复解释成新 dispatch。"""

    view = _owner_view(
        _recovery(
            index=1,
            state=HostDispatchRecoveryState.SAFE_TO_RETRY,
        ),
        status="READY",
    )
    services = _ResumeServices(view)
    graph, config = _seed_after_execution_grant(
        services=services,
        saga_id="saga-task11",
    )

    graph.invoke(None, config)

    assert services.begin_count == 0
    assert services.calls == ["refresh:saga-task11"]
