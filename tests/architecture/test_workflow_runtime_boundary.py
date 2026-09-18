"""ADR-010 Workflow Orchestrator runtime ownership 的架构边界测试。

这些测试先冻结“orchestrator 必须成为独立 workspace distribution，且 LangGraph 只能
由该 owner package 持有”的结构事实。Task 1 按 TDD 要求先提交本文件，确认当前基线
会因为缺少 package-local manifest / workspace membership 而失败，再补最小实现。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "platform" / "orchestrator"


def test_orchestrator_is_a_workspace_distribution() -> None:
    """Workflow Orchestrator 必须成为独立、可锁定依赖的 uv workspace distribution。"""

    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "platform/orchestrator" in root["tool"]["uv"]["workspace"]["members"]

    package = tomllib.loads((ORCHESTRATOR / "pyproject.toml").read_text(encoding="utf-8"))
    assert package["project"]["name"] == "design-orchestrator"


def test_langgraph_is_owned_by_orchestrator_package() -> None:
    """LangGraph 依赖必须只由 Workflow Orchestrator runtime owner 显式声明。"""

    package = tomllib.loads((ORCHESTRATOR / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = tuple(package["project"]["dependencies"])

    assert any(item.startswith("langgraph>=1.2.11") for item in dependencies)
    assert any(
        item.startswith("langgraph-checkpoint-postgres>=3.1.2")
        for item in dependencies
    )


def test_existing_domain_modules_do_not_import_langgraph() -> None:
    """既有 deterministic domain modules 不得把 framework 类型泄漏进业务边界。"""

    for name in (
        "canonical_operations.py",
        "operation_resolver.py",
        "parameter_binder.py",
        "interactive_binding.py",
    ):
        text = (ORCHESTRATOR / "src" / "design_orchestrator" / name).read_text(
            encoding="utf-8"
        )
        assert "langgraph" not in text
