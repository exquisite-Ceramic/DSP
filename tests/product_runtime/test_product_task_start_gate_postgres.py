"""ProductTask 首次 workflow start 的 PostgreSQL 串行化 gate 契约测试。"""

from __future__ import annotations

import threading

import design_product_runtime as product_runtime
import psycopg
import pytest
from design_orchestrator import (
    LangGraphWorkflowCheckpointReader,
    WorkflowCheckpointView,
    WorkflowPhase,
    WorkflowStartRequest,
)
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.langgraph_runtime import _runtime_config
from design_orchestrator.langgraph_state import CHECKPOINT_CONTRACT_VERSION, WorkflowGraphState
from design_product_runtime import (
    ProductTaskRequest,
    WallThicknessProductFlow,
    create_postgres_product_task_request_store,
)
from langgraph.graph import END, START, StateGraph


def _gate_type():
    """取得计划要求的 PostgreSQL gate；缺失时形成明确的 TDD RED。"""

    gate_type = getattr(product_runtime, "PostgresProductTaskStartGate", None)
    assert gate_type is not None, "PostgresProductTaskStartGate 尚未实现"
    return gate_type


def _reset_start_test_schemas(dsn: str) -> None:
    """并发 flow 用例使用 fresh request/checkpoint owners，避免跨测试 lineage 污染。"""

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS product_task CASCADE")
        connection.execute("DROP SCHEMA IF EXISTS orchestrator_checkpoint CASCADE")


