"""M2 Python 运行时兼容矩阵的结构契约。

Task 7 只增加 Python 3.14 非 canonical 兼容性证明；不得借此提高项目 Python 下限、
改变 Ruff 语法目标，或把兼容 lane 变成新的 canonical 质量门所有者。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "repository-regression.yml"
PYPROJECT = ROOT / "pyproject.toml"


def _workflow_text() -> str:
    """读取 canonical repository regression workflow。"""

    assert WORKFLOW.is_file(), "缺少 repository-regression.yml"
    return WORKFLOW.read_text(encoding="utf-8")


def test_python_matrix_keeps_311_canonical_and_adds_314_compatibility() -> None:
    """运行时矩阵必须明确区分 canonical 3.11 与 compatibility 3.14。"""

    text = _workflow_text()

    assert 'python-version: "3.11"\n            lane: canonical' in text
    assert 'python-version: "3.14"\n            lane: compatibility' in text
    assert "python-version: ${{ matrix.python-version }}" in text


def test_both_python_lanes_consume_the_same_locked_workspace_and_pytest_modes() -> None:
    """两个 Python lane 必须共享 committed lock 和相同的离线 pytest 回归入口。"""

    text = _workflow_text()

    # bootstrap 与 pytest 命令位于同一个 matrix job，因此两个 lane 消费同一份仓库 metadata/lock。
    assert text.count("uv sync --locked --all-packages") == 1
    assert text.count("uv run python -m pytest --import-mode=importlib -q") == 1
    assert text.count("uv run python -m pytest -q") == 1


def test_only_canonical_python_lane_owns_ruff_delta_gate() -> None:
    """3.14 是兼容性证明，不复制 canonical Ruff baseline ownership。"""

    text = _workflow_text()
    ruff_step = text.split("- name: Enforce no new repository Ruff diagnostics", 1)[1]

    assert "if: matrix.lane == 'canonical'" in ruff_step.split("run: |", 1)[0]


def test_python_compatibility_lane_does_not_raise_source_floor_or_ruff_target() -> None:
    """Task 7 必须保留 >=3.11 public floor 与 Ruff py311 语法目标。"""

    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">=3.11"
    assert pyproject["tool"]["ruff"]["target-version"] == "py311"
