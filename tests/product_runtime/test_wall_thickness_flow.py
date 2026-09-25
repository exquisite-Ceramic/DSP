"""Task 8：WallThicknessProductFlow 的 request-first 与 authoritative outcome 投影契约测试。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    SliceReconciliationStatusV2,
)
from design_orchestrator import (
    WorkflowCheckpointView,
    WorkflowPhase,
    WorkflowStartRequest,
)
from design_product_runtime import (
    ProductFlowStatus,
    ProductTaskRequest,
    WallThicknessProductFlow,
)


@dataclass(frozen=True, slots=True)
class _SliceSnapshot:
    """只提供 facade 投影需要读取的 Slice authoritative 字段。"""

    status: SliceReconciliationStatusV2
    verification_hash: str | None = None


@dataclass(frozen=True, slots=True)
class _SagaSnapshot:
    """只提供 facade 投影需要读取的 Saga authoritative 字段。"""

    status: ExecutionSagaStatusV2
    slice_states: tuple[_SliceSnapshot, ...] = ()


class _RequestStore:
    """最小 create-once request store fake，用于验证 facade 调用顺序而不复制数据库行为。"""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.requests: dict[str, ProductTaskRequest] = {}

    def create(self, request: ProductTaskRequest) -> ProductTaskRequest:
        """记录 create 调用并保持同 task、同 body 幂等。"""

        self.events.append("request.create")
        existing = self.requests.get(request.task_id)
        if existing is None:
            self.requests[request.task_id] = request
            return request
        if existing != request:
            raise AssertionError("测试 fake 不允许同 task 写入不同 request")
        return existing

    def get(self, task_id: str) -> ProductTaskRequest | None:
        """按 exact task_id 返回已经持久化的 request。"""

        self.events.append("request.get")
        return self.requests.get(task_id)


class _Runtime:
    """记录 framework-neutral workflow 调用，并允许注入一次 checkpoint 读取崩溃。"""

    def __init__(
        self,
        events: list[str],
        *,
        checkpoint: WorkflowCheckpointView | None = None,
        fail_checkpoint_once: bool = False,
    ) -> None:
        self.events = events
        self.checkpoint = checkpoint
        self.fail_checkpoint_once = fail_checkpoint_once
        self.start_requests: list[WorkflowStartRequest] = []

    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None:
        """模拟 runtime checkpoint read；崩溃发生在 request durable create 之后。"""

        self.events.append("runtime.get_checkpoint")
        if self.fail_checkpoint_once:
            self.fail_checkpoint_once = False
            raise RuntimeError("simulated crash after request write")
        if self.checkpoint is not None:
            assert self.checkpoint.task_id == task_id
        return self.checkpoint

    def start(self, request: WorkflowStartRequest) -> WorkflowCheckpointView:
        """记录 start，并返回一个可继续观察的初始 checkpoint。"""

        self.events.append("runtime.start")
        self.start_requests.append(request)
        self.checkpoint = WorkflowCheckpointView(
            task_id=request.task_id,
            phase=WorkflowPhase.AWAIT_OPERATION_PROPOSAL,
        )
        return self.checkpoint

    def resume(self, task_id: str, command=None) -> WorkflowCheckpointView:
        """Task 8 focused tests 不推进 HITL；保留 port shape 防止 facade 依赖 runtime-private API。"""

        del command
        self.events.append("runtime.resume")
        if self.checkpoint is None or self.checkpoint.task_id != task_id:
            raise AssertionError("测试 runtime 没有可恢复 checkpoint")
        return self.checkpoint


class _SagaStore:
    """按 exact saga_id 暴露 authoritative Saga snapshot。"""

    def __init__(self, snapshots: dict[str, _SagaSnapshot] | None = None) -> None:
        self.snapshots = snapshots or {}
        self.requested_ids: list[str] = []

    def get_saga(self, saga_id: str) -> _SagaSnapshot | None:
        """记录 exact lookup，禁止测试依赖 latest/reverse lookup。"""

        self.requested_ids.append(saga_id)
        return self.snapshots.get(saga_id)


def _request(*, task_id: str = "task-wall-300", thickness: float = 300.0) -> ProductTaskRequest:
    """构造冻结 vertical 的规范 Revit wall-thickness 产品请求。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id="project-a",
        host_kind="REVIT",
        session_ref="revit-session-a",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": thickness, "unit": "mm"}},
    )