def _request(task_id: str) -> ProductTaskRequest:
    """构造两个独立 facade 竞争的同一 immutable ProductTask request。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id="PROJECT-START-GATE",
        host_kind="REVIT",
        session_ref="SESSION-START-GATE",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


class _NoSagaStore:
    """首次启动 checkpoint 尚无 Saga；任何 Saga lookup 都属于测试错误。"""

    def get_saga(self, saga_id: str):
        """禁止 pre-execution 流程意外访问 Saga owner。"""

        raise AssertionError(f"unexpected saga lookup: {saga_id}")


class _PostgresCountingRuntime:
    """用真实 PostgreSQL checkpointer 持久化 checkpoint，并记录本实例的 start 次数。"""

    def __init__(self, saver, *, fail_after_persist: bool = False) -> None:
        self._saver = saver
        self._reader = LangGraphWorkflowCheckpointReader(checkpointer=saver)
        self._fail_after_persist = fail_after_persist
        self.start_requests: list[WorkflowStartRequest] = []

        builder = StateGraph(WorkflowGraphState)

        def persist(state: WorkflowGraphState) -> dict[str, object]:
            """不生成领域事实，只让 start 写入一个合法的 durable root checkpoint。"""

            del state
            return {}

        builder.add_node("persist", persist)
        builder.add_edge(START, "persist")
        builder.add_edge("persist", END)
        self._graph = builder.compile(checkpointer=saver)

    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None:
        """通过 Task 1 的只读 adapter 查询同一 durable checkpoint owner。"""

        return self._reader.get_checkpoint(task_id)

    def start(self, request: WorkflowStartRequest) -> WorkflowCheckpointView:
        """记录真实 start 调用，并通过 PostgreSQL LangGraph saver 持久化首个 checkpoint。"""

        self.start_requests.append(request)
        self._graph.invoke(
            {
                "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
                "task_id": request.task_id,
                "phase": WorkflowPhase.RESOLVE_HOST_CONTEXT.value,
            },
            _runtime_config(request.task_id),
        )
        checkpoint = self._reader.get_checkpoint(request.task_id)
        assert checkpoint is not None
        if self._fail_after_persist:
            # 模拟 start 已 durable commit，但调用方在收到返回值前丢失响应。这个异常不能让
            # 第二个 submit 再次调用 start；它必须重新读取刚刚已经持久化的 checkpoint。
            self._fail_after_persist = False
            raise RuntimeError("simulated response loss after checkpoint persistence")
        return checkpoint

    def resume(self, task_id: str, command=None) -> WorkflowCheckpointView:
        """本测试不执行 resume；保留公共 workflow port shape 以防 facade 误调用。"""

        del task_id, command
        raise AssertionError("start-gate concurrency test must not resume workflow")


def test_two_independent_postgres_gates_serialize_same_task(
    product_task_postgres_dsn: str,
) -> None:
    """两个独立连接竞争同一 task 时，后到者必须等前一个事务释放行锁。"""

    gate_type = _gate_type()
    first_gate = gate_type(product_task_postgres_dsn)
    second_gate = gate_type(product_task_postgres_dsn)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    failures: list[BaseException] = []

    def first_worker() -> None:
        """持有第一个数据库临界区，直到主线程显式允许释放。"""

        try:
            with first_gate.serialize("TASK-START-GATE-1"):
                first_entered.set()
                if not release_first.wait(timeout=5):
                    raise AssertionError("测试未能及时释放第一个 start gate")
        except BaseException as exc:  # noqa: BLE001 - 线程异常必须回传主测试线程。
            failures.append(exc)

    def second_worker() -> None:
        """竞争相同 task；只有拿到数据库锁之后才能设置 entered 事件。"""

        try:
            if not first_entered.wait(timeout=5):
                raise AssertionError("第一个 start gate 未及时进入")
            with second_gate.serialize("TASK-START-GATE-1"):
                second_entered.set()
        except BaseException as exc:  # noqa: BLE001 - 线程异常必须回传主测试线程。
            failures.append(exc)

    first_thread = threading.Thread(target=first_worker, daemon=True)
    second_thread = threading.Thread(target=second_worker, daemon=True)
    try:
        first_thread.start()
        assert first_entered.wait(timeout=5), "第一个 start gate 未进入临界区"
        second_thread.start()

        # 这里用事件超时只证明“第一个事务仍持锁时第二个不能进入”；真正释放后还会再证明
        # 第二个最终可以获得同一行锁，避免把线程没有调度误判成数据库串行化成功。
        assert not second_entered.wait(timeout=0.25), (
            "第二个 start gate 在第一个事务释放前进入了同一 task 临界区"
        )
        release_first.set()
        assert second_entered.wait(timeout=5), "第一个事务释放后第二个 start gate 仍未进入"
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert failures == []
    finally:
        release_first.set()
        first_gate.close()
        second_gate.close()


def test_two_independent_product_flows_start_same_task_only_once(
    product_task_postgres_dsn: str,
) -> None:
    """两个 facade 竞争同一 durable request/checkpoint 时只能形成一次有效 workflow start。"""

    _reset_start_test_schemas(product_task_postgres_dsn)
    gate_type = _gate_type()
    first_request_store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    second_request_store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    first_saver = create_postgres_checkpointer(product_task_postgres_dsn)
    second_saver = create_postgres_checkpointer(product_task_postgres_dsn)
    first_runtime = _PostgresCountingRuntime(first_saver)
    second_runtime = _PostgresCountingRuntime(second_saver)
    first_gate = gate_type(product_task_postgres_dsn)
    second_gate = gate_type(product_task_postgres_dsn)
    failures: list[BaseException] = []
    request = _request("TASK-FLOW-START-ONCE")

    try:
        first_flow = WallThicknessProductFlow(
            request_store=first_request_store,
            workflow_runtime=first_runtime,
            saga_store=_NoSagaStore(),
            start_gate=first_gate,
        )
        second_flow = WallThicknessProductFlow(
            request_store=second_request_store,
            workflow_runtime=second_runtime,
            saga_store=_NoSagaStore(),
            start_gate=second_gate,
        )

        def submit(flow: WallThicknessProductFlow) -> None:
            """并发提交同一 immutable request，并把线程异常带回主测试线程。"""

            try:
                flow.submit(request)
            except BaseException as exc:  # noqa: BLE001 - 线程异常必须由主线程统一断言。
                failures.append(exc)

        first_thread = threading.Thread(target=submit, args=(first_flow,), daemon=True)
        second_thread = threading.Thread(target=submit, args=(second_flow,), daemon=True)
        first_thread.start()
        second_thread.start()
        first_thread.join(timeout=10)
        second_thread.join(timeout=10)

        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert failures == []
        assert len(first_runtime.start_requests) + len(second_runtime.start_requests) == 1

        checkpoint = LangGraphWorkflowCheckpointReader(
            checkpointer=first_saver
        ).get_checkpoint(request.task_id)
        assert checkpoint is not None
        assert checkpoint.task_id == request.task_id
    finally:
        first_gate.close()
        second_gate.close()
        first_saver.close()
        second_saver.close()
        first_request_store.close()
        second_request_store.close()


def test_gate_holder_crash_before_start_rolls_back_and_next_flow_starts_once(
    product_task_postgres_dsn: str,
) -> None:
    """request 已持久化但首个 holder 在 start 前崩溃时，后继进程必须取得锁并仅启动一次。"""

    _reset_start_test_schemas(product_task_postgres_dsn)
    gate_type = _gate_type()
    first_request_store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    second_request_store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    saver = create_postgres_checkpointer(product_task_postgres_dsn)
    runtime = _PostgresCountingRuntime(saver)
    first_gate = gate_type(product_task_postgres_dsn)
    second_gate = gate_type(product_task_postgres_dsn)
    request = _request("TASK-CRASH-BEFORE-START")

    try:
        # submit 的 request-first 规则意味着进程在进入 gate 前已经提交 immutable request。
        first_request_store.create(request)

        with (
            pytest.raises(RuntimeError, match="simulated crash before start"),
            first_gate.serialize(request.task_id),
        ):
            assert runtime.get_checkpoint(request.task_id) is None
            # 异常退出 transaction() 模拟 holder 消失；数据库必须 rollback 并释放行锁。
            raise RuntimeError("simulated crash before start")

        second_flow = WallThicknessProductFlow(
            request_store=second_request_store,
            workflow_runtime=runtime,
            saga_store=_NoSagaStore(),
            start_gate=second_gate,
        )
        view = second_flow.submit(request)

        assert view.checkpoint.task_id == request.task_id
        assert len(runtime.start_requests) == 1
        assert runtime.get_checkpoint(request.task_id) is not None
    finally:
        first_gate.close()
        second_gate.close()
        saver.close()
        first_request_store.close()
        second_request_store.close()


def test_response_loss_after_checkpoint_persist_does_not_start_again(
    product_task_postgres_dsn: str,
) -> None:
    """首个 start 已持久化 checkpoint 但响应丢失时，第二次 submit 只能复用 checkpoint。"""

    _reset_start_test_schemas(product_task_postgres_dsn)
    gate_type = _gate_type()
    first_request_store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    second_request_store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    first_saver = create_postgres_checkpointer(product_task_postgres_dsn)
    second_saver = create_postgres_checkpointer(product_task_postgres_dsn)
    first_runtime = _PostgresCountingRuntime(first_saver, fail_after_persist=True)
    second_runtime = _PostgresCountingRuntime(second_saver)
    first_gate = gate_type(product_task_postgres_dsn)
    second_gate = gate_type(product_task_postgres_dsn)
    request = _request("TASK-RESPONSE-LOSS-AFTER-CHECKPOINT")

    try:
        first_flow = WallThicknessProductFlow(
            request_store=first_request_store,
            workflow_runtime=first_runtime,
            saga_store=_NoSagaStore(),
            start_gate=first_gate,
        )
        second_flow = WallThicknessProductFlow(
            request_store=second_request_store,
            workflow_runtime=second_runtime,
            saga_store=_NoSagaStore(),
            start_gate=second_gate,
        )

        with pytest.raises(
            RuntimeError,
            match="simulated response loss after checkpoint persistence",
        ):
            first_flow.submit(request)

        # gate 事务回滚不能回滚独立 checkpoint owner 的 durable 写入。
        durable_checkpoint = LangGraphWorkflowCheckpointReader(
            checkpointer=second_saver
        ).get_checkpoint(request.task_id)
        assert durable_checkpoint is not None
        assert len(first_runtime.start_requests) == 1

        replayed = second_flow.submit(request)

        assert replayed.checkpoint.task_id == request.task_id
        assert second_runtime.start_requests == []
        assert len(first_runtime.start_requests) + len(second_runtime.start_requests) == 1
    finally:
        first_gate.close()
        second_gate.close()
        first_saver.close()
        second_saver.close()
        first_request_store.close()
        second_request_store.close()
