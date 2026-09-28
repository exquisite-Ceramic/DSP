"""ProductTask exact query 的 request/checkpoint 组合与 split-read race 契约测试。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from design_execution_reconciliation import ExecutionSagaStatusV2
from design_orchestrator import WorkflowCheckpointView, WorkflowPhase
from design_product_runtime import ProductFlowStatus, ProductTaskRequest
import design_product_runtime as product_runtime


@dataclass(frozen=True, slots=True)
class _SagaSnapshot:
    """仅提供既有产品投影 helper 读取的 authoritative Saga 字段。"""

    status: ExecutionSagaStatusV2
    slice_states: tuple[object, ...] = ()


class _ScriptedRequestStore:
    """按调用顺序返回 request，用于精确模拟 split-read 并发窗口。"""

    def __init__(self, results: list[ProductTaskRequest | None]) -> None:
        self._results = list(results)
        self.calls: list[str] = []

    def get(self, task_id: str) -> ProductTaskRequest | None:
        """只允许计划内的 exact task lookup，不提供 latest/search fallback。"""

        self.calls.append(task_id)
        if not self._results:
            raise AssertionError("测试 request store 收到计划外的额外读取")
        return self._results.pop(0)


class _CheckpointReader:
    """记录 query 是否只执行只读 checkpoint lookup。"""

    def __init__(self, checkpoint: WorkflowCheckpointView | None) -> None:
        self.checkpoint = checkpoint
        self.calls: list[str] = []

    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None:
        """返回预设 framework-neutral checkpoint。"""

        self.calls.append(task_id)
        return self.checkpoint


class _SagaStore:
    """按 exact saga_id 返回 authoritative Saga snapshot。"""

    def __init__(self, snapshots: dict[str, _SagaSnapshot] | None = None) -> None:
        self.snapshots = snapshots or {}
        self.calls: list[str] = []

    def get_saga(self, saga_id: str) -> _SagaSnapshot | None:
        """记录 exact lookup，禁止 query 自己维护第二份 outcome state。"""

        self.calls.append(saga_id)
        return self.snapshots.get(saga_id)


def _request(task_id: str = "task-query-1") -> ProductTaskRequest:
    """构造冻结 wall-thickness vertical 的最小 immutable request。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id="project-a",
        host_kind="REVIT",
        session_ref="session-a",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


def _query_types():
    """取得计划新增类型；缺失时形成明确 RED，不把失败变成 import collection error。"""

    service_type = getattr(product_runtime, "ProductTaskQueryService", None)
    state_type = getattr(product_runtime, "ProductTaskQueryState", None)
    error_type = getattr(product_runtime, "ProductTaskQueryError", None)
    assert service_type is not None, "ProductTaskQueryService 尚未实现"
    assert state_type is not None, "ProductTaskQueryState 尚未实现"
    assert error_type is not None, "ProductTaskQueryError 尚未实现"
    return service_type, state_type, error_type


def _service(
    *,
    request_results: list[ProductTaskRequest | None],
    checkpoint: WorkflowCheckpointView | None,
    saga_snapshots: dict[str, _SagaSnapshot] | None = None,
):
    """按公开依赖面组装 query，并把三个 owner fake 一并返回用于调用顺序断言。"""

    service_type, state_type, error_type = _query_types()
    request_store = _ScriptedRequestStore(request_results)
    checkpoint_reader = _CheckpointReader(checkpoint)
    saga_store = _SagaStore(saga_snapshots)
    service = service_type(
        request_store=request_store,
        checkpoint_reader=checkpoint_reader,
        saga_store=saga_store,
    )
    return service, state_type, error_type, request_store, checkpoint_reader, saga_store


def test_absent_request_and_absent_checkpoint_is_not_found() -> None:
    """两个 durable owner 都不存在时返回 None，不创建任何任务状态。"""

    service, _, _, requests, checkpoints, sagas = _service(
        request_results=[None],
        checkpoint=None,
    )

    assert service.get("task-query-1") is None
    assert requests.calls == ["task-query-1"]
    assert checkpoints.calls == ["task-query-1"]
    assert sagas.calls == []


def test_persisted_request_without_checkpoint_is_accepted_pre_workflow() -> None:
    """request-first 崩溃窗口是合法查询事实，不能误报 not-found 或启动 workflow。"""

    request = _request()
    service, state_type, _, requests, checkpoints, sagas = _service(
        request_results=[request],
        checkpoint=None,
    )

    view = service.get(request.task_id)

    assert view.task_id == request.task_id
    assert view.request_hash == request.request_hash
    assert view.state is state_type.ACCEPTED_PRE_WORKFLOW
    assert view.flow is None
    assert requests.calls == [request.task_id]
    assert checkpoints.calls == [request.task_id]
    assert sagas.calls == []


def test_request_and_checkpoint_projects_existing_product_outcome_truth() -> None:
    """两边都存在时复用 WallThickness 产品投影，不由 query 重新解释 Saga 成功。"""

    request = _request()
    checkpoint = WorkflowCheckpointView(
        task_id=request.task_id,
        phase=WorkflowPhase.COMPLETED,
        saga_id="saga-query-1",
    )
    service, state_type, _, requests, checkpoints, sagas = _service(
        request_results=[request],
        checkpoint=checkpoint,
        saga_snapshots={
            "saga-query-1": _SagaSnapshot(status=ExecutionSagaStatusV2.SUCCEEDED)
        },
    )

    view = service.get(request.task_id)

    assert view.state is state_type.WORKFLOW
    assert view.flow is not None
    assert view.flow.status is ProductFlowStatus.SUCCEEDED
    assert view.flow.checkpoint == checkpoint
    assert requests.calls == [request.task_id]
    assert checkpoints.calls == [request.task_id]
    assert sagas.calls == ["saga-query-1"]


def test_checkpoint_without_request_is_lineage_invalid_after_stabilization_reread() -> None:
    """checkpoint 已存在但连续两次 exact request 都缺失才可判 lineage corruption。"""

    checkpoint = WorkflowCheckpointView(
        task_id="task-query-1",
        phase=WorkflowPhase.AWAIT_OPERATION_PROPOSAL,
    )
    service, _, error_type, requests, checkpoints, sagas = _service(
        request_results=[None, None],
        checkpoint=checkpoint,
    )

    with pytest.raises(error_type) as exc_info:
        service.get("task-query-1")

    assert exc_info.value.code == "PRODUCT_TASK_LINEAGE_INVALID"
    assert requests.calls == ["task-query-1", "task-query-1"]
    assert checkpoints.calls == ["task-query-1"]
    assert sagas.calls == []


def test_split_read_race_rereads_request_and_returns_workflow_instead_of_corruption() -> None:
    """request 在第一次读取后提交时，稳定化重读必须观察到它并正常投影 workflow。"""

    request = _request()
    checkpoint = WorkflowCheckpointView(
        task_id=request.task_id,
        phase=WorkflowPhase.AWAIT_OPERATION_PROPOSAL,
    )
    service, state_type, _, requests, checkpoints, sagas = _service(
        request_results=[None, request],
        checkpoint=checkpoint,
    )

    view = service.get(request.task_id)

    assert view.state is state_type.WORKFLOW
    assert view.flow is not None
    assert view.flow.status is ProductFlowStatus.WAITING
    assert requests.calls == [request.task_id, request.task_id]
    assert checkpoints.calls == [request.task_id]
    assert sagas.calls == []
