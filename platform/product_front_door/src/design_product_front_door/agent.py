"""Product Front Door 的窄模型解释契约；模型永远不拥有业务身份或执行授权。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AgentProposal:
    """模型只允许提出受支持的 configured candidate 与厚度意图。"""

    candidate_key: str
    thickness_value: float
    thickness_unit: str


@dataclass(frozen=True, slots=True)
class AgentClarificationRequired:
    """需要用户补充信息；此结果绝不产生业务任务身份。"""

    question: str


class AgentInterpreterPort(Protocol):
    """把原始自然语言解释成一个窄 proposal 或一个澄清问题。"""

    def interpret(
        self,
        *,
        client_submission_ref: str,
        utterance: str,
    ) -> AgentProposal | AgentClarificationRequired:
        """解释 durable utterance；不得自行分配 task/session/approval identity。"""

        ...


@dataclass(frozen=True, slots=True)
class NormalizedFreezeProposal:
    """只包含生成 task/session identity 之前已经确定的 callback 等价输入。"""

    project_id: str
    host_kind: str
    requested_action: str
    intent_arguments: Mapping[str, object]
    candidate_key: str
    candidate_hash: str


__all__ = [
    "AgentClarificationRequired",
    "AgentInterpreterPort",
    "AgentProposal",
    "NormalizedFreezeProposal",
]
