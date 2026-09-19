"""ADR-010 的 LangGraph WorkflowOrchestratorPort runtime adapter。

LangGraph 的 RunnableConfig、StateSnapshot 与 Command 都被封装在本模块内部。调用方只看见
framework-neutral 的 start/resume/get_checkpoint 契约与 WorkflowStateError 稳定错误码。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from langgraph.types import Command

from design_orchestrator.hitl_resume import synthetic_legacy_operation_proposal_pause
from design_orchestrator.langgraph_graph import build_workflow_graph
from design_orchestrator.langgraph_state import (
    CHECKPOINT_CONTRACT_VERSION,
    _encode_stable_ref,
    graph_state_to_checkpoint_view,
)
from design_orchestrator.workflow_contracts import (
    WorkflowCheckpointView,
    WorkflowPhase,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)
from design_orchestrator.workflow_port import WorkflowOrchestratorPort
from design_orchestrator.workflow_services import WorkflowServices, WorkflowStateError

_CHECKPOINT_NAMESPACE = "dsp.workflow.v0_6"


def _runtime_config(task_id: str) -> dict[str, dict[str, str]]:
    """构造调用 graph 时使用的 LangGraph runtime-private 配置。"""

    if not isinstance(task_id, str) or not task_id.strip():
        raise WorkflowStateError("WORKFLOW_RESUME_INVALID", "task_id must not be blank")
    normalized = task_id.strip()
    return {
        "configurable": {
            "thread_id": normalized,
            "checkpoint_ns": _CHECKPOINT_NAMESPACE,
        }
    }


def _checkpoint_lookup_config(task_id: str) -> dict[str, dict[str, str]]:
    """构造 root graph checkpoint 的读取配置。

    LangGraph 会把顶层 graph 的非空 ``checkpoint_ns`` 归一化为空字符串，并把非空 namespace
    保留给 subgraph 路径。因此 ADR-010 的应用级 namespace 仍只存在于 invoke config 中，而
    root checkpoint 的稳定读取坐标是 ``thread_id + checkpoint_ns=''``。
    """

    runtime_config = _runtime_config(task_id)
    return {
        "configurable": {
            "thread_id": runtime_config["configurable"]["thread_id"],
            "checkpoint_ns": "",
        }
    }


def _resume_payload(command: WorkflowResumeCommand) -> dict[str, object]:
    """把公共 HITL command 转为 runtime-private、JSON-compatible resume payload。

    这里只做字段透传；pause 是否当前、resume kind 是否匹配以及 legacy/poll 模式选择仍由后续
    Task 7 的 runtime validation 统一负责。Graph 自身同时保留 defense-in-depth 精确校验。
    """

    if not isinstance(command, WorkflowResumeCommand):
        raise WorkflowStateError(
            "WORKFLOW_RESUME_INVALID",
            "command must be a WorkflowResumeCommand",
        )
    return {
        "pause_id": command.pause_id,
        "resume_kind": command.resume_kind,
        "payload": dict(command.payload),
    }


def _project_checkpoint_snapshot(snapshot: Any) -> WorkflowCheckpointView:
    """把 persisted values 与真实 interrupt 共同投影为公共 checkpoint。

    ``graph_state_to_checkpoint_view()`` 继续只解释 state 本身，绝不根据 phase 猜测 pause。
    runtime 只有在看到精确历史 Operation Proposal interrupt payload 时，才为未版本化旧状态
    合成 deterministic human pause identity；其他 legacy interrupt 形状由后续 fail-closed RED
    单独冻结，避免本步骤一次引入尚未验证的行为。
    """

    values = getattr(snapshot, "values", None)
    if not isinstance(values, Mapping) or not values:
        raise WorkflowStateError(
            "WORKFLOW_CHECKPOINT_INVALID",
            "checkpoint values must be a non-empty mapping",
        )

    checkpoint = graph_state_to_checkpoint_view(values)
    if values.get("checkpoint_contract_version") is not None:
        return checkpoint

    interrupts = tuple(getattr(snapshot, "interrupts", ()) or ())
    if len(interrupts) != 1 or checkpoint.operation_ref is None:
        return checkpoint

    interrupt_value = getattr(interrupts[0], "value", None)
    expected = {
        "kind": "OPERATION_PROPOSAL",
        "operation_ref": _encode_stable_ref(checkpoint.operation_ref),
    }
    if interrupt_value != expected:
        return checkpoint

    pending = synthetic_legacy_operation_proposal_pause(
        task_id=checkpoint.task_id,
        operation_ref=checkpoint.operation_ref,
    )
    return replace(checkpoint, pending_interaction=pending)


class LangGraphWorkflowRuntime(WorkflowOrchestratorPort):
    """把 ADR-010 deterministic graph 封装在 framework-neutral orchestrator port 后面。"""

    def __init__(self, *, services: WorkflowServices, checkpointer) -> None:
        if services is None:
            raise ValueError("services must not be None")
        if checkpointer is None:
            raise ValueError("checkpointer must not be None")
        self._services = services
        self._checkpointer = checkpointer
        self._graph = build_workflow_graph(services).compile(checkpointer=checkpointer)

    def start(self, request: WorkflowStartRequest) -> WorkflowCheckpointView:
        """启动新 workflow，并返回第一次暂停/完成后的 framework-neutral checkpoint。"""

        if not isinstance(request, WorkflowStartRequest):
            raise WorkflowStateError(
                "WORKFLOW_RESUME_INVALID",
                "request must be a WorkflowStartRequest",
            )
        config = _runtime_config(request.task_id)
        initial_state: dict[str, object] = {
            # 新 workflow 从第一次 graph invocation 起就是 v2；版本号必须随所有后续
            # checkpoint update 自然继承，不能等到 human resume 时再补写。
            "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
            "task_id": request.task_id,
            "phase": WorkflowPhase.RESOLVE_HOST_CONTEXT.value,
            "request_data": dict(request.request_data),
            "initial_host_ref": _encode_stable_ref(request.initial_host_ref),
            "context_snapshot_ref": _encode_stable_ref(request.initial_context_ref),
        }
        try:
            self._graph.invoke(initial_state, config)
        except WorkflowStateError:
            raise
        except Exception as exc:
            raise WorkflowStateError(
                "WORKFLOW_SERVICE_FAILURE",
                "workflow service invocation failed",
            ) from exc

        checkpoint = self.get_checkpoint(request.task_id)
        if checkpoint is None:
            raise WorkflowStateError(
                "WORKFLOW_CHECKPOINT_INVALID",
                "start completed without a persisted checkpoint",
            )
        return checkpoint

    def resume(
        self,
        task_id: str,
        command: WorkflowResumeCommand | None = None,
    ) -> WorkflowCheckpointView:
        """恢复既有 workflow；显式 HITL 才构造 ``Command(resume=...)``。

        ``command is None`` 表示 poll/recheck：runtime 只从现有 checkpoint 重新调用 graph，
        不伪造用户输入。后续恢复决策仍由 graph/service 对 authoritative owner 的重新查询决定。
        """

        invoke_config = _runtime_config(task_id)
        snapshot = self._load_snapshot(task_id)
        if snapshot is None:
            raise WorkflowStateError("WORKFLOW_NOT_FOUND", task_id.strip())

        graph_input: object
        if command is None:
            graph_input = None
        else:
            interrupts = getattr(snapshot, "interrupts", ())
            if not interrupts:
                raise WorkflowStateError(
                    "WORKFLOW_RESUME_INVALID",
                    "workflow has no pending interrupt",
                )
            graph_input = Command(resume=_resume_payload(command))

        try:
            self._graph.invoke(graph_input, invoke_config)
        except WorkflowStateError:
            raise
        except Exception as exc:
            raise WorkflowStateError(
                "WORKFLOW_SERVICE_FAILURE",
                "workflow service invocation failed",
            ) from exc

        checkpoint = self.get_checkpoint(task_id)
        if checkpoint is None:
            raise WorkflowStateError(
                "WORKFLOW_CHECKPOINT_INVALID",
                "resume completed without a persisted checkpoint",
            )
        return checkpoint

    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None:
        """读取当前 checkpoint，并把所有 LangGraph 私有类型投影出公共边界。"""

        snapshot = self._load_snapshot(task_id)
        if snapshot is None:
            return None

        try:
            checkpoint = _project_checkpoint_snapshot(snapshot)
        except WorkflowStateError:
            raise
        except Exception as exc:
            raise WorkflowStateError(
                "WORKFLOW_CHECKPOINT_INVALID",
                "persisted workflow checkpoint is invalid",
            ) from exc
        if checkpoint.task_id != task_id.strip():
            raise WorkflowStateError(
                "WORKFLOW_CHECKPOINT_INVALID",
                "checkpoint task_id does not match requested task",
            )
        return checkpoint

    def _load_snapshot(self, task_id: str) -> Any | None:
        """读取 root checkpoint，并把 backend/serialization 细节封装成稳定错误码。"""

        lookup_config = _checkpoint_lookup_config(task_id)
        try:
            checkpoint_tuple = self._checkpointer.get_tuple(lookup_config)
            if checkpoint_tuple is None:
                return None
            return self._graph.get_state(lookup_config)
        except WorkflowStateError:
            raise
        except Exception as exc:
            raise WorkflowStateError(
                "WORKFLOW_CHECKPOINT_INVALID",
                f"{task_id.strip()}: checkpoint backend read failed",
            ) from exc


__all__ = ["LangGraphWorkflowRuntime"]
