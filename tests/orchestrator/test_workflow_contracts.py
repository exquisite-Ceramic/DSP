"""ADR-010 Workflow Orchestrator 公共契约的 RED 测试。

本文件只冻结 framework-neutral、checkpoint-safe 的公共边界；LangGraph 的 StateGraph、
Command、checkpointer 等类型必须留在 runtime adapter 内部，不能进入 DSP 公共契约。
"""

from __future__ import annotations

import inspect
from dataclasses import fields

import pytest
from design_orchestrator import workflow_contracts, workflow_port
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)


def test_required_identifiers_are_trimmed_and_blank_values_are_rejected() -> None:
    """所有稳定身份都必须拒绝空白，同时把合法文本规范化为去首尾空白的值。"""

    assert StableRef("  snapshot-1  ").ref_id == "snapshot-1"
    assert AsyncOperationRef(
        kind=AsyncOperationKind.RECONSTRUCTION_JOB,
        owner="  semantic-runtime  ",
        operation_id="  reconstruction-1  ",
    ) == AsyncOperationRef(
        kind=AsyncOperationKind.RECONSTRUCTION_JOB,
        owner="semantic-runtime",
        operation_id="reconstruction-1",
    )

    for factory in (
        lambda: StableRef("   "),
        lambda: AsyncOperationRef(
            kind=AsyncOperationKind.OTHER,
            owner=" ",
            operation_id="op-1",
        ),
        lambda: AsyncOperationRef(
            kind=AsyncOperationKind.OTHER,
            owner="owner-1",
            operation_id=" ",
        ),
        lambda: WorkflowCheckpointView(task_id=" ", phase=WorkflowPhase.RESOLVE_INTENT),
        lambda: WorkflowStartRequest(task_id=" "),
    ):
        with pytest.raises(ValueError):
            factory()


def test_optional_content_hash_requires_lowercase_sha256() -> None:
    """StableRef 的可选内容哈希只能携带 canonical lowercase SHA-256。"""

    digest = "a" * 64
    assert StableRef("snapshot-1", digest).content_hash == digest

    for bad_hash in ("A" * 64, "abc", "g" * 64):
        with pytest.raises(ValueError):
            StableRef("snapshot-1", bad_hash)


def test_checkpoint_contains_stable_refs_instead_of_authoritative_objects() -> None:
    """Checkpoint view 只保存 stable refs 与 workflow-local 导航信息。"""

    snapshot = StableRef("snapshot-1", "b" * 64)
    operation = StableRef("operation-1", "c" * 64)
    waiting = AsyncOperationRef(
        kind=AsyncOperationKind.INTERACTION_SESSION,
        owner="interaction",
        operation_id="interaction-1",
    )

    view = WorkflowCheckpointView(
        task_id=" task-1 ",
        phase="PARAMETER_BINDING",
        context_snapshot_ref=snapshot,
        operation_ref=operation,
        interaction_ref=waiting,
        async_operation_ref=waiting,
        saga_id=" saga-1 ",
    )

    assert view.task_id == "task-1"
    assert view.phase is WorkflowPhase.PARAMETER_BINDING
    assert view.context_snapshot_ref is snapshot
    assert view.operation_ref is operation
    assert view.saga_id == "saga-1"


def test_start_and_resume_requests_copy_workflow_local_payloads() -> None:
    """调用者后续修改原 mapping 时，不得悄悄改写已经创建的 workflow command。"""

    start_payload = {"intent_text": "thicken wall"}
    resume_payload = {"approved": True}

    request = WorkflowStartRequest(
        task_id="task-1",
        request_data=start_payload,
        initial_host_ref=StableRef("host-1"),
        initial_context_ref=StableRef("snapshot-1"),
    )
    command = WorkflowResumeCommand(
        resume_kind="HITL_DECISION",
        payload=resume_payload,
    )

    start_payload["intent_text"] = "mutated"
    resume_payload["approved"] = False

    assert request.request_data == {"intent_text": "thicken wall"}
    assert command.payload == {"approved": True}


