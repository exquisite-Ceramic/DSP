"""Revit wall-thickness 产品请求对既有 workflow/Saga owner 的薄 facade。"""

from __future__ import annotations

from typing import Protocol

from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    ExecutionSagaStoreV2,
    SliceReconciliationStatusV2,
    StoredExecutionSagaV2,
)
from design_orchestrator import (
    WorkflowCheckpointView,
    WorkflowOrchestratorPort,
    WorkflowPhase,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)

from .contracts import ProductFlowStatus, ProductFlowView, ProductTaskRequest
from .start_gate import ProductTaskStartGate


class ProductTaskRequestStore(Protocol):
    """ProductFlow 只需要 immutable request owner 的 create/get 最小公共面。"""

    def create(self, request: ProductTaskRequest) -> ProductTaskRequest:
        """按 exact task_id create-once；同 body replay 必须幂等。"""

        ...

    def get(self, task_id: str) -> ProductTaskRequest | None:
        """按 exact task_id 读取 immutable request。"""

        ...


_TERMINAL_SAGA_STATUS_MAP = {
    ExecutionSagaStatusV2.SUCCEEDED: ProductFlowStatus.SUCCEEDED,
    ExecutionSagaStatusV2.FAILED: ProductFlowStatus.FAILED,
    ExecutionSagaStatusV2.PARTIALLY_COMMITTED: ProductFlowStatus.PARTIALLY_COMMITTED,
    ExecutionSagaStatusV2.DIVERGED: ProductFlowStatus.DIVERGED,
}
_KNOWN_COMMIT_SLICE_STATUSES = frozenset(
    {
        SliceReconciliationStatusV2.HOST_COMMITTED,
        SliceReconciliationStatusV2.RECONCILING,
    }
)
_ACTIVE_RECOVERY_SAGA_STATUSES = frozenset(
    {
        ExecutionSagaStatusV2.EXECUTING,
        ExecutionSagaStatusV2.CONVERGENCE_PENDING,
    }
)
_ACTIVE_RECOVERY_WORKFLOW_PHASES = frozenset(
    {
        WorkflowPhase.APPLY_WAIT,
        WorkflowPhase.VERIFY_RECONCILE,
    }
)


def _load_saga(
    checkpoint: WorkflowCheckpointView,
    saga_store: ExecutionSagaStoreV2,
) -> StoredExecutionSagaV2 | None:
    """只允许通过 checkpoint 已持有的 exact saga_id 访问 authoritative Saga owner。"""

    if checkpoint.saga_id is None:
        return None
    return saga_store.get_saga(checkpoint.saga_id)


def _has_known_commit_recovery(saga: StoredExecutionSagaV2) -> bool:
    """识别已经越过 Host commit 边界但尚未形成 terminal Saga 的 durable Slice truth。"""

    return any(
        slice_state.status in _KNOWN_COMMIT_SLICE_STATUSES
        for slice_state in saga.slice_states
    )


def _project_status(
    checkpoint: WorkflowCheckpointView,
    saga: StoredExecutionSagaV2 | None,
) -> ProductFlowStatus:
    """执行冻结的 outcome 投影；任何模糊执行态都 fail closed 为 recovery-required。"""

    if saga is not None:
        terminal = _TERMINAL_SAGA_STATUS_MAP.get(saga.status)
        if terminal is not None:
            # 只有 authoritative Saga SUCCEEDED 才能让产品 SUCCEEDED；workflow COMPLETED
            # 本身永远不参与成功判定。
            return terminal

        if _has_known_commit_recovery(saga):
            # HOST_COMMITTED/RECONCILING（尤其 verification_hash=None）意味着 side effect
            # 已知发生但 authoritative verification 尚未终结，必须进入恢复语义。
            return ProductFlowStatus.RECOVERY_REQUIRED

        if saga.status in _ACTIVE_RECOVERY_SAGA_STATUSES:
            # 同步 facade 返回后仍停留在 execution/convergence 的非终态，后续动作必须
            # 由 owner recovery/poll 决定，产品层不能把它降格成普通等待或推断成功。
            return ProductFlowStatus.RECOVERY_REQUIRED

    if checkpoint.phase is WorkflowPhase.CANCELLED:
        return ProductFlowStatus.CANCELLED
    if checkpoint.phase is WorkflowPhase.FAILED:
        return ProductFlowStatus.FAILED
    if checkpoint.phase is WorkflowPhase.COMPLETED:
        # COMPLETED 只有 workflow navigation 含义；没有 terminal Saga 时 fail closed。
        return ProductFlowStatus.RECOVERY_REQUIRED
    if checkpoint.phase in _ACTIVE_RECOVERY_WORKFLOW_PHASES:
        return ProductFlowStatus.RECOVERY_REQUIRED
    return ProductFlowStatus.WAITING


