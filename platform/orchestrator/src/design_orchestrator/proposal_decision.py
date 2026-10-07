"""Operation Proposal human decision 与 continuation 的 durable owner contract。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .workflow_contracts import StableRef


class HumanDecisionState(str, Enum):
    """人工决定历史；stale 不是一种 human decision。"""

    AWAITING = "AWAITING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ProposalContinuationState(str, Enum):
    """旧 proposal 是否仍可授权后续 workflow progression。"""

    CONTINUABLE = "CONTINUABLE"
    STALE_GATE_A = "STALE_GATE_A"
    STALE_GATE_B = "STALE_GATE_B"


def _required_text(value: object, field_name: str) -> str:
    """把 owner identity 规范化为非空文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ProposalDecisionRecord:
    """同一 task/pause/subject 的唯一 durable human/continuation truth。"""

    task_id: str
    pause_id: str
    subject_ref: StableRef
    human_decision: HumanDecisionState
    continuation: ProposalContinuationState
    revision: int
    reason: str | None = None

    def __post_init__(self) -> None:
        """校验状态组合，禁止把 stale 伪装成人工拒绝。"""

        task_id = _required_text(self.task_id, "task_id")
        pause_id = _required_text(self.pause_id, "pause_id")
        if not isinstance(self.subject_ref, StableRef):
            raise ValueError("subject_ref must be a StableRef")
        if self.subject_ref.content_hash is None:
            raise ValueError("subject_ref must include content_hash")
        decision = HumanDecisionState(self.human_decision)
        continuation = ProposalContinuationState(self.continuation)
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise ValueError("revision must be an integer")
        if self.revision <= 0:
            raise ValueError("revision must be positive")

        reason = None if self.reason is None else _required_text(self.reason, "reason")
        if continuation is ProposalContinuationState.STALE_GATE_A:
            if decision is not HumanDecisionState.AWAITING or reason is None:
                raise ValueError("STALE_GATE_A requires AWAITING decision and reason")
        elif continuation is ProposalContinuationState.STALE_GATE_B:
            if decision is not HumanDecisionState.ACCEPTED or reason is None:
                raise ValueError("STALE_GATE_B requires ACCEPTED decision and reason")
        else:
            if reason is not None:
                raise ValueError("CONTINUABLE record must not carry stale reason")
            if decision is HumanDecisionState.AWAITING:
                raise ValueError("durable AWAITING record must be stale or omitted")

        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "pause_id", pause_id)
        object.__setattr__(self, "human_decision", decision)
        object.__setattr__(self, "continuation", continuation)
        object.__setattr__(self, "reason", reason)


class ProposalDecisionStore(Protocol):
    """Proposal decision owner 的最小 create-once/CAS 端口。"""

    def claim_accept(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
    ) -> ProposalDecisionRecord: ...

    def claim_reject(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
    ) -> ProposalDecisionRecord: ...

    def invalidate_gate_a(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
        reason: str,
    ) -> ProposalDecisionRecord: ...

    def invalidate_gate_b(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
        reason: str,
    ) -> ProposalDecisionRecord: ...

    def get(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
    ) -> ProposalDecisionRecord | None: ...

    def get_for_task(self, task_id: str) -> ProposalDecisionRecord | None:
        """读取本阶段单 proposal/task 的 durable history；多行必须 fail closed。"""

        ...


__all__ = [
    "HumanDecisionState",
    "ProposalContinuationState",
    "ProposalDecisionRecord",
    "ProposalDecisionStore",
]