def _flow(
    *,
    events: list[str] | None = None,
    checkpoint: WorkflowCheckpointView | None = None,
    saga_snapshots: dict[str, _SagaSnapshot] | None = None,
    request_store: _RequestStore | None = None,
    runtime: _Runtime | None = None,
) -> tuple[WallThicknessProductFlow, _RequestStore, _Runtime, _SagaStore]:
    """组装只包含 Task 8 三个 owner port 的 facade 测试环境。"""

    owned_events = events if events is not None else []
    owned_request_store = request_store or _RequestStore(owned_events)
    owned_runtime = runtime or _Runtime(owned_events, checkpoint=checkpoint)
    saga_store = _SagaStore(saga_snapshots)
    return (
        WallThicknessProductFlow(
            request_store=owned_request_store,
            workflow_runtime=owned_runtime,
            saga_store=saga_store,
        ),
        owned_request_store,
        owned_runtime,
        saga_store,
    )


def test_submit_persists_request_before_checkpoint_lookup_and_starts_only_when_absent() -> None:
    """request 必须先 durable create；没有 checkpoint 时才允许启动 workflow。"""

    events: list[str] = []
    flow, request_store, runtime, _ = _flow(events=events)
    request = _request()

    view = flow.submit(request)

    assert events[:3] == [
        "request.create",
        "runtime.get_checkpoint",
        "runtime.start",
    ]
    assert request_store.requests[request.task_id] == request
    assert len(runtime.start_requests) == 1
    assert dict(runtime.start_requests[0].request_data) == {
        "product_request_task_id": request.task_id,
        "product_request_hash": request.request_hash,
    }
    assert view.status is ProductFlowStatus.WAITING


def test_submit_with_existing_checkpoint_never_starts_a_second_workflow() -> None:
    """已有 durable checkpoint 时 submit 只能复用 owner truth，不能创建并行 workflow。"""

    events: list[str] = []
    checkpoint = WorkflowCheckpointView(
        task_id="task-wall-300",
        phase=WorkflowPhase.AWAIT_OPERATION_PROPOSAL,
    )
    flow, _, runtime, _ = _flow(events=events, checkpoint=checkpoint)

    view = flow.submit(_request())

    assert events == ["request.create", "runtime.get_checkpoint"]
    assert runtime.start_requests == []
    assert view.status is ProductFlowStatus.WAITING
    assert view.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL


def test_request_written_before_start_crash_is_recoverable_from_fresh_flow() -> None:
    """request-write / start 前崩溃后，重建 facade 仍能按同一 request 安全启动。"""

    events: list[str] = []
    request_store = _RequestStore(events)
    crashing_runtime = _Runtime(events, fail_checkpoint_once=True)
    first_flow, _, _, _ = _flow(
        events=events,
        request_store=request_store,
        runtime=crashing_runtime,
    )
    request = _request()

    with pytest.raises(RuntimeError, match="simulated crash"):
        first_flow.submit(request)

    # 崩溃发生时 request 已经 durable；不能通过回滚 request 来掩盖启动窗口。
    assert request_store.requests[request.task_id] == request
    assert events[:2] == ["request.create", "runtime.get_checkpoint"]

    # 新 runtime 没有 checkpoint，同 body replay 必须幂等，然后正常 start。
    rebuilt_runtime = _Runtime(events)
    rebuilt_flow, _, _, _ = _flow(
        events=events,
        request_store=request_store,
        runtime=rebuilt_runtime,
    )
    view = rebuilt_flow.submit(request)

    assert len(rebuilt_runtime.start_requests) == 1
    assert view.status is ProductFlowStatus.WAITING


