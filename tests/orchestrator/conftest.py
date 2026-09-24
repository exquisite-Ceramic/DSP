"""隔离需要可选 Workflow Orchestrator runtime 依赖的测试模块。

历史 Step23/25/26/36 lane 只验证 deterministic orchestrator 层，并不会安装 LangGraph
或 PostgreSQL runtime 依赖。这里仅在对应依赖缺失时阻止收集 runtime 专用测试；完整 workspace
回归与 workflow-orchestrator PostgreSQL gate 安装这些依赖后仍会正常收集并执行全部用例。
该 collection guard 只控制 pytest 模块收集，不豁免 Ruff 或 branch-vs-main quality gate。
"""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import pytest

_LANGGRAPH_TESTS = frozenset(
    {
        "test_langgraph_graph.py",
        "test_langgraph_runtime.py",
        "test_postgres_checkpoint.py",
        "test_real_owner_workflow_end_to_end.py",
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
        "test_task9_real_owner_acceptance.py",
        "test_workflow_end_to_end.py",
    }
)


def _dependency_available(module_name: str) -> bool:
    """只检查模块是否可解析，不在 collection guard 中执行第三方包代码。"""

    return find_spec(module_name) is not None


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
