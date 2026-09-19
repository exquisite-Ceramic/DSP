"""ADR-010 的 LangGraph WorkflowOrchestratorPort runtime adapter。

LangGraph 的 RunnableConfig、StateSnapshot 与 Command 都被封装在本模块内部。调用方只看见
framework-neutral 的 start/resume/get_checkpoint 契约与 WorkflowStateError 稳定错误码。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from langgraph.types import Command

from design_orchestrator.hitl_resume import (
    synthetic_legacy_operation_proposal_pause,
    validate_resume_mode,
)
from design_orchestrator.langgraph_graph import build_workflow_graph
from design_orchestrator.langgraph_state import (
    CHECKPOINT_CONTRACT_VERSION,
    _encode_async_ref,
    _encode_stable_ref,
    encode_pending_interaction,
    graph_state_to_checkpoint_view,
)
from design_orchestrator.workflow_artifacts import WorkflowArtifactUnavailableError
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
    """把公共 HITL command 转为 runtime-private、JSON-compatible resume payload。"""

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
    v2 checkpoint 始终按严格公共契约投影；未版本化旧状态只有在真实 interrupt 精确匹配
    Operation Proposal 或 external-owner async 历史形状时才兼容读取，其他 interrupt-bearing
    legacy shape 一律 fail closed。
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
    if not interrupts:
        # 未版本化 state 本身不包含 human pause identity；没有真实 interrupt 时绝不能仅凭
        # phase 猜测存在人工暂停。
        return checkpoint
    if len(interrupts) != 1:
        raise WorkflowStateError(
            "WORKFLOW_CHECKPOINT_INVALID",
            "unversioned checkpoint contains an unsupported interrupt set",
        )

    interrupt_value = getattr(interrupts[0], "value", None)
    if (
        checkpoint.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        and checkpoint.operation_ref is not None
        and checkpoint.async_operation_ref is None
    ):
        expected_human_interrupt = {
            "kind": "OPERATION_PROPOSAL",
            "operation_ref": _encode_stable_ref(checkpoint.operation_ref),
        }
        if interrupt_value == expected_human_interrupt:
            pending = synthetic_legacy_operation_proposal_pause(
                task_id=checkpoint.task_id,
                operation_ref=checkpoint.operation_ref,
            )
            return replace(checkpoint, pending_interaction=pending)

    if checkpoint.async_operation_ref is not None:
        expected_async_interrupt = {
            "kind": "ASYNC_OPERATION",
            "operation_ref": _encode_async_ref(checkpoint.async_operation_ref),
        }
        if interrupt_value == expected_async_interrupt:
            # 旧 async wait 已经通过公共 async_operation_ref 完整表达，不创建 synthetic
            # human pause，也不改变历史 poll/command 兼容语义。
            return checkpoint

    raise WorkflowStateError(
        "WORKFLOW_CHECKPOINT_INVALID",
        "unversioned checkpoint contains an unsupported interrupt shape",
    )


def _checkpoint_from_snapshot(
    snapshot: Any,
    *,
    task_id: str,
) -> WorkflowCheckpointView:
    """安全投影一个已读取 snapshot，并统一执行 task identity 校验与错误归一。"""

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


def _require_v2_human_interrupt(
    snapshot: Any,
    checkpoint: WorkflowCheckpointView,
) -> None:
    """确认 legacy migration 后已经形成真实、可恢复的 v2 human interrupt。"""

    values = getattr(snapshot, "values", None)
    if not isinstance(values, Mapping):
        raise WorkflowStateError(
            "WORKFLOW_CHECKPOINT_INVALID",
            "migrated checkpoint values must be a mapping",
        )
    if values.get("checkpoint_contract_version") != CHECKPOINT_CONTRACT_VERSION:
        raise WorkflowStateError(
            "WORKFLOW_CHECKPOINT_INVALID",
            "legacy human migration did not persist checkpoint contract version 2",
        )
    pending = checkpoint.pending_interaction
    if (
        checkpoint.phase is not WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        or pending is None
        or checkpoint.operation_ref != pending.subject_ref
    ):
        raise WorkflowStateError(
            "WORKFLOW_CHECKPOINT_INVALID",
            "legacy human migration did not persist a valid pending interaction",
        )

    interrupts = tuple(getattr(snapshot, "interrupts", ()) or ())
    expected_interrupt = {
        "pause_id": pending.pause_id,
        "kind": pending.kind.value,
        "subject_ref": _encode_stable_ref(pending.subject_ref),
    }
    if len(interrupts) != 1 or getattr(interrupts[0], "value", None) != expected_interrupt:
        raise WorkflowStateError(
            "WORKFLOW_CHECKPOINT_INVALID",
            "legacy human migration did not establish the expected v2 interrupt",
        )


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
        """按公共 checkpoint 事实选择 human/async/poll，并安全恢复既有 workflow。"""

        invoke_config = _runtime_config(task_id)
        snapshot = self._load_snapshot(task_id)
        if snapshot is None:
            raise WorkflowStateError("WORKFLOW_NOT_FOUND", task_id.strip())

        checkpoint = _checkpoint_from_snapshot(snapshot, task_id=task_id)
        resume_mode = validate_resume_mode(checkpoint=checkpoint, command=command)

        values = getattr(snapshot, "values", None)
        if not isinstance(values, Mapping):
            raise WorkflowStateError(
                "WORKFLOW_CHECKPOINT_INVALID",
                "checkpoint values must be a mapping",
            )
        checkpoint_version = values.get("checkpoint_contract_version")

        if checkpoint_version is None and resume_mode == "human":
            # 精确 legacy human pause 必须先校验 command，再恢复 artifact；任何恢复失败都发生在
            # update_state 之前，从而保证原旧 checkpoint 仍然可重试。
            pending = checkpoint.pending_interaction
            context_snapshot_ref = checkpoint.context_snapshot_ref
            if pending is None or context_snapshot_ref is None:
                raise WorkflowStateError(
                    "WORKFLOW_CHECKPOINT_INVALID",
                    "legacy human checkpoint is missing migration references",
                )
            if command is None:
                # validate_resume_mode 已保证 human 模式一定有 command；这里仅保留防御性断言。
                raise WorkflowStateError(
                    "WORKFLOW_RESUME_INVALID",
                    "human resume command is required",
                )

            try:
                resolution = self._services.ensure_operation_artifact(
                    pending.subject_ref,
                    context_snapshot_ref,
                    allow_legacy_rehydrate=True,
                )
            except WorkflowArtifactUnavailableError as exc:
                raise WorkflowStateError(
                    "WORKFLOW_ARTIFACT_UNAVAILABLE",
                    "operation artifact required for legacy migration is unavailable",
                ) from exc

            migrated_pending = replace(pending, subject_ref=resolution.ref)
            try:
                migrated_config = self._graph.update_state(
                    _checkpoint_lookup_config(task_id),
                    {
                        "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
                        "operation_ref": _encode_stable_ref(resolution.ref),
                        "pending_interaction": encode_pending_interaction(migrated_pending),
                        "async_operation_ref": None,
                        "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
                    },
                    as_node="prepare_operation_proposal_pause",
                )
                # ``as_node`` 只声明“prepare 已完成”；随后从其后继 await node 建立真实 interrupt，
                # 绝不能重新执行 prepare node，否则会生成新的随机 pause_id。
                self._graph.invoke(None, migrated_config)
            except WorkflowStateError:
                raise
            except Exception as exc:
                raise WorkflowStateError(
                    "WORKFLOW_CHECKPOINT_INVALID",
                    "legacy human checkpoint migration failed",
                ) from exc

            migrated_snapshot = self._load_snapshot(task_id)
            if migrated_snapshot is None:
                raise WorkflowStateError(
                    "WORKFLOW_CHECKPOINT_INVALID",
                    "legacy human migration completed without a persisted checkpoint",
                )
            migrated_checkpoint = _checkpoint_from_snapshot(
                migrated_snapshot,
                task_id=task_id,
            )
            _require_v2_human_interrupt(migrated_snapshot, migrated_checkpoint)

            # 同一个 command 必须再次通过迁移后 v2 pending 校验，证明 synthetic pause identity
            # 没有在 migration 中漂移；只有这一步之后才允许真正消费 Command(resume=...)。
            validate_resume_mode(checkpoint=migrated_checkpoint, command=command)
            snapshot = migrated_snapshot
            checkpoint = migrated_checkpoint

        graph_input: object
        if resume_mode == "poll":
            graph_input = None
        else:
            if command is None:
                raise WorkflowStateError(
                    "WORKFLOW_RESUME_INVALID",
                    "explicit resume mode requires a command",
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
        return _checkpoint_from_snapshot(snapshot, task_id=task_id)

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