@pytest.mark.parametrize(
    ("saga_status", "expected"),
    [
        (ExecutionSagaStatusV2.SUCCEEDED, ProductFlowStatus.SUCCEEDED),
        (ExecutionSagaStatusV2.FAILED, ProductFlowStatus.FAILED),
        (
            ExecutionSagaStatusV2.PARTIALLY_COMMITTED,
            ProductFlowStatus.PARTIALLY_COMMITTED,
        ),
        (ExecutionSagaStatusV2.DIVERGED, ProductFlowStatus.DIVERGED),
    ],
)
def test_authoritative_saga_terminal_status_maps_one_to_one(
    saga_status: ExecutionSagaStatusV2,
    expected: ProductFlowStatus,
) -> None:
    """四个 authoritative Saga terminal 必须一对一投影，产品层不得重新解释成功或失败。"""

    checkpoint = WorkflowCheckpointView(
        task_id="task-wall-300",
        phase=WorkflowPhase.COMPLETED,
        saga_id="saga-1",
    )
    flow, _, _, saga_store = _flow(
        checkpoint=checkpoint,
        saga_snapshots={"saga-1": _SagaSnapshot(status=saga_status)},
    )

    view = flow.get("task-wall-300")

    assert saga_store.requested_ids == ["saga-1"]
    assert view.status is expected
    assert view.saga_id == "saga-1"


def test_workflow_completed_without_authoritative_saga_success_never_projects_success() -> None:
    """WorkflowPhase.COMPLETED 只是导航事实，缺少 terminal Saga 时必须 fail closed。"""

    checkpoint = WorkflowCheckpointView(
        task_id="task-wall-300",
        phase=WorkflowPhase.COMPLETED,
        saga_id="saga-nonterminal",
    )
    flow, _, _, _ = _flow(
        checkpoint=checkpoint,
        saga_snapshots={
            "saga-nonterminal": _SagaSnapshot(status=ExecutionSagaStatusV2.EXECUTING)
        },
    )

    view = flow.get("task-wall-300")

    assert view.status is ProductFlowStatus.RECOVERY_REQUIRED
    assert view.status is not ProductFlowStatus.SUCCEEDED


def test_host_committed_reconciling_without_verification_projects_recovery_required() -> None:
    """已知 Host commit 但独立 evidence 未取得时，产品层必须保持 recovery-required。"""

    checkpoint = WorkflowCheckpointView(
        task_id="task-wall-300",
        phase=WorkflowPhase.VERIFY_RECONCILE,
        saga_id="saga-known-commit",
    )
    flow, _, _, _ = _flow(
        checkpoint=checkpoint,
        saga_snapshots={
            "saga-known-commit": _SagaSnapshot(
                status=ExecutionSagaStatusV2.EXECUTING,
                slice_states=(
                    _SliceSnapshot(
                        status=SliceReconciliationStatusV2.RECONCILING,
                        verification_hash=None,
                    ),
                ),
            )
        },
    )

    view = flow.get("task-wall-300")

    assert view.status is ProductFlowStatus.RECOVERY_REQUIRED
    assert view.status is not ProductFlowStatus.SUCCEEDED


def test_cancelled_workflow_projects_cancelled_without_saga_lookup() -> None:
    """用户在 pre-execution HITL 拒绝时，workflow CANCELLED 可以直接投影为产品取消。"""

    checkpoint = WorkflowCheckpointView(
        task_id="task-wall-300",
        phase=WorkflowPhase.CANCELLED,
    )
    flow, _, _, saga_store = _flow(checkpoint=checkpoint)

    view = flow.get("task-wall-300")

    assert view.status is ProductFlowStatus.CANCELLED
    assert saga_store.requested_ids == []
