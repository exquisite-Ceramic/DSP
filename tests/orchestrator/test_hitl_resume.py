"""Task 7：HITL resume mode 与 legacy synthetic pause identity 的 RED 契约测试。

本文件先冻结纯函数边界，不接触 LangGraph snapshot 或 artifact rehydrate。这样可以把
human/async/poll 的授权分类与后续 migration 机制分离，避免 runtime 通过 interrupt 形状猜测
用户意图。
"""

from __future__ import annotations

import hashlib
import json

import pytest
from design_orchestrator.hitl_resume import (
    synthetic_legacy_operation_proposal_pause,
    validate_resume_mode,
)
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
    WorkflowResumeCommand,
)
from design_orchestrator.workflow_services import WorkflowStateError


def _operation_ref() -> StableRef:
    """返回 legacy Operation Proposal 使用的稳定 operation ref。"""

    return StableRef("operation-legacy", "a" * 64)


def _human_checkpoint() -> WorkflowCheckpointView:
    """构造一个严格 v2 human wait 公共 checkpoint。"""

    operation_ref = _operation_ref()
    return WorkflowCheckpointView(
        task_id="task-hitl-1",
        phase=WorkflowPhase.AWAIT_OPERATION_PROPOSAL,
        context_snapshot_ref=StableRef("snapshot-1", "b" * 64),
        operation_ref=operation_ref,
        pending_interaction=PendingInteractionView(
            pause_id="pause-current",
            kind=PendingInteractionKind.OPERATION_PROPOSAL,
            subject_ref=operation_ref,
            allowed_resume_kinds=(
                "OPERATION_PROPOSAL_ACCEPTED",
                "OPERATION_PROPOSAL_REJECTED",
            ),
        ),
    )


def _async_checkpoint() -> WorkflowCheckpointView:
    """构造现有 external-owner async wait；它必须继续兼容旧的 pause_id=None command。"""

    return WorkflowCheckpointView(
        task_id="task-async-1",
        phase=WorkflowPhase.ENSURE_OPERATION_FRESHNESS,
        operation_ref=_operation_ref(),
        async_operation_ref=AsyncOperationRef(
            kind=AsyncOperationKind.RECONSTRUCTION_JOB,
            owner="semantic-runtime",
            operation_id="reconstruction-1",
        ),
    )


def _command(
    *,
    kind: str = "OPERATION_PROPOSAL_ACCEPTED",
    pause_id: str | None = "pause-current",
    payload: dict[str, object] | None = None,
) -> WorkflowResumeCommand:
    """构造测试命令；默认形状代表合法 human ACCEPT。"""

    return WorkflowResumeCommand(
        resume_kind=kind,
        pause_id=pause_id,
        payload={} if payload is None else payload,
    )


def _assert_error_code(
    expected_code: str,
    *,
    checkpoint: WorkflowCheckpointView,
    command: WorkflowResumeCommand | None,
) -> None:
    """断言 resume classification 以稳定 WorkflowStateError code fail closed。"""

    with pytest.raises(WorkflowStateError) as exc:
        validate_resume_mode(checkpoint=checkpoint, command=command)

    assert exc.value.code == expected_code


def test_human_wait_requires_explicit_command() -> None:
    """Human wait 不允许 command=None 被解释成 poll。"""

    _assert_error_code(
        "WORKFLOW_RESUME_INVALID",
        checkpoint=_human_checkpoint(),
        command=None,
    )


def test_human_wait_requires_pause_id() -> None:
    """Human command 缺少 pause identity 时不能消费 durable pause。"""

    _assert_error_code(
        "WORKFLOW_RESUME_INVALID",
        checkpoint=_human_checkpoint(),
        command=_command(pause_id=None),
    )


def test_human_wait_rejects_stale_pause_id() -> None:
    """旧 pause/superseded pause 的重放必须稳定分类为 STALE。"""

    _assert_error_code(
        "WORKFLOW_RESUME_STALE",
        checkpoint=_human_checkpoint(),
        command=_command(pause_id="pause-old"),
    )


