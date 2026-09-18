"""隔离需要可选 Workflow Orchestrator runtime 依赖的测试模块。

历史 Step23/25/26/36 lane 只验证 deterministic orchestrator 层，并不会安装 LangGraph
或 PostgreSQL runtime 依赖。这里仅在对应依赖缺失时阻止收集 runtime 专用测试；完整 workspace
回归与 workflow-orchestrator PostgreSQL gate 安装这些依赖后仍会正常收集并执行全部用例。
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
        "test_workflow_end_to_end.py",
        "test_workflow_resume_authoritative_truth.py",
    }
)

_POSTGRES_TESTS = frozenset(
    {
        "test_postgres_checkpoint.py",
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
