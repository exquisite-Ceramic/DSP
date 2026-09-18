"""ADR-010 的 LangGraph WorkflowOrchestratorPort runtime adapter。

LangGraph 的 RunnableConfig、StateSnapshot 与 Command 都被封装在本模块内部。调用方只看见
framework-neutral 的 start/resume/get_checkpoint 契约与 WorkflowStateError 稳定错误码。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langgraph.types import Command

from design_orchestrator.langgraph_graph import build_workflow_graph
from design_orchestrator.langgraph_state import (
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
    """构造只在 adapter 内使用的 LangGraph checkpoint 隔离配置。"""

    if not isinstance(task_id, str) or not task_id.strip():
        raise WorkflowStateError("WORKFLOW_RESUME_INVALID", "task_id must not be blank")
    normalized = task_id.strip()
    return {
        "configurable": {
            "thread_id": normalized,
            "checkpoint_ns": _CHECKPOINT_NAMESPACE,
        }
    }


def _resume_payload(command: WorkflowResumeCommand) -> dict[str, object]:
    """把公共 HITL command 转为 runtime-private、JSON-compatible resume payload。"""

    if not isinstance(command, WorkflowResumeCommand):
        raise WorkflowStateError(
            "WORKFLOW_RESUME_INVALID",
            "command must be a WorkflowResumeCommand",
        )
    return {
        "resume_kind": command.resume_kind,
        "payload": dict(command.payload),
    }


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

        config = _runtime_config(task_id)
        snapshot = self._load_snapshot(task_id, config)
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
            self._graph.invoke(graph_input, config)
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

        config = _runtime_config(task_id)
        snapshot = self._load_snapshot(task_id, config)
        if snapshot is None:
            return None

        values = getattr(snapshot, "values", None)
        if not isinstance(values, Mapping) or not values:
            raise WorkflowStateError(
                "WORKFLOW_CHECKPOINT_INVALID",
                "checkpoint values must be a non-empty mapping",
            )
        try:
            checkpoint = graph_state_to_checkpoint_view(values)
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

    def _load_snapshot(
        self,
        task_id: str,
        config: dict[str, dict[str, str]],
    ) -> Any | None:
        """先用 checkpointer 判断线程是否存在，再读取 LangGraph StateSnapshot。

        这一步把“not found”和“checkpoint backend/serialization 损坏”分开，避免调用方需要
        识别 LangGraph 或具体 checkpointer 的异常类型。
        """

        try:
            checkpoint_tuple = self._checkpointer.get_tuple(config)
            if checkpoint_tuple is None:
                return None
            return self._graph.get_state(config)
        except WorkflowStateError:
            raise
        except Exception as exc:
            raise WorkflowStateError(
                "WORKFLOW_CHECKPOINT_INVALID",
                f"{task_id.strip()}: checkpoint backend read failed",
            ) from exc


__all__ = ["LangGraphWorkflowRuntime"]