def test_pending_interaction_contract_normalizes_identity_and_allowed_kinds() -> None:
    """Human pause 必须有稳定 pause identity、typed kind 与非空唯一 resume kind 集合。"""

    pending_kind = workflow_contracts.PendingInteractionKind
    pending_view = workflow_contracts.PendingInteractionView
    subject = StableRef("operation-space-1", "d" * 64)

    pending = pending_view(
        pause_id="  pause-1  ",
        kind="OPERATION_PROPOSAL",
        subject_ref=subject,
        allowed_resume_kinds=(
            "  OPERATION_PROPOSAL_ACCEPTED  ",
            "OPERATION_PROPOSAL_REJECTED",
        ),
    )

    assert pending.pause_id == "pause-1"
    assert pending.kind is pending_kind.OPERATION_PROPOSAL
    assert pending.subject_ref is subject
    assert pending.allowed_resume_kinds == (
        "OPERATION_PROPOSAL_ACCEPTED",
        "OPERATION_PROPOSAL_REJECTED",
    )

    for factory in (
        lambda: pending_view(
            pause_id=" ",
            kind=pending_kind.OPERATION_PROPOSAL,
            subject_ref=subject,
            allowed_resume_kinds=("OPERATION_PROPOSAL_ACCEPTED",),
        ),
        lambda: pending_view(
            pause_id="pause-1",
            kind=pending_kind.OPERATION_PROPOSAL,
            subject_ref=subject,
            allowed_resume_kinds=(),
        ),
        lambda: pending_view(
            pause_id="pause-1",
            kind=pending_kind.OPERATION_PROPOSAL,
            subject_ref=subject,
            allowed_resume_kinds=("OPERATION_PROPOSAL_ACCEPTED", " "),
        ),
        lambda: pending_view(
            pause_id="pause-1",
            kind=pending_kind.OPERATION_PROPOSAL,
            subject_ref=subject,
            allowed_resume_kinds=(
                "OPERATION_PROPOSAL_ACCEPTED",
                "OPERATION_PROPOSAL_ACCEPTED",
            ),
        ),
        lambda: pending_view(
            pause_id="pause-1",
            kind=pending_kind.OPERATION_PROPOSAL,
            subject_ref="operation-space-1",
            allowed_resume_kinds=("OPERATION_PROPOSAL_ACCEPTED",),
        ),
    ):
        with pytest.raises((TypeError, ValueError)):
            factory()


def test_hitl_additions_preserve_resume_command_source_compatibility() -> None:
    """pause_id 只能 trailing additive；既有 async resume construction 必须继续合法。"""

    assert [field.name for field in fields(WorkflowResumeCommand)] == [
        "resume_kind",
        "payload",
        "pause_id",
    ]

    command = WorkflowResumeCommand(
        resume_kind="ASYNC_OPERATION_COMPLETED",
        payload={"operation_id": "op-1"},
    )
    assert command.pause_id is None

    human = WorkflowResumeCommand(
        resume_kind=" OPERATION_PROPOSAL_ACCEPTED ",
        payload={},
        pause_id=" pause-1 ",
    )
    assert human.resume_kind == "OPERATION_PROPOSAL_ACCEPTED"
    assert human.pause_id == "pause-1"

    with pytest.raises(ValueError):
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            pause_id=" ",
        )


def test_checkpoint_human_wait_is_mutually_exclusive_with_external_waits() -> None:
    """Public checkpoint 不得同时宣称 human pending 与 external async/interaction wait。"""

    pending = workflow_contracts.PendingInteractionView(
        pause_id="pause-1",
        kind=workflow_contracts.PendingInteractionKind.OPERATION_PROPOSAL,
        subject_ref=StableRef("operation-space-1", "e" * 64),
        allowed_resume_kinds=("OPERATION_PROPOSAL_ACCEPTED",),
    )
    external = AsyncOperationRef(
        kind=AsyncOperationKind.INTERACTION_SESSION,
        owner="interaction",
        operation_id="interaction-1",
    )

    view = WorkflowCheckpointView(
        task_id="task-1",
        phase="AWAIT_OPERATION_PROPOSAL",
        pending_interaction=pending,
    )
    assert view.pending_interaction is pending

    for kwargs in (
        {"pending_interaction": pending, "async_operation_ref": external},
        {"pending_interaction": pending, "interaction_ref": external},
    ):
        with pytest.raises(ValueError):
            WorkflowCheckpointView(
                task_id="task-1",
                phase="AWAIT_OPERATION_PROPOSAL",
                **kwargs,
            )


def test_cancelled_is_a_stable_workflow_phase_projection() -> None:
    """Human REJECT 后需要 framework-neutral terminal CANCELLED phase。"""

    assert WorkflowPhase.CANCELLED.value == "CANCELLED"
    assert WorkflowCheckpointView(
        task_id="task-1",
        phase="CANCELLED",
    ).phase is WorkflowPhase.CANCELLED


def test_public_workflow_contracts_do_not_expose_langgraph_types() -> None:
    """公共 workflow contract / port 源码不得出现 framework-specific public type。"""

    source = inspect.getsource(workflow_contracts) + inspect.getsource(workflow_port)

    assert "langgraph." not in source
    assert "StateGraph" not in source
    assert "PostgresSaver" not in source


def test_workflow_orchestrator_port_exposes_only_framework_neutral_methods() -> None:
    """Port 必须冻结 start/resume/get_checkpoint 三个稳定入口。"""

    methods = {
        name
        for name, value in vars(workflow_port.WorkflowOrchestratorPort).items()
        if callable(value) and not name.startswith("_")
    }

    assert methods == {"start", "resume", "get_checkpoint"}
