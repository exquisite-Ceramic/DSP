"""Task 15：Cross-Host Product Vertical real-owner recovery matrix。"""

from __future__ import annotations

import os

import psycopg
import pytest
from design_execution_coordination import (
    ExecutionRecoveryDisposition,
    project_execution_recovery,
)
from design_execution_reconciliation import (
    ExecutionReconciliationServiceV2,
    HostDispatchStatus,
    build_host_dispatch_intent,
)
from design_execution_reconciliation.postgres import (
    apply_execution_saga_migrations,
    connect_postgres,
)
from design_execution_reconciliation.postgres_dispatch_intent import (
    PostgresHostDispatchIntentStore,
)
from design_execution_reconciliation.postgres_evidence import (
    PostgresReconciliationEvidenceStore,
)
from design_execution_reconciliation.postgres_saga_store_v2 import (
    PostgresExecutionSagaStoreV2,
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
from tests.execution_reconciliation._support import signed_bundle, signed_delta

_PROJECT_ID = "project-cross-host-recovery-task15"


def _dsn() -> str:
    """只在显式 PostgreSQL lane 中执行 crash/restart recovery acceptance。"""

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _reset_and_migrate(dsn: str) -> None:
    """用 execution owner 自己的 migrations 建立 fresh durable state。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS execution_saga CASCADE")
    conn = connect_postgres(dsn)
    try:
        apply_execution_saga_migrations(conn)
    finally:
        conn.close()


def _assigned_tasks(stored, changeset, slice_hash: str):
    """读取 Saga definition 已冻结的 validation task 分配，不自创 recovery 规则。"""

    assignment = next(
        item
        for item in stored.definition.slice_validation_assignments
        if item.execution_slice_hash == slice_hash
    )
    by_id = {item.validation_task_id: item for item in changeset.validation_tasks}
    return tuple(by_id[item] for item in assignment.validation_task_ids)


def _complete_first_slice(
    *,
    ctx,
    service,
    dispatches,
    stored,
    index: int,
):
    """按 production coordinator 同一顺序完成第一 Slice 的本地 reconciliation。"""

    execution_slice = ctx.execution_plan.execution_slices[index]
    authority = ctx.authorities[index]
    stored = service.reserve_slice_admission(
        stored.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at="2026-10-07T06:40:00Z",
    )
    stored = service.confirm_slice_admitted(
        stored.definition.saga_id,
        authority,
        expected_revision=stored.saga_revision,
    )

    intent = dispatches.prepare(
        build_host_dispatch_intent(
            saga_id=stored.definition.saga_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            grant_hash=authority.grant_hash,
            binding_set_hash=authority.binding_set_hash,
            host_instance_id=authority.host_instance_id,
            document_ref=execution_slice.host_runtime_ref.document_ref,
            expected_host_revision="10",
            prepared_at="2026-10-07T06:40:01Z",
        )
    )
    intent = dispatches.mark_dispatched(
        intent.dispatch_intent_id,
        expected_revision=intent.intent_revision,
        observed_at="2026-10-07T06:40:02Z",
    )

    delta = signed_delta(ctx, index)
    assert service.persist_actual_delta(delta) == delta.actual_delta_hash
    intent = dispatches.mark_host_committed(
        intent.dispatch_intent_id,
        expected_revision=intent.intent_revision,
        evidence_hash=delta.actual_delta_hash,
        observed_at="2026-10-07T06:40:03Z",
    )
    stored = service.record_host_commit(
        stored.definition.saga_id,
        delta,
        expected_revision=stored.saga_revision,
        committed_at="2026-10-07T06:40:03Z",
    )
    stored = service.begin_reconciliation(
        stored.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=stored.saga_revision,
    )
    scope = service.compare_scope(
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
        execution_slice=execution_slice,
        authority=authority,
        actual_delta=delta,
    )
    stored = service.record_scope_result(
        stored.definition.saga_id,
        scope,
        expected_revision=stored.saga_revision,
    )

    bundle = signed_bundle(ctx, delta, index)
    assert (
        service.persist_verification_bundle(bundle)
        == bundle.evidence_bundle_hash
    )
    verification = service.verify_semantics(
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
        execution_slice=execution_slice,
        authority=authority,
        actual_delta=delta,
        validation_tasks=_assigned_tasks(
            stored,
            ctx.case.changeset,
            execution_slice.execution_slice_hash,
        ),
        verification_evidence_bundle=bundle,
        verified_at="2026-10-07T06:40:04Z",
    )
    assert (
        service.persist_verification_result(verification)
        == verification.verification_hash
    )
    stored = service.record_verification_result(
        stored.definition.saga_id,
        verification,
        expected_revision=stored.saga_revision,
        reconciled_at="2026-10-07T06:40:05Z",
    )
    intent = dispatches.mark_reconciled(
        intent.dispatch_intent_id,
        expected_revision=intent.intent_revision,
        evidence_hash=verification.verification_hash,
        observed_at="2026-10-07T06:40:06Z",
    )
    assert intent.status is HostDispatchStatus.RECONCILED
    return stored


def _leave_second_outcome_unknown(
    *,
    ctx,
    service,
    dispatches,
    stored,
    index: int,
):
    """让第二 Slice 停在已发送但 response 未知的真实 durable window。"""

    execution_slice = ctx.execution_plan.execution_slices[index]
    authority = ctx.authorities[index]
    stored = service.reserve_slice_admission(
        stored.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at="2026-10-07T06:41:00Z",
    )
    stored = service.confirm_slice_admitted(
        stored.definition.saga_id,
        authority,
        expected_revision=stored.saga_revision,
    )
    intent = dispatches.prepare(
        build_host_dispatch_intent(
            saga_id=stored.definition.saga_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            grant_hash=authority.grant_hash,
            binding_set_hash=authority.binding_set_hash,
            host_instance_id=authority.host_instance_id,
            document_ref=execution_slice.host_runtime_ref.document_ref,
            expected_host_revision="10",
            prepared_at="2026-10-07T06:41:01Z",
        )
    )
    intent = dispatches.mark_dispatched(
        intent.dispatch_intent_id,
        expected_revision=intent.intent_revision,
        observed_at="2026-10-07T06:41:02Z",
    )
    intent = dispatches.mark_outcome_unknown(
        intent.dispatch_intent_id,
        expected_revision=intent.intent_revision,
        failure_ref="TASK15_RESPONSE_LOST",
        observed_at="2026-10-07T06:41:03Z",
    )
    assert intent.status is HostDispatchStatus.OUTCOME_UNKNOWN
    return stored


def test_restart_projects_all_required_dispatch_truth_without_forward_execute() -> None:
    """重启后只读 Saga/dispatch truth；任一 unresolved required Slice 都强制 recover/wait。"""

    dsn = _dsn()
    _reset_and_migrate(dsn)
    ctx = phase_i_readiness_inputs(project_id=_PROJECT_ID)

    saga_store = PostgresExecutionSagaStoreV2(dsn)
    dispatches = PostgresHostDispatchIntentStore(dsn)
    evidence = PostgresReconciliationEvidenceStore(dsn)
    try:
        service = ExecutionReconciliationServiceV2(
            store=saga_store,
            evidence_store=evidence,
        )
        stored = service.create_saga(
            ctx.case.changeset,
            ctx.case.boundary_v2,
            ctx.materialization_plan,
            ctx.execution_plan,
        )
        stored = _complete_first_slice(
            ctx=ctx,
            service=service,
            dispatches=dispatches,
            stored=stored,
            index=0,
        )
        stored = _leave_second_outcome_unknown(
            ctx=ctx,
            service=service,
            dispatches=dispatches,
            stored=stored,
            index=1,
        )
        saga_id = stored.definition.saga_id
    finally:
        evidence.close()
        dispatches.close()
        saga_store.close()

    # 模拟 composition/process restart：新连接只读取 durable owners。
    reopened_saga = PostgresExecutionSagaStoreV2(dsn)
    reopened_dispatch = PostgresHostDispatchIntentStore(dsn)
    try:
        durable = reopened_saga.get_saga(saga_id)
        assert durable is not None
        projections = []
        intents = []
        for slice_hash in durable.definition.ordered_slice_hashes:
            intent = reopened_dispatch.get_for_saga_slice(saga_id, slice_hash)
            intents.append(intent)
            projections.append(
                project_execution_recovery(durable, slice_hash, intent)
            )

        assert projections[0].disposition is None
        assert (
            projections[1].disposition
            is ExecutionRecoveryDisposition.OUTCOME_UNKNOWN
        )
        assert intents[1] is not None

        recovery = HostDispatchRecoveryView(
            dispatch_intent_id=str(intents[1].dispatch_intent_id),
            execution_slice_hash=durable.definition.ordered_slice_hashes[1],
            state=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
        )
        owner_view = ExecutionOwnerView(
            saga=ExecutionSagaView(
                saga_id=saga_id,
                saga_revision=durable.saga_revision,
                status=durable.status.value,
                active_slice_hash=None,
            ),
            unresolved_dispatch_recoveries=(recovery,),
        )
        decision = decide_apply_resume(
            checkpoint=WorkflowCheckpointView(
                task_id=ctx.case.changeset.task_id,
                phase=WorkflowPhase.APPLY_WAIT,
                saga_id=saga_id,
            ),
            execution=owner_view,
        )

        assert decision.route == "RECOVER_OR_WAIT"
        assert "OUTCOME_UNKNOWN" in decision.reason
    finally:
        reopened_dispatch.close()
        reopened_saga.close()
