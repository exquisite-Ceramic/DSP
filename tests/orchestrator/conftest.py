"""隔离需要可选 Workflow Orchestrator runtime 依赖的测试模块。

历史 Step23/25/26/36 lane 只验证 deterministic orchestrator 层，并不会安装 LangGraph
或 PostgreSQL runtime 依赖。这里仅在对应依赖缺失时阻止收集 runtime 专用测试；完整 workspace
回归与 workflow-orchestrator PostgreSQL gate 安装这些依赖后仍会正常收集并执行全部用例。
该 collection guard 只控制 pytest 模块收集，不豁免 Ruff 或 branch-vs-main quality gate。
"""

from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path

import pytest

_LANGGRAPH_TESTS = frozenset(
    {
        "test_langgraph_graph.py",
        "test_langgraph_runtime.py",
        "test_postgres_checkpoint.py",
        "test_real_owner_workflow_end_to_end.py",
        "test_task10_durable_recovery.py",
        "test_task10_review_regressions.py",
        "test_task9_parameter_binding_lineage.py",
        "test_task9_real_owner_acceptance.py",
        "test_workflow_end_to_end.py",
        "test_workflow_resume_authoritative_truth.py",
    }
)

# ``test_canonical_owner_ports.py`` 同时承载 deterministic owner tests 与少量真实
# LangGraph saver/graph proofs，不能像纯 runtime 模块一样整文件 ignore。这里只标记真正
# 依赖 LangGraph 的两个 6R.3 用例，使轻量 lane 仍执行该模块其余 owner regression。
_LANGGRAPH_MIXED_TESTS = frozenset(
    {
        "test_task6r3_complete_mismatch_reaches_adapter_but_not_real_impact",
        "test_task6r3_rebuilt_adapter_consumes_only_saver_restored_exact_refs",
    }
)

_POSTGRES_TESTS = frozenset(
    {
        "test_postgres_checkpoint.py",
        "test_real_owner_workflow_end_to_end.py",
        "test_task10_durable_recovery.py",
        "test_task10_review_regressions.py",
        "test_task9_real_owner_acceptance.py",
        "test_workflow_end_to_end.py",
    }
)


def _dependency_available(module_name: str) -> bool:
    """只检查模块是否可解析，不在 collection guard 中执行第三方包代码。"""

    return find_spec(module_name) is not None


def _reset_execution_owner_postgres(dsn: str) -> None:
    """只清理 Task 10 使用的 Execution Saga owner 数据，不触碰 migration ledger。"""

    from design_execution_reconciliation.postgres import (
        apply_execution_saga_migrations,
        connect_postgres,
    )

    conn = connect_postgres(dsn)
    try:
        apply_execution_saga_migrations(conn)
        with conn.transaction():
            conn.execute(
                """
                TRUNCATE TABLE
                    execution_saga.host_dispatch_observation,
                    execution_saga.host_dispatch_intent,
                    execution_saga.outbox,
                    execution_saga.inbox_receipt,
                    execution_saga.saga_v2
                CASCADE
                """
            )
    finally:
        conn.close()


@pytest.fixture
def task10_postgres_execution_owner_factory():
    """提供 fresh PostgreSQL Saga/dispatch store 连接；不实现任何 owner 业务语义。

    Task 10 需要在 runtime A/B 之间显式关闭并重建真实持久化连接。fixture 只负责
    migration、测试隔离和连接生命周期；Saga transition、dispatch replay/recovery 仍完全由
    repository production stores 与 coordinator 承担。
    """

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")

    from design_execution_reconciliation import create_execution_saga_store_v2
    from design_execution_reconciliation.postgres_dispatch_intent import (
        PostgresHostDispatchIntentStore,
    )

    _reset_execution_owner_postgres(dsn)
    opened: list[object] = []

    def factory():
        saga_store = create_execution_saga_store_v2(
            backend="postgres",
            postgres_dsn=dsn,
        )
        dispatch_store = PostgresHostDispatchIntentStore(dsn)
        opened.extend((saga_store, dispatch_store))
        return saga_store, dispatch_store

    yield factory

    for store in reversed(opened):
        close = getattr(store, "close", None)
        if callable(close):
            close()
    _reset_execution_owner_postgres(dsn)


def pytest_ignore_collect(
    collection_path: Path,
    config: pytest.Config,
) -> bool:
    """缺少 runtime 依赖时只忽略对应专用测试，不影响 deterministic orchestrator 回归。"""

    del config
    name = collection_path.name

    if name in _LANGGRAPH_TESTS and not _dependency_available("langgraph"):
        return True
    if name in _POSTGRES_TESTS and not _dependency_available("psycopg"):
        return True
    return False


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """混合模块缺少 LangGraph 时只 skip runtime proof，不隐藏同文件 deterministic tests。"""

    del config
    if _dependency_available("langgraph"):
        return

    marker = pytest.mark.skip(reason="langgraph is required for Task 6R.3 graph proofs")
    for item in items:
        if (
            item.path.name == "test_canonical_owner_ports.py"
            and item.name in _LANGGRAPH_MIXED_TESTS
        ):
            item.add_marker(marker)
