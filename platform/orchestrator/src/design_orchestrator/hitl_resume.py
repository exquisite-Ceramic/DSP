"""Task 7 的 framework-neutral HITL resume 分类与 legacy pause identity。

本模块只负责两类纯确定性规则：

1. 根据公共 checkpoint 与公共 resume command 判定 ``human`` / ``async`` / ``poll``；
2. 为旧版未持久化 pause_id 的 Operation Proposal interrupt 派生稳定 synthetic identity。

它不读取 LangGraph ``StateSnapshot``、不访问 artifact store，也不执行 legacy checkpoint migration。
这些副作用边界由 runtime 与 WorkflowServices 后续步骤负责。
"""

from __future__ import annotations

import hashlib
import json

from design_orchestrator.workflow_contracts import (
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowCheckpointView,
    WorkflowResumeCommand,
)
from design_orchestrator.workflow_services import WorkflowStateError

_LEGACY_OPERATION_PROPOSAL_CONTRACT = (
    "dsp.workflow.legacy-operation-proposal-pause.v1"
)
_OPERATION_PROPOSAL_RESUME_KINDS = (
    "OPERATION_PROPOSAL_ACCEPTED",
    "OPERATION_PROPOSAL_REJECTED",
)


def synthetic_legacy_operation_proposal_pause(
    *,
    task_id: str,
    operation_ref: StableRef,
) -> PendingInteractionView:
    """为精确 legacy Operation Proposal wait 派生可跨进程重建的 pause identity。

    这里故意把 ``content_hash=None`` 也显式写入 canonical body；字段省略和 JSON ``null``
    不能被视为同一个 identity 输入。任务 ID 与公共契约一致先去除首尾空白，然后使用固定的
    sorted/compact JSON 与 SHA-256，确保数据库重启、不同 Python 进程和重复读取结果完全一致。
    """

    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must not be blank")
    if not isinstance(operation_ref, StableRef):
        raise ValueError("operation_ref must be a StableRef")

    normalized_task_id = task_id.strip()
    body = {
        "contract": _LEGACY_OPERATION_PROPOSAL_CONTRACT,
        "operation_ref": {
            "content_hash": operation_ref.content_hash,
            "ref_id": operation_ref.ref_id,
        },
        "task_id": normalized_task_id,
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    pause_id = "legacy-op-proposal:" + hashlib.sha256(encoded).hexdigest()

    return PendingInteractionView(
        pause_id=pause_id,
        kind=PendingInteractionKind.OPERATION_PROPOSAL,
        subject_ref=operation_ref,
        allowed_resume_kinds=_OPERATION_PROPOSAL_RESUME_KINDS,
    )


def validate_resume_mode(
    *,
    checkpoint: WorkflowCheckpointView,
    command: WorkflowResumeCommand | None,
) -> str:
    """按 durable checkpoint 事实确定恢复模式，并在调用 graph 前 fail closed。

    Human pause 的 identity 与允许动作来自 ``PendingInteractionView``，因此 command 缺失、旧
    pause replay、动作不匹配或夹带未冻结 payload 都不能进入 LangGraph。没有 human pause 时，
    任何非空 ``pause_id`` 都视为已消费/过期 human identity 的 stale replay；已有 external-owner
    wait 则保留 ADR-010 的 ``async`` 与无命令 ``poll`` 兼容行为。
    """

    if not isinstance(checkpoint, WorkflowCheckpointView):
        raise WorkflowStateError(
            "WORKFLOW_RESUME_INVALID",
            "checkpoint must be a WorkflowCheckpointView",
        )
    if command is not None and not isinstance(command, WorkflowResumeCommand):
        raise WorkflowStateError(
            "WORKFLOW_RESUME_INVALID",
            "command must be a WorkflowResumeCommand or None",
        )

    pending = checkpoint.pending_interaction
    if pending is not None:
        if command is None:
            raise WorkflowStateError(
                "WORKFLOW_RESUME_INVALID",
                "human wait requires an explicit resume command",
            )
        if command.pause_id is None:
            raise WorkflowStateError(
                "WORKFLOW_RESUME_INVALID",
                "human resume command requires pause_id",
            )
        if command.pause_id != pending.pause_id:
            raise WorkflowStateError(
                "WORKFLOW_RESUME_STALE",
                "resume pause_id does not match the current pending interaction",
            )
        if command.resume_kind not in pending.allowed_resume_kinds:
            raise WorkflowStateError(
                "WORKFLOW_RESUME_MISMATCH",
                "resume_kind is not allowed by the current pending interaction",
            )
        if command.payload:
            raise WorkflowStateError(
                "WORKFLOW_RESUME_INVALID",
                "operation proposal human resume payload must be empty",
            )
        return "human"

    if command is not None and command.pause_id is not None:
        # 当前 checkpoint 已没有 human pause；携带 pause_id 的 command 只能是旧 pause 的重放，
        # 不能被 async 或普通 poll 路径重新解释。
        raise WorkflowStateError(
            "WORKFLOW_RESUME_STALE",
            "checkpoint has no pending human interaction for pause_id",
        )

    if checkpoint.async_operation_ref is not None:
        return "poll" if command is None else "async"

    if command is None:
        # 非 human、非 external-owner wait 的 command-less resume 仍是一次普通 recheck。
        # 是否允许 graph 从该 phase 继续，由 runtime/topology 自身状态校验决定。
        return "poll"

    raise WorkflowStateError(
        "WORKFLOW_RESUME_INVALID",
        "resume command is not valid for a checkpoint without a pending wait",
    )


__all__ = [
    "synthetic_legacy_operation_proposal_pause",
    "validate_resume_mode",
]