def test_human_wait_rejects_resume_kind_outside_pending_contract() -> None:
    """pause identity 正确但 resume kind 不匹配时必须与 stale 区分。"""

    _assert_error_code(
        "WORKFLOW_RESUME_MISMATCH",
        checkpoint=_human_checkpoint(),
        command=_command(kind="ASYNC_OPERATION_COMPLETED"),
    )


def test_human_wait_rejects_nonempty_payload() -> None:
    """Operation Proposal v1 的 ACCEPT/REJECT 不允许夹带未冻结业务 payload。"""

    _assert_error_code(
        "WORKFLOW_RESUME_INVALID",
        checkpoint=_human_checkpoint(),
        command=_command(payload={"accepted": True}),
    )


def test_valid_human_command_is_classified_as_human() -> None:
    """只有 exact pause + allowed kind + empty payload 才进入 human resume mode。"""

    assert (
        validate_resume_mode(
            checkpoint=_human_checkpoint(),
            command=_command(),
        )
        == "human"
    )


def test_async_wait_accepts_legacy_command_without_pause_id() -> None:
    """既有 async owner wake command 继续属于 async mode，不被 human correlation 破坏。"""

    assert (
        validate_resume_mode(
            checkpoint=_async_checkpoint(),
            command=_command(
                kind="ASYNC_OPERATION_COMPLETED",
                pause_id=None,
                payload={"operation_id": "reconstruction-1"},
            ),
        )
        == "async"
    )


def test_async_wait_without_command_is_poll() -> None:
    """command=None 在 external-owner wait 上仍表示重新查询 owner 的 poll/recheck。"""

    assert validate_resume_mode(checkpoint=_async_checkpoint(), command=None) == "poll"


def test_non_human_checkpoint_rejects_pause_id_as_stale() -> None:
    """Human pause 已消费后重放旧 pause_id，不得被 async/terminal 路径重新解释。"""

    checkpoint = WorkflowCheckpointView(
        task_id="task-consumed",
        phase=WorkflowPhase.PARAMETER_BINDING,
        operation_ref=_operation_ref(),
    )

    _assert_error_code(
        "WORKFLOW_RESUME_STALE",
        checkpoint=checkpoint,
        command=_command(pause_id="pause-current"),
    )


def test_synthetic_legacy_pause_identity_is_deterministic_and_content_bound() -> None:
    """Legacy pause ID 必须来自冻结的 compact JSON，而不是进程随机 UUID。"""

    operation_ref = _operation_ref()
    expected_body = {
        "contract": "dsp.workflow.legacy-operation-proposal-pause.v1",
        "operation_ref": {
            "content_hash": operation_ref.content_hash,
            "ref_id": operation_ref.ref_id,
        },
        "task_id": "task-hitl-1",
    }
    encoded = json.dumps(
        expected_body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    expected_pause_id = "legacy-op-proposal:" + hashlib.sha256(encoded).hexdigest()

    first = synthetic_legacy_operation_proposal_pause(
        task_id="  task-hitl-1  ",
        operation_ref=operation_ref,
    )
    second = synthetic_legacy_operation_proposal_pause(
        task_id="task-hitl-1",
        operation_ref=operation_ref,
    )

    assert first == second
    assert first.pause_id == expected_pause_id
    assert first.kind is PendingInteractionKind.OPERATION_PROPOSAL
    assert first.subject_ref == operation_ref
    assert first.allowed_resume_kinds == (
        "OPERATION_PROPOSAL_ACCEPTED",
        "OPERATION_PROPOSAL_REJECTED",
    )


def test_synthetic_legacy_pause_includes_explicit_null_content_hash() -> None:
    """旧 ref 没有 hash 时仍必须把 null 纳入 identity body，避免隐式字段省略产生歧义。"""

    operation_ref = StableRef("operation-no-hash", None)
    expected_body = {
        "contract": "dsp.workflow.legacy-operation-proposal-pause.v1",
        "operation_ref": {
            "content_hash": None,
            "ref_id": "operation-no-hash",
        },
        "task_id": "task-hitl-null",
    }
    encoded = json.dumps(
        expected_body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    pending = synthetic_legacy_operation_proposal_pause(
        task_id="task-hitl-null",
        operation_ref=operation_ref,
    )

    assert pending.pause_id == (
        "legacy-op-proposal:" + hashlib.sha256(encoded).hexdigest()
    )