def project_wall_thickness_product_flow(
    checkpoint: WorkflowCheckpointView,
    saga_store: ExecutionSagaStoreV2,
) -> ProductFlowView:
    """共享 WallThicknessProductFlow 已冻结的 workflow/Saga outcome 投影规则。"""

    if not isinstance(checkpoint, WorkflowCheckpointView):
        raise TypeError("workflow runtime must return WorkflowCheckpointView")
    if saga_store is None:
        raise ValueError("saga_store must not be None")

    saga = _load_saga(checkpoint, saga_store)
    status = _project_status(checkpoint, saga)
    return ProductFlowView(status=status, checkpoint=checkpoint)


class WallThicknessProductFlow:
    """只负责 request persistence、workflow 驱动与 authoritative outcome 投影。

    facade 不拥有 semantic/planning/execution/reconciliation 真相；所有 durable domain facts
    继续由既有 owner 持有。这里也不读取 LangGraph private state，只使用 framework-neutral
    ``WorkflowOrchestratorPort`` checkpoint surface 和 exact ``saga_id`` lookup。
    """

    def __init__(
        self,
        *,
        request_store: ProductTaskRequestStore,
        workflow_runtime: WorkflowOrchestratorPort,
        saga_store: ExecutionSagaStoreV2,
        start_gate: ProductTaskStartGate,
    ) -> None:
        """绑定既有 owners 与首次启动 gate；facade 自身不创建任何 durable state。"""

        if request_store is None:
            raise ValueError("request_store must not be None")
        if workflow_runtime is None:
            raise ValueError("workflow_runtime must not be None")
        if saga_store is None:
            raise ValueError("saga_store must not be None")
        if start_gate is None:
            raise ValueError("start_gate must not be None")
        self._request_store = request_store
        self._workflow_runtime = workflow_runtime
        self._saga_store = saga_store
        self._start_gate = start_gate

    def submit(self, request: ProductTaskRequest) -> ProductFlowView:
        """先持久化 immutable request，再串行化 exact task 的首次 workflow start。

        request create 故意位于 gate 之前：不同进程先竞争 immutable ProductTask owner，随后
        才进入 ``checkpoint read → possible start`` 临界区。gate 内必须重新读取 checkpoint，
        因而等待锁的提交者会观察到前一个提交者已经持久化的首个 checkpoint，而不会再次
        调用 ``start()``。异常退出时数据库事务释放 gate 锁；request 仍可由后续进程幂等重放。
        """

        if not isinstance(request, ProductTaskRequest):
            raise TypeError("request must be a ProductTaskRequest")

        stored = self._request_store.create(request)
        if not isinstance(stored, ProductTaskRequest):
            raise TypeError("request_store.create() must return a ProductTaskRequest")
        if stored != request:
            # 正常 owner 会对不同 body 抛 conflict；这里保留防御性 fail-closed，避免 facade
            # 在异常 adapter 下把另一个 task body 的 hash 带入 workflow locator。
            raise RuntimeError("request store returned a different ProductTask request")

        with self._start_gate.serialize(stored.task_id):
            # checkpoint lookup 必须发生在锁内，不能复用进入 gate 前的观察结果。
            checkpoint = self._workflow_runtime.get_checkpoint(stored.task_id)
            if checkpoint is None:
                checkpoint = self._workflow_runtime.start(
                    WorkflowStartRequest(
                        task_id=stored.task_id,
                        request_data={
                            # request_data 只携带 immutable owner locator/hash；完整 request body
                            # 始终留在 ProductTask request owner，禁止形成 checkpoint 第二真相。
                            "product_request_task_id": stored.task_id,
                            "product_request_hash": stored.request_hash,
                        },
                    )
                )
        return project_wall_thickness_product_flow(checkpoint, self._saga_store)

    def resume(
        self,
        task_id: str,
        command: WorkflowResumeCommand | None = None,
    ) -> ProductFlowView:
        """通过公共 workflow port 恢复 exact task，并立即投影最新 owner truth。"""

        checkpoint = self._workflow_runtime.resume(task_id, command)
        return project_wall_thickness_product_flow(checkpoint, self._saga_store)

    def get(self, task_id: str) -> ProductFlowView | None:
        """读取当前 workflow checkpoint；不存在时不猜测或创建任何 domain 状态。"""

        checkpoint = self._workflow_runtime.get_checkpoint(task_id)
        if checkpoint is None:
            return None
        return project_wall_thickness_product_flow(checkpoint, self._saga_store)


__all__ = [
    "ProductTaskRequestStore",
    "WallThicknessProductFlow",
    "project_wall_thickness_product_flow",
]
