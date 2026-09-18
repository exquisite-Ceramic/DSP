"""Workflow Orchestrator 的 framework-neutral 公共端口。

端口只交换 ADR-010 冻结的稳定 workflow contract。具体 runtime 的配置、checkpoint
representation 与异常类型都必须由 adapter 自己消化，不能泄漏到调用方。
"""

from __future__ import annotations

from typing import Protocol

from design_orchestrator.workflow_contracts import (
    WorkflowCheckpointView,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)


class WorkflowOrchestratorPort(Protocol):
    """Workflow Orchestrator logical owner 对外提供的稳定操作边界。"""

    def start(self, request: WorkflowStartRequest) -> WorkflowCheckpointView:
        """启动一个新 workflow，并返回当前 checkpoint view。"""

        ...

    def resume(
        self,
        task_id: str,
        command: WorkflowResumeCommand | None = None,
    ) -> WorkflowCheckpointView:
        """恢复已有 workflow；没有 command 时表示重新检查 authoritative owner 状态。"""

        ...

    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None:
        """读取稳定、framework-neutral 的当前 checkpoint view。"""

        ...


__all__ = ["WorkflowOrchestratorPort"]
