"""Task 16A：显式人工决定的 V2 exact-pause resume 测试侧安全边界。

本模块不自行调用模型、选择批准结果或创建 Host mutation。
只有调用方另行取得明确的人类决定后，才允许转交现有生产 MCP resume。
在发出可能触发 Host 执行的 resume 之前，必须重新核对 durable owner truth。
"""

from __future__ import annotations

from dataclasses import dataclass

from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import (
    PendingInteractionKind,
    WorkflowCheckpointView,
    WorkflowPhase,
)
from design_product_runtime import ProductTaskQueryViewV2

from .cross_host_product_v2_proposal_authority import (
    ReviewedV2Proposal,
    _require_v2_query,
    _validate_subject,
)

_ALLOWED_DECISIONS = frozenset(
    {"OPERATION_PROPOSAL_ACCEPTED", "OPERATION_PROPOSAL_REJECTED"}
)


def _deny(code: str, detail: str) -> None:
    """出现任何不可证明的身份或状态时停止，不得尝试替换为最近一次任务。"""

    raise ValueError(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class ExplicitHumanDecisionV2:
    """外部人工动作明确关联 request、binding、pause 和 immutable subject。"""

    task_id: str
    request_hash: str
    session_binding_hash: str
    pause_id: str
    subject_content_hash: str
    resume_kind: str

    def __post_init__(self) -> None:
        """冻结可审计的决定输入；不允许任意字符串变成批准指令。"""

        if self.resume_kind not in _ALLOWED_DECISIONS:
            _deny("LIVE_HUMAN_DECISION_INVALID", "unsupported explicit decision kind")
        for field in (
            "task_id",
            "request_hash",
            "session_binding_hash",
            "pause_id",
            "subject_content_hash",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                _deny("LIVE_HUMAN_DECISION_INVALID", f"{field} is absent")


async def resume_reviewed_v2_proposal(
    *,
    reviewed: ReviewedV2Proposal,
    human_decision: ExplicitHumanDecisionV2 | None,
    mcp_client: object,
    checkpoint_reader: object,
    artifact_reader: object,
) -> ProductTaskQueryViewV2:
    """仅在人工确实提供 exact 决定后恢复一次 MCP V2 pause。

    前置校验不会修改 Owner；一旦 MCP resume 返回不一致，不会进行自动重试。
    若调用方进程在发送后退出，必须通过同一 exact task 的 durable query 调查。
    """

    if human_decision is None:
        _deny("LIVE_HUMAN_DECISION_REQUIRED", "explicit human decision is missing")
    if not isinstance(human_decision, ExplicitHumanDecisionV2):
        _deny("LIVE_HUMAN_DECISION_INVALID", "decision must use the explicit V2 DTO")
    if not isinstance(reviewed, ReviewedV2Proposal):
        _deny("LIVE_HUMAN_DECISION_INVALID", "reviewed proposal must be immutable V2")
    request = reviewed.frozen.request
    binding = reviewed.frozen.session_binding
    if (
        human_decision.task_id != request.task_id
        or human_decision.request_hash != request.request_hash
        or human_decision.session_binding_hash != binding.binding_hash
        or human_decision.pause_id != reviewed.pause_id
        or human_decision.subject_content_hash != reviewed.subject_ref.content_hash
    ):
        _deny(
            "LIVE_HUMAN_DECISION_LINEAGE_INVALID",
            "explicit human decision does not match reviewed exact authority",
        )

    get = getattr(mcp_client, "get", None)
    resume = getattr(mcp_client, "resume_operation_proposal", None)
    get_checkpoint = getattr(checkpoint_reader, "get_checkpoint", None)
    get_artifact = getattr(artifact_reader, "get", None)
    if not all(callable(call) for call in (get, resume, get_checkpoint, get_artifact)):
        _deny("LIVE_HUMAN_DECISION_WIRING_INVALID", "production owner ports unavailable")

    current = await get(request.task_id)
    try:
        _require_v2_query(current, reviewed.frozen)
    except (TypeError, ValueError):
        _deny("LIVE_HUMAN_DECISION_STALE", "durable MCP query is no longer pending")
    if current != reviewed.view:
        _deny("LIVE_HUMAN_DECISION_STALE", "reviewed product state changed")

    checkpoint = get_checkpoint(request.task_id)
    if (
        not isinstance(checkpoint, WorkflowCheckpointView)
        or checkpoint.task_id != request.task_id
        or checkpoint.phase is not WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        or checkpoint.pending_interaction is None
        or checkpoint.pending_interaction.kind is not PendingInteractionKind.OPERATION_PROPOSAL
    ):
        _deny("LIVE_HUMAN_DECISION_STALE", "reviewed pause is no longer current")
    pending = checkpoint.pending_interaction
    if (
        pending.pause_id != reviewed.pause_id
        or pending.subject_ref != reviewed.subject_ref
        or human_decision.resume_kind not in pending.allowed_resume_kinds
    ):
        _deny("LIVE_HUMAN_DECISION_STALE", "exact pause or subject ref changed")

    current_subject = get_artifact(pending.subject_ref)
    if (
        pending.subject_ref.content_hash is None
        or workflow_artifact_content_hash(current_subject)
        != pending.subject_ref.content_hash
    ):
        _deny(
            "LIVE_V2_SUBJECT_INTEGRITY_INVALID",
            "durable proposal artifact differs from exact ref hash",
        )
    _validate_subject(
        subject=current_subject,
        frozen=reviewed.frozen,
        pending=pending,
    )
    if current_subject != reviewed.subject:
        _deny("LIVE_HUMAN_DECISION_STALE", "reviewed subject body changed")

    # 仅此处调用真正的 MCP resume；所有 check 均已通过，后续异常不进行猜测式重送。
    resumed = await resume(
        task_id=request.task_id,
        pause_id=reviewed.pause_id,
        resume_kind=human_decision.resume_kind,
    )
    reread = await get(request.task_id)
    if (
        not isinstance(resumed, ProductTaskQueryViewV2)
        or not isinstance(reread, ProductTaskQueryViewV2)
        or resumed.task_id != request.task_id
        or reread.task_id != request.task_id
        or resumed.request_hash != request.request_hash
        or reread.request_hash != request.request_hash
        or resumed != reread
    ):
        _deny(
            "LIVE_HUMAN_RESUME_LINEAGE_INVALID",
            "resume and exact-task GET disagree; manual recovery required",
        )
    return reread


__all__ = ["ExplicitHumanDecisionV2", "resume_reviewed_v2_proposal"]
