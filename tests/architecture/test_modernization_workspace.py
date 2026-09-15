"""M1 Python workspace 的结构契约测试。

本测试只消费 M0 已冻结的事实清单，不根据当前 import 是否成功来推断 workspace 成员。
这样可以避免把仅由根 pytest ``pythonpath`` 暴露的源码树误判为正式 Python distribution。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs" / "superpowers" / "modernization" / "dependency-inventory.md"
ROOT_PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"


def _m0_package_managed_members() -> set[str]:
    """从 M0 冻结的 manifest 表中提取应成为 uv workspace member 的子项目路径。"""

    inventory = INVENTORY.read_text(encoding="utf-8")
    section_start = inventory.index("### Python manifests confirmed at the frozen baseline")
    section_end = inventory.index("### Source trees without a package-local manifest", section_start)
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
    """workspace 成员必须与 M0 已确认的 package-managed 子项目一一对应。"""

    pyproject = tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))
    workspace = pyproject.get("tool", {}).get("uv", {}).get("workspace")

    assert workspace is not None, "缺少 [tool.uv.workspace]"
    actual_members = set(workspace.get("members", []))
    expected_members = _m0_package_managed_members()

    assert actual_members == expected_members

    # 这四个源码树在 M0 中被明确记录为没有 package-local manifest，当前只能依赖根配置暴露。
    # M1 Task 4 不允许借 workspace 迁移顺手把它们升级为正式 distribution。
    forbidden_members = {
        "platform/approval_scope",
        "platform/impact",
        "platform/interaction",
        "platform/orchestrator",
    }
    assert actual_members.isdisjoint(forbidden_members)


def test_workspace_preserves_python_floor_and_ruff_target() -> None:
    """Task 4 只建立解析/锁定基础设施，不提高 Python 支持下限。"""

    pyproject = tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">=3.11"
    assert pyproject["tool"]["ruff"]["target-version"] == "py311"


def test_workspace_has_committed_uv_lock() -> None:
    """共享 lock 必须作为仓库事实提交，而不能只存在于开发者本地环境。"""

    assert UV_LOCK.is_file(), "缺少提交到仓库的 uv.lock"
