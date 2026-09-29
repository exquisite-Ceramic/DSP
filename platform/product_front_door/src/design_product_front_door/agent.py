"""Product Front Door 的窄模型解释契约；模型永远不拥有业务身份或执行授权。"""

from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

_AGENT_OUTPUT_INVALID = "FRONT_DOOR_AGENT_OUTPUT_INVALID"
_AGENT_PROCESS_FAILED = "FRONT_DOOR_AGENT_PROCESS_FAILED"


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


class SubprocessAgentInterpreter:
    """以真实子进程承载模型解释，并把输入/输出严格限制在冻结的窄 JSON 契约。"""

    def __init__(
        self,
        *,
        command: Sequence[str],
        timeout_seconds: float = 30.0,
    ) -> None:
        """冻结可执行命令与超时；永远使用 shell=False，避免扩大命令解释边界。"""

        if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
            raise TypeError("command must be a sequence of strings")
        normalized_command = tuple(command)
        if not normalized_command or any(
            not isinstance(part, str) or not part.strip() for part in normalized_command
        ):
            raise ValueError("command must contain only non-blank strings")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or float(timeout_seconds) <= 0.0
        ):
            raise ValueError("timeout_seconds must be a finite positive number")

        self._command = normalized_command
        self._timeout_seconds = float(timeout_seconds)

    def interpret(
        self,
        *,
        client_submission_ref: str,
        utterance: str,
    ) -> AgentProposal | AgentClarificationRequired:
        """只发送 correlation + utterance，并把 stdout 严格解码为两种允许结果之一。"""

        if not isinstance(client_submission_ref, str) or not client_submission_ref.strip():
            raise ValueError("client_submission_ref must be a non-blank string")
        if not isinstance(utterance, str):
            raise TypeError("utterance must be a string")

        stdin_payload = json.dumps(
            {
                "client_submission_ref": client_submission_ref.strip(),
                "utterance": utterance,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        try:
            completed = subprocess.run(
                self._command,
                input=stdin_payload,
                text=True,
                capture_output=True,
                check=False,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(
                f"{_AGENT_PROCESS_FAILED}: interpreter process could not complete"
            ) from exc

        if completed.returncode != 0:
            raise ValueError(
                f"{_AGENT_PROCESS_FAILED}: interpreter process exited with code {completed.returncode}"
            )

        return self._decode_output(completed.stdout)

    @staticmethod
    def _decode_output(stdout: str) -> AgentProposal | AgentClarificationRequired:
        """要求 stdout 是唯一 JSON object，并按 exact-key schema fail closed。"""

        try:
            payload = json.loads(stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"{_AGENT_OUTPUT_INVALID}: stdout must contain exactly one JSON document"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"{_AGENT_OUTPUT_INVALID}: stdout JSON must be an object")

        kind = payload.get("kind")
        if kind == "PROPOSAL":
            return SubprocessAgentInterpreter._decode_proposal(payload)
        if kind == "CLARIFICATION_REQUIRED":
            return SubprocessAgentInterpreter._decode_clarification(payload)
        raise ValueError(f"{_AGENT_OUTPUT_INVALID}: unsupported result kind")

    @staticmethod
    def _decode_proposal(payload: Mapping[str, object]) -> AgentProposal:
        """只接受 candidate_key + {value, unit} thickness，不允许任何 authority/未知字段。"""

        if set(payload) != {"kind", "candidate_key", "thickness"}:
            raise ValueError(f"{_AGENT_OUTPUT_INVALID}: PROPOSAL contains unknown fields")

        candidate_key = payload.get("candidate_key")
        if not isinstance(candidate_key, str) or not candidate_key.strip():
            raise ValueError(
                f"{_AGENT_OUTPUT_INVALID}: candidate_key must be a non-blank string"
            )

        thickness = payload.get("thickness")
        if not isinstance(thickness, Mapping) or set(thickness) != {"value", "unit"}:
            raise ValueError(
                f"{_AGENT_OUTPUT_INVALID}: thickness must contain exactly value and unit"
            )
        value = thickness.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
        ):
            raise ValueError(
                f"{_AGENT_OUTPUT_INVALID}: thickness.value must be a finite positive number"
            )
        if thickness.get("unit") != "mm":
            raise ValueError(f"{_AGENT_OUTPUT_INVALID}: thickness.unit must be mm")

        return AgentProposal(
            candidate_key=candidate_key.strip(),
            thickness_value=float(value),
            thickness_unit="mm",
        )

    @staticmethod
    def _decode_clarification(payload: Mapping[str, object]) -> AgentClarificationRequired:
        """只接受 kind + question，澄清结果不能夹带 candidate 或业务 identity。"""

        if set(payload) != {"kind", "question"}:
            raise ValueError(
                f"{_AGENT_OUTPUT_INVALID}: CLARIFICATION_REQUIRED contains unknown fields"
            )
        question = payload.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(
                f"{_AGENT_OUTPUT_INVALID}: clarification question must be non-blank"
            )
        return AgentClarificationRequired(question=question)


__all__ = [
    "AgentClarificationRequired",
    "AgentInterpreterPort",
    "AgentProposal",
    "NormalizedFreezeProposal",
    "SubprocessAgentInterpreter",
]
