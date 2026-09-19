"""M1 Python workspace 的结构契约测试。

本测试只消费 M0 已冻结的事实清单，不根据当前 import 是否成功来推断 workspace 成员。
这样可以避免把仅由根 pytest ``pythonpath`` 暴露的源码树误判为正式 Python distribution。
ADR-010 后续只通过显式 architecture-approved delta 扩展该历史基线。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs" / "superpowers" / "modernization" / "dependency-inventory.md"
ROOT_PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"

# ADR-010 正式把 Workflow Orchestrator 提升为独立 runtime owner distribution；
# 这里显式记录批准后的增量，不能回写 M0 inventory 假装该 manifest 在历史基线已经存在。
ARCHITECTURE_APPROVED_WORKSPACE_ADDITIONS = {"platform/orchestrator"}


def _m0_package_managed_members() -> set[str]:
    """从 M0 冻结的 manifest 表中提取应成为 uv workspace member 的子项目路径。"""

    inventory = INVENTORY.read_text(encoding="utf-8")
    section_start = inventory.index("### Python manifests confirmed at the frozen baseline")
    section_end = inventory.index(
        "### Source trees without a package-local manifest",
        section_start,
    )
    section = inventory[section_start:section_end]

    # 表格中的反引号路径是 M0 已确认的 package-managed manifest；根 pyproject 是 workspace root，
    # 因此不重复放入 members。这里只接受以 pyproject.toml 结尾的路径，避免说明文字污染集合。
    manifests = {
        match
        for match in re.findall(r"`([^`]+pyproject\.toml)`", section)
        if match != "pyproject.toml"
    }
    return {str(Path(path).parent).replace("\\", "/") for path in manifests}


def test_uv_workspace_matches_m0_package_manifest_inventory() -> None:
    """workspace 必须等于 M0 历史基线加上经过架构批准的显式增量。"""

    pyproject = tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))
    workspace = pyproject.get("tool", {}).get("uv", {}).get("workspace")

    assert workspace is not None, "缺少 [tool.uv.workspace]"
    actual_members = set(workspace.get("members", []))
    expected_members = _m0_package_managed_members() | ARCHITECTURE_APPROVED_WORKSPACE_ADDITIONS

    assert actual_members == expected_members

    # 这些源码树在 M0 中被明确记录为没有 package-local manifest；ADR-010 只批准 orchestrator，
    # 不允许借本次 runtime 工作顺手把其他 source-only 子树升级为正式 distribution。
    forbidden_members = {
        "platform/approval_scope",
        "platform/impact",
        "platform/interaction",
    }
    assert actual_members.isdisjoint(forbidden_members)


def test_workspace_preserves_python_floor_and_ruff_target() -> None:
    """ADR-010 引入 runtime package，但不提高 Python 支持下限或 Ruff 目标版本。"""

    pyproject = tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">=3.11"
    assert pyproject["tool"]["ruff"]["target-version"] == "py311"


def test_workspace_declares_default_dev_tooling_for_locked_verification() -> None:
    """默认 locked sync 必须继续安装 canonical Python 验证工具链。"""

    pyproject = tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))
    dev_group = set(pyproject.get("dependency-groups", {}).get("dev", []))

    # uv 默认同步 dependency-groups.dev，而不会默认同步 project.optional-dependencies extras。
    # canonical CI 不能再额外漂移安装 pytest 或 Ruff，因此这些工具必须进入共享 lock。
    assert {
        "pytest>=8.0",
        "pytest-asyncio>=0.23",
        "jsonschema>=4.20",
        "ruff",
    }.issubset(dev_group)


def test_workspace_has_committed_uv_lock() -> None:
    """共享 lock 必须作为仓库事实提交，而不能只存在于开发者本地环境。"""

    assert UV_LOCK.is_file(), "缺少提交到仓库的 uv.lock"
