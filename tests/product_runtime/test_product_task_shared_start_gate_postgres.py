"""共享 ProductTask PostgreSQL start gate 的并发回归。"""

from __future__ import annotations

import threading

import psycopg
from design_orchestrator import WorkflowCheckpointView, WorkflowPhase, WorkflowStartRequest
from design_product_runtime import (
    PostgresProductTaskStartGate,
    ProductTaskRequest,
    WallThicknessProductFlow,
    create_postgres_product_task_request_store,
)


class _NoSagaStore:
    """首次启动阶段不允许访问 Saga owner。"""

    def get_saga(self, saga_id: str):
        raise AssertionError(f"unexpected saga lookup: {saga_id}")


class _BlockingCountingRuntime:
    """在首个 start 内制造可控窗口，暴露共享 gate 是否真正串行化。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._checkpoint: WorkflowCheckpointView | None = None
        self.start_count = 0
        self.first_start_entered = threading.Event()
        self.second_start_entered = threading.Event()
        self.release_first_start = threading.Event()

    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None:
        del task_id
        with self._lock:
            return self._checkpoint

    def start(self, request: WorkflowStartRequest) -> WorkflowCheckpointView:
        with self._lock:
            self.start_count += 1
            call_index = self.start_count
            if call_index == 1:
                self.first_start_entered.set()
            else:
                self.second_start_entered.set()

        if call_index == 1 and not self.release_first_start.wait(timeout=5):
            raise AssertionError("测试未及时释放首个 workflow.start()")

        checkpoint = WorkflowCheckpointView(
            task_id=request.task_id,
            phase=WorkflowPhase.RESOLVE_HOST_CONTEXT,
        )
        with self._lock:
            self._checkpoint = checkpoint
        return checkpoint

    def resume(self, task_id: str, command=None) -> WorkflowCheckpointView:
        del task_id, command
        raise AssertionError("shared start-gate regression must not resume workflow")


def _reset_owner_schema(dsn: str) -> None:
    """每个用例从 fresh ProductTask owner schema 开始。"""

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS product_task CASCADE")


def _request() -> ProductTaskRequest:
    return ProductTaskRequest.create(
        task_id="TASK-SHARED-START-GATE",
        project_id="PROJECT-SHARED-START-GATE",
        host_kind="REVIT",
        session_ref="SESSION-SHARED-START-GATE",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


def test_shared_flow_and_gate_start_same_task_only_once(
    product_task_postgres_dsn: str,
) -> None:
    """production-shaped 同一 flow/gate 并发 submit 必须只调用一次 workflow.start。"""

    _reset_owner_schema(product_task_postgres_dsn)
    request_store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    start_gate = PostgresProductTaskStartGate(product_task_postgres_dsn)
    runtime = _BlockingCountingRuntime()
    flow = WallThicknessProductFlow(
        request_store=request_store,
        workflow_runtime=runtime,
        saga_store=_NoSagaStore(),
        start_gate=start_gate,
    )
    request = _request()
    failures: list[BaseException] = []

    def submit() -> None:
        try:
            flow.submit(request)
        except BaseException as exc:  # noqa: BLE001 - 线程异常必须回传主测试线程。
            failures.append(exc)

    first = threading.Thread(target=submit, daemon=True)
    second = threading.Thread(target=submit, daemon=True)
    try:
        first.start()
        assert runtime.first_start_entered.wait(timeout=5), "首个 workflow.start() 未进入"
        second.start()

        assert not runtime.second_start_entered.wait(timeout=0.5), (
            "共享 PostgresProductTaskStartGate 允许第二个并发 submit 在首个 start 完成前进入"
        )

        runtime.release_first_start.set()
        first.join(timeout=5)
        second.join(timeout=5)

        assert not first.is_alive()
        assert not second.is_alive()
        assert failures == []
        assert runtime.start_count == 1
    finally:
        runtime.release_first_start.set()
        first.join(timeout=5)
        second.join(timeout=5)
        start_gate.close()
        request_store.close()
