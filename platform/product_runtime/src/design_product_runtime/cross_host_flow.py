"""Cross-Host ProductTask V2 对既有 workflow owner 的薄启动 facade。"""

from __future__ import annotations

from design_orchestrator import (
    WorkflowCheckpointView,
    WorkflowOrchestratorPort,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)

from .accepted_input import AcceptedProductTaskInputV2
from .start_gate import ProductTaskStartGate


class CrossHostProductFlow:
    """只负责 accepted V2 task 的首次 workflow start 与后续 resume。

    完整 request/binding body 始终由 ProductTask owner 持有；checkpoint 只保存 locator/hash。
    """

    def __init__(
        self,
        *,
        workflow_runtime: WorkflowOrchestratorPort,
        start_gate: ProductTaskStartGate,
    ) -> None:
        """绑定既有 workflow runtime 与 ProductTask task-row start gate。"""

        if workflow_runtime is None:
            raise ValueError("workflow_runtime must not be None")
        if start_gate is None:
            raise ValueError("start_gate must not be None")
        self._workflow_runtime = workflow_runtime
        self._start_gate = start_gate

    def start_accepted(
        self,
        accepted: AcceptedProductTaskInputV2,
    ) -> WorkflowCheckpointView:
        """在 existing task-row gate 内把 start-eligible V2 task 启动至 durable checkpoint。"""

        if not isinstance(accepted, AcceptedProductTaskInputV2):
            raise TypeError("accepted must be AcceptedProductTaskInputV2")
        request = accepted.request

        with self._start_gate.serialize(request.task_id):
            checkpoint = self._workflow_runtime.get_checkpoint(request.task_id)
            if checkpoint is None:
                checkpoint = self._workflow_runtime.start(
                    WorkflowStartRequest(
                        task_id=request.task_id,
                        request_data={
                            "product_request_version": request.version,
                            "product_request_task_id": request.task_id,
                            "product_request_hash": request.request_hash,
                            "product_session_binding_hash": (
                                accepted.session_binding_hash
                            ),
                        },
                    )
                )

        if not isinstance(checkpoint, WorkflowCheckpointView):
            raise TypeError(
                "workflow runtime must return WorkflowCheckpointView"
            )
        if checkpoint.task_id != request.task_id:
            raise ValueError(
                "CROSS_HOST_PRODUCT_FLOW_LINEAGE_INVALID: "
                "checkpoint task_id differs from accepted ProductTask"
            )
        return checkpoint

    def resume(
        self,
        task_id: str,
        command: WorkflowResumeCommand | None = None,
    ) -> WorkflowCheckpointView:
        """恢复 exact V2 workflow；不创建 request/binding 的第二份 truth。"""

        checkpoint = self._workflow_runtime.resume(task_id, command)
        if not isinstance(checkpoint, WorkflowCheckpointView):
            raise TypeError(
                "workflow runtime must return WorkflowCheckpointView"
            )
        if checkpoint.task_id != task_id.strip():
            raise ValueError(
                "CROSS_HOST_PRODUCT_FLOW_LINEAGE_INVALID: "
                "resumed checkpoint belongs to another task"
            )
        return checkpoint


__all__ = ["CrossHostProductFlow"]
