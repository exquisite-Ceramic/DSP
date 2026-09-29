"""把 durable correlation、窄模型 proposal、fresh Revit evidence 与 atomic freeze 组合起来。"""

from __future__ import annotations

import math
from collections.abc import Callable

from design_changeset import canonical_hash
from design_product_runtime import ProductTaskRequest

from .agent import (
    AgentClarificationRequired,
    AgentInterpreterPort,
    AgentProposal,
    NormalizedFreezeProposal,
)
from .contracts import (
    ConfiguredRevitCandidateSource,
    SessionBinding,
    session_binding_hash_body,
)
from .sqlite_state import FrozenSubmission, SqliteFrontDoorStateStore

_HOST_KIND = "REVIT"
_REQUESTED_ACTION = "SET_SELECTED_WALL_THICKNESS"
_CANDIDATE_NOT_FOUND = "FRONT_DOOR_CANDIDATE_NOT_FOUND"
_PROPOSAL_INVALID = "FRONT_DOOR_AGENT_PROPOSAL_INVALID"
_CONTEXT_INVALID = "FRONT_DOOR_CONTEXT_INVALID"
_SELECTION_INVALID = "FRONT_DOOR_SELECTION_INVALID"


class SubmissionController:
    """确定性 client controller；模型只能提议，最终 identity 与 freeze 由本类控制。"""

    def __init__(
        self,
        *,
        state_store: SqliteFrontDoorStateStore,
        agent_interpreter: AgentInterpreterPort,
        candidate_source: ConfiguredRevitCandidateSource,
        context_probe_factory: Callable[[str], object],
        session_ref_factory: Callable[[], str],
        task_id_factory: Callable[[], str],
    ) -> None:
        """注入全部外部 authority/factory；不在 controller 内隐藏全局单例。"""

        if state_store is None:
            raise TypeError("state_store is required")
        if not callable(getattr(agent_interpreter, "interpret", None)):
            raise TypeError("agent_interpreter must provide interpret")
        if not callable(getattr(candidate_source, "get", None)):
            raise TypeError("candidate_source must provide get")
        if not callable(context_probe_factory):
            raise TypeError("context_probe_factory must be callable")
        if not callable(session_ref_factory):
            raise TypeError("session_ref_factory must be callable")
        if not callable(task_id_factory):
            raise TypeError("task_id_factory must be callable")

        self._state_store = state_store
        self._agent_interpreter = agent_interpreter
        self._candidate_source = candidate_source
        self._context_probe_factory = context_probe_factory
        self._session_ref_factory = session_ref_factory
        self._task_id_factory = task_id_factory

    def prepare_submission(
        self,
        *,
        client_submission_ref: str,
        utterance: str,
    ) -> FrozenSubmission | AgentClarificationRequired:
        """create/load correlation；若已冻结先返回 winner，否则解释、验证并竞争一次 atomic freeze。"""

        record = self._state_store.create_submission(client_submission_ref, utterance)
        if record.frozen is not None:
            # 可靠重送的关键不变量：一旦 freeze 成功，任何 callback 都先返回 durable winner，
            # 禁止再次调用模型、Host probe 或 ID factory。
            return record.frozen

        interpretation = self._agent_interpreter.interpret(
            client_submission_ref=record.client_submission_ref,
            utterance=record.utterance,
        )
        if isinstance(interpretation, AgentClarificationRequired):
            if not isinstance(interpretation.question, str) or not interpretation.question.strip():
                raise ValueError(f"{_PROPOSAL_INVALID}: clarification question must be non-blank")
            return interpretation
        if not isinstance(interpretation, AgentProposal):
            raise TypeError(
                f"{_PROPOSAL_INVALID}: interpreter must return AgentProposal or AgentClarificationRequired"
            )

        candidate = self._candidate_source.get(interpretation.candidate_key)
        if candidate is None:
            raise ValueError(
                f"{_CANDIDATE_NOT_FOUND}: configured candidate does not exist"
            )

        intent_arguments = self._normalize_thickness_intent(interpretation)
        probe = self._context_probe_factory(candidate.transport_locator)
        discover = getattr(probe, "discover", None)
        if not callable(discover):
            raise TypeError("context_probe_factory must return an object with discover")
        observation = discover(
            command_id=f"front-door-probe:{record.client_submission_ref}",
            document_id=candidate.document_id,
        )
        self._validate_observation(candidate=candidate, observation=observation)

        # task/session identity 只在 proposal + configured candidate + fresh Host evidence 全部通过后分配。
        session_ref = self._new_identity(self._session_ref_factory, "session_ref")
        task_id = self._new_identity(self._task_id_factory, "task_id")
        binding = self._build_binding(
            session_ref=session_ref,
            candidate=candidate,
            observation=observation,
        )
        request = ProductTaskRequest.create(
            task_id=task_id,
            project_id=candidate.project_id,
            host_kind=_HOST_KIND,
            session_ref=binding.session_ref,
            requested_action=_REQUESTED_ACTION,
            intent_arguments=intent_arguments,
        )
        proposal = NormalizedFreezeProposal(
            project_id=candidate.project_id,
            host_kind=_HOST_KIND,
            requested_action=_REQUESTED_ACTION,
            intent_arguments=intent_arguments,
            candidate_key=candidate.candidate_key,
            candidate_hash=candidate.candidate_hash,
        )
        return self._state_store.freeze_submission(
            client_submission_ref=record.client_submission_ref,
            proposal=proposal,
            binding=binding,
            request=request,
        )

    @staticmethod
    def _normalize_thickness_intent(proposal: AgentProposal) -> dict[str, object]:
        """只接受当前 vertical 的正有限毫米厚度，不让模型输出扩张请求面。"""

        value = proposal.thickness_value
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
        ):
            raise ValueError(
                f"{_PROPOSAL_INVALID}: thickness_value must be a finite positive number"
            )
        if proposal.thickness_unit != "mm":
            raise ValueError(f"{_PROPOSAL_INVALID}: thickness_unit must be mm")
        return {
            "thickness": {
                "value": float(value),
                "unit": "mm",
            }
        }

    @staticmethod
    def _validate_observation(*, candidate, observation) -> None:
        """再次收窄 fresh Host evidence：exact document/runtime 且只选中 configured Wall。"""

        if observation is None:
            raise ValueError(f"{_CONTEXT_INVALID}: context probe returned no observation")
        if getattr(observation, "document_id", None) != candidate.document_id:
            raise ValueError(
                f"{_CONTEXT_INVALID}: fresh document identity does not match configured candidate"
            )
        host_instance_id = getattr(observation, "host_instance_id", None)
        if not isinstance(host_instance_id, str) or not host_instance_id.strip():
            raise ValueError(f"{_CONTEXT_INVALID}: fresh host_instance_id is missing")

        selected_elements = getattr(observation, "selected_elements", None)
        if not isinstance(selected_elements, tuple) or len(selected_elements) != 1:
            raise ValueError(
                f"{_SELECTION_INVALID}: exactly one configured Wall must be selected"
            )
        selected = selected_elements[0]
        if (
            getattr(selected, "unique_id", None) != candidate.native_target_unique_id
            or getattr(selected, "native_kind", None) != "Wall"
        ):
            raise ValueError(
                f"{_SELECTION_INVALID}: selected Host target does not match configured Wall"
            )

    @staticmethod
    def _build_binding(*, session_ref: str, candidate, observation) -> SessionBinding:
        """把 configured candidate 与 fresh runtime/document evidence 冻结成 immutable SessionBinding。"""

        body = session_binding_hash_body(
            session_ref=session_ref,
            project_id=candidate.project_id,
            host_kind=_HOST_KIND,
            candidate_key=candidate.candidate_key,
            candidate_hash=candidate.candidate_hash,
            transport_locator=candidate.transport_locator,
            host_instance_id=observation.host_instance_id,
            document_id=candidate.document_id,
        )
        return SessionBinding(
            session_ref=session_ref,
            project_id=candidate.project_id,
            host_kind=_HOST_KIND,
            candidate_key=candidate.candidate_key,
            candidate_hash=candidate.candidate_hash,
            transport_locator=candidate.transport_locator,
            host_instance_id=observation.host_instance_id,
            document_id=candidate.document_id,
            document_title=observation.document_title,
            binding_hash=canonical_hash(body),
        )

    @staticmethod
    def _new_identity(factory: Callable[[], str], field_name: str) -> str:
        """要求 controller factory 返回非空 opaque identity；值本身不参与 callback 等价。"""

        value = factory()
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} factory must return a non-blank string")
        return value.strip()


__all__ = ["SubmissionController"]
