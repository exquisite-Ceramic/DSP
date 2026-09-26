from __future__ import annotations

from dataclasses import replace

import psycopg
import pytest
from design_orchestrator import WorkflowPhase, WorkflowResumeCommand
from design_product_runtime import (
    ProductFlowStatus,
    ProductTaskRequestError,
    RevitSemanticBoundaryError,
)


def _submit_to_proposal(case):
    """把真实 ProductFlow 推进到 operation proposal HITL，并返回冻结 pause。"""

    proposal = case.flow.submit(case.request)
    assert proposal.status is ProductFlowStatus.WAITING
    assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert proposal.checkpoint.pending_interaction is not None
    assert case.host.execute_count == 0
    return proposal


def _accept(case, proposal):
    """只通过公共 ProductFlow resume 接受当前 exact proposal。"""

    return case.flow.resume(
        case.task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            pause_id=proposal.checkpoint.pending_interaction.pause_id,
        ),
    )


def test_operation_proposal_reject_cancels_without_host_mutation(
    revit_wall_thickness_product_case,
) -> None:
    """场景 2/19：用户拒绝 operation proposal 后产品取消，Revit 不得执行写操作。"""

    case = revit_wall_thickness_product_case("task-product-proposal-reject")
    proposal = _submit_to_proposal(case)

    cancelled = case.flow.resume(
        case.task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_REJECTED",
            pause_id=proposal.checkpoint.pending_interaction.pause_id,
        ),
    )

    assert cancelled.status is ProductFlowStatus.CANCELLED
    assert cancelled.workflow_phase is WorkflowPhase.CANCELLED
    assert cancelled.saga_id is None
    assert case.host.execute_count == 0
    assert "set_wall_thickness" not in case.host.command_operations()


def test_stale_context_never_executes_with_the_stale_revision(
    revit_wall_thickness_product_case,
) -> None:
    """场景 3/19：proposal 后 Host revision 漂移时，后续写入必须先经过 freshness 并使用新 revision。"""

    case = revit_wall_thickness_product_case("task-product-stale-context")
    proposal = _submit_to_proposal(case)

    # 模拟用户确认前发生外部 Revit 编辑；42 已经成为 stale context revision。
    case.host.current_revision = 43

    completed = _accept(case, proposal)

    assert completed.status is ProductFlowStatus.SUCCEEDED
    assert case.host.execute_count == 1
    execute_commands = [
        command
        for command in case.host.commands
        if command.operation == "set_wall_thickness"
    ]
    assert len(execute_commands) == 1
    assert execute_commands[0].preconditions == [{"revision": 43}]
    assert case.host.current_revision == 44

    # 证明没有拿旧 context revision=42 直接写 Host；真实 operation-freshness 路径已经
    # 在 EXECUTE 前按当前 revision 重建 PlanningSnapshot，并把 43 冻进 binding hash。
    execute_index = case.host.commands.index(execute_commands[0])
    assert any(
        command.operation == "read_wall_thickness_snapshot"
        and index < execute_index
        and case.host.command_revisions[index] == 43
        for index, command in enumerate(case.host.commands)
    )


def test_parameter_context_lineage_mismatch_fails_closed_before_execution(
    revit_wall_thickness_product_case,
) -> None:
    """场景 4/19：authoritative ContextSnapshot hash 漂移后 binder lineage 必须 fail closed。"""

    case = revit_wall_thickness_product_case("task-product-context-lineage-mismatch")
    proposal = _submit_to_proposal(case)
    context_ref = proposal.checkpoint.context_snapshot_ref
    assert context_ref is not None
    snapshot = case.snapshot_registry.get_snapshot(context_ref.ref_id)

    # 这是显式 corruption injection，不是第二个 semantic owner。保留 hash 前 12 位可让
    # snapshot 自身 content-addressed id 仍合法，从而精确触发 StableRef/full-hash mismatch。
    replacement = "0" if snapshot.hash[12] != "0" else "1"
    mismatched_hash = f"{snapshot.hash[:12]}{replacement}{snapshot.hash[13:]}"
    corrupted = replace(snapshot, hash=mismatched_hash)
    case.snapshot_registry._snapshots[snapshot.snapshot_id] = corrupted

    with pytest.raises(
        (ValueError, RevitSemanticBoundaryError),
        match="hash|snapshot|ContextSnapshot|lineage",
    ):
        _accept(case, proposal)

    assert case.host.execute_count == 0
    assert "set_wall_thickness" not in case.host.command_operations()


def test_request_unavailable_before_binding_has_no_latest_or_current_fallback(
    revit_wall_thickness_product_case,
    product_task_postgres_dsn: str,
) -> None:
    """场景 6a/19：binder 前 exact request 行消失时必须失败，不能退回 latest/current request。"""

    case = revit_wall_thickness_product_case("task-product-request-unavailable")
    proposal = _submit_to_proposal(case)

    with psycopg.connect(product_task_postgres_dsn, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM product_task.request WHERE task_id = %s",
            (case.task_id,),
        )

    with pytest.raises(RevitSemanticBoundaryError) as captured:
        _accept(case, proposal)

    assert captured.value.code == "REVIT_PRODUCT_REQUEST_UNAVAILABLE"
    assert case.host.execute_count == 0
    assert "set_wall_thickness" not in case.host.command_operations()


def test_request_hash_mismatch_before_binding_fails_integrity_without_execution(
    revit_wall_thickness_product_case,
    product_task_postgres_dsn: str,
) -> None:
    """场景 6b/19：binder 前 request hash 被篡改时 owner integrity 必须阻止任何 Host mutation。"""

    case = revit_wall_thickness_product_case("task-product-request-hash-mismatch")
    proposal = _submit_to_proposal(case)

    with psycopg.connect(product_task_postgres_dsn, autocommit=True) as conn:
        conn.execute(
            "UPDATE product_task.request SET request_hash = %s WHERE task_id = %s",
            ("0" * 64, case.task_id),
        )

    with pytest.raises(ProductTaskRequestError) as captured:
        _accept(case, proposal)

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"
    assert case.host.execute_count == 0
    assert "set_wall_thickness" not in case.host.command_operations()
