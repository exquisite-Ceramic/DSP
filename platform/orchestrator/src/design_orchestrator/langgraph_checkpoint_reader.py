"""只读 LangGraph workflow checkpoint adapter。

该模块只依赖 checkpointer，不构造 ``WorkflowServices``，也不编译可执行 graph。它复用
``langgraph_runtime`` 已冻结的 root checkpoint 坐标与公共 checkpoint 投影逻辑，把
LangGraph persistence 私有形状限制在 Orchestrator runtime adapter 内部。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.serde.types import INTERRUPT, RESUME

from design_orchestrator.langgraph_runtime import (
    _checkpoint_from_snapshot,
    _checkpoint_lookup_config,
)
from design_orchestrator.workflow_contracts import WorkflowCheckpointView
from design_orchestrator.workflow_services import WorkflowStateError


@dataclass(frozen=True, slots=True)
class _CheckpointReadSnapshot:
    """仅提供既有 checkpoint projector 所需的最小 snapshot 读取面。"""

    values: object
    interrupts: tuple[object, ...]


def _pending_interrupts(checkpoint_tuple: Any) -> tuple[object, ...]:
    """从 checkpointer pending writes 恢复仍未被 resume 的 root interrupts。

    LangGraph 把 interrupt 与 resume 作为 checkpointer 私有 pending write 保存。这里仅在
    Orchestrator adapter 内解释这两个 runtime 标记；Product Runtime 不接触这些细节。
    """

    pending_writes = getattr(checkpoint_tuple, "pending_writes", None)
    if pending_writes is None:
        return ()
    if not isinstance(pending_writes, (list, tuple)):
        raise ValueError("checkpoint pending_writes must be a sequence")

    interrupts_by_task: dict[str, tuple[object, ...]] = {}
    resumed_tasks: set[str] = set()
    for write in pending_writes:
        if not isinstance(write, (list, tuple)) or len(write) != 3:
            raise ValueError("checkpoint pending write must contain task, channel and value")
        task_id, channel, value = write
        if not isinstance(task_id, str):
            raise ValueError("checkpoint pending write task id must be a string")

        if channel == INTERRUPT:
            # LangGraph 1.2.x 按 task 写入一个 interrupt 序列；兼容单值只用于防御性读取。
            if isinstance(value, (list, tuple)):
                interrupts_by_task[task_id] = tuple(value)
            else:
                interrupts_by_task[task_id] = (value,)
        elif channel == RESUME:
            resumed_tasks.add(task_id)

    return tuple(
        interrupt
        for task_id, task_interrupts in interrupts_by_task.items()
        if task_id not in resumed_tasks
        for interrupt in task_interrupts
    )


def _snapshot_from_checkpoint_tuple(checkpoint_tuple: Any) -> _CheckpointReadSnapshot:
    """把 checkpointer tuple 缩减为现有 projector 已理解的 values/interrupts。"""

    checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
    if not isinstance(checkpoint, dict):
        raise ValueError("checkpoint tuple does not contain a checkpoint mapping")
    return _CheckpointReadSnapshot(
        values=checkpoint.get("channel_values"),
        interrupts=_pending_interrupts(checkpoint_tuple),
    )


class LangGraphWorkflowCheckpointReader:
    """只读 persisted workflow checkpoint，不构造 services 或可执行 graph。"""

    def __init__(self, *, checkpointer) -> None:
        """绑定已有 checkpointer；读取 adapter 自身不拥有其生命周期。"""

        if checkpointer is None:
            raise ValueError("checkpointer must not be None")
        self._checkpointer = checkpointer

    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None:
        """按 exact task id 读取 root checkpoint，并复用既有稳定错误归一。"""

        lookup_config = _checkpoint_lookup_config(task_id)
        try:
            checkpoint_tuple = self._checkpointer.get_tuple(lookup_config)
            if checkpoint_tuple is None:
                return None
            snapshot = _snapshot_from_checkpoint_tuple(checkpoint_tuple)
            return _checkpoint_from_snapshot(snapshot, task_id=task_id)
        except WorkflowStateError:
            raise
        except Exception as exc:
            raise WorkflowStateError(
                "WORKFLOW_CHECKPOINT_INVALID",
                f"{task_id.strip()}: checkpoint backend read failed",
            ) from exc


__all__ = ["LangGraphWorkflowCheckpointReader"]
