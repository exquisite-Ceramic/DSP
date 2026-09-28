"""ProductTask exact query 在真实 PostgreSQL request/checkpoint owners 上的组合验收。"""

from __future__ import annotations

import psycopg
import pytest
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.langgraph_checkpoint_reader import LangGraphWorkflowCheckpointReader
from design_orchestrator.langgraph_runtime import _runtime_config
from design_orchestrator.langgraph_state import CHECKPOINT_CONTRACT_VERSION, WorkflowGraphState
from design_orchestrator.workflow_contracts import WorkflowPhase
from design_product_runtime import (
    ProductFlowStatus,
    ProductTaskQueryError,
    ProductTaskQueryService,
    ProductTaskQueryState,
    ProductTaskRequest,
    create_postgres_product_task_request_store,
)
from langgraph.graph import END, START, StateGraph


class _NoSagaStore:
    """这些 acceptance 只验证 pre-Saga query；任何 Saga 读取都属于测试失败。"""

    def get_saga(self, saga_id: str):
        """禁止无 saga_id 的早期 workflow 查询意外访问 Saga owner。"""

        raise AssertionError(f"unexpected saga lookup: {saga_id}")


class _CountingRequestStore:
    """包裹真实 PostgreSQL request store，只记录 exact lookup 次数。"""

    def __init__(self, store) -> None:
        self._store = store
        self.get_calls: list[str] = []

    def create(self, request: ProductTaskRequest) -> ProductTaskRequest:
        """透明转发 immutable create。"""

        return self._store.create(request)

    def get(self, task_id: str) -> ProductTaskRequest | None:
        """记录稳定化重读，并由真实 owner 执行 exact lookup。"""

        self.get_calls.append(task_id)
        return self._store.get(task_id)


def _reset_query_owners(dsn: str) -> None:
    """每个用例从空 request/checkpoint owner schemas 开始，避免跨测试 lineage 污染。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS product_task CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS orchestrator_checkpoint CASCADE")


def _request(task_id: str) -> ProductTaskRequest:
    """构造真实 PostgreSQL owner 可持久化的规范 vertical request。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id="PROJECT-QUERY-PG",
        host_kind="REVIT",
        session_ref="SESSION-QUERY-PG",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


def _persist_checkpoint(saver, *, task_id: str) -> None:
    """通过真实 PostgreSQL LangGraph saver 写入一个无 Saga 的 v2 root checkpoint。"""

    builder = StateGraph(WorkflowGraphState)

    def persist(state: WorkflowGraphState) -> dict[str, object]:
        """节点不生成领域事实，只触发 LangGraph 的真实 checkpoint persistence。"""

        del state
        return {}

    builder.add_node("persist", persist)
    builder.add_edge(START, "persist")
    builder.add_edge("persist", END)
    graph = builder.compile(checkpointer=saver)
    graph.invoke(
        {
            "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
            "task_id": task_id,
            "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
        },
        _runtime_config(task_id),
    )


def _query(store, saver) -> ProductTaskQueryService:
    """组合真实 request/checkpoint owners 与一个禁止意外 Saga lookup 的边界。"""

    return ProductTaskQueryService(
        request_store=store,
        checkpoint_reader=LangGraphWorkflowCheckpointReader(checkpointer=saver),
        saga_store=_NoSagaStore(),
    )


def test_postgres_request_only_projects_accepted_pre_workflow(
    product_task_postgres_dsn: str,
) -> None:
    """request 已提交但 checkpoint 尚未存在时必须保持可查询的 accepted-pre-workflow。"""

    _reset_query_owners(product_task_postgres_dsn)
    request = _request("TASK-QUERY-PG-PRESTART")
    store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    saver = create_postgres_checkpointer(product_task_postgres_dsn)
    try:
        store.create(request)
        view = _query(store, saver).get(request.task_id)
    finally:
        saver.close()
        store.close()

    assert view is not None
    assert view.task_id == request.task_id
    assert view.request_hash == request.request_hash
    assert view.state is ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW
    assert view.flow is None


def test_postgres_request_and_checkpoint_projects_workflow(
    product_task_postgres_dsn: str,
) -> None:
    """两个 durable owners 都存在时 exact query 返回既有 workflow 投影，不启动任何工作。"""

    _reset_query_owners(product_task_postgres_dsn)
    request = _request("TASK-QUERY-PG-WORKFLOW")
    store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    saver = create_postgres_checkpointer(product_task_postgres_dsn)
    try:
        store.create(request)
        _persist_checkpoint(saver, task_id=request.task_id)
        view = _query(store, saver).get(request.task_id)
    finally:
        saver.close()
        store.close()

    assert view is not None
    assert view.state is ProductTaskQueryState.WORKFLOW
    assert view.flow is not None
    assert view.flow.status is ProductFlowStatus.WAITING
    assert view.flow.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL


def test_postgres_checkpoint_without_request_fails_only_after_second_request_read(
    product_task_postgres_dsn: str,
) -> None:
    """孤立 checkpoint 必须先做真实 PostgreSQL stabilization re-read，再判 lineage invalid。"""

    _reset_query_owners(product_task_postgres_dsn)
    task_id = "TASK-QUERY-PG-CORRUPT"
    raw_store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    store = _CountingRequestStore(raw_store)
    saver = create_postgres_checkpointer(product_task_postgres_dsn)
    try:
        _persist_checkpoint(saver, task_id=task_id)
        with pytest.raises(ProductTaskQueryError) as exc_info:
            _query(store, saver).get(task_id)
    finally:
        saver.close()
        raw_store.close()

    assert exc_info.value.code == "PRODUCT_TASK_LINEAGE_INVALID"
    assert store.get_calls == [task_id, task_id]
