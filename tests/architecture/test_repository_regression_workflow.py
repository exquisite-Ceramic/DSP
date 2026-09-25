from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/repository-regression.yml"


def _workflow_text() -> str:
    assert WORKFLOW.is_file(), "repository-regression.yml must exist"
    return WORKFLOW.read_text(encoding="utf-8")


def _trigger_block(text: str) -> str:
    assert "\non:\n" in f"\n{text}"
    return text.split("on:\n", 1)[1].split("\njobs:\n", 1)[0]


def test_repository_regression_workflow_exists() -> None:
    assert WORKFLOW.is_file()


def test_current_repository_triggers_are_unfiltered() -> None:
    trigger_block = _trigger_block(_workflow_text())
    assert "push:" in trigger_block
    assert "pull_request:" in trigger_block
    assert "workflow_dispatch:" in trigger_block
    assert "paths:" not in trigger_block
    assert "paths-ignore:" not in trigger_block


def test_repository_regression_is_offline_only() -> None:
    text = _workflow_text()
    assert 'AGENT_HOST_TEST: "0"' in text
    assert 'DSP_PHASE_I_LIVE: "0"' in text
    assert 'DSP_REVIT_LIVE: "0"' in text
    assert 'DSP_PHASE_I_LIVE: "1"' not in text
    assert "self-hosted" not in text


def test_repository_regression_consumes_committed_uv_graph() -> None:
    """Task 5 后 canonical Python bootstrap 必须从 workspace metadata + lock 重建。"""

    text = _workflow_text()

    assert "python -m pip install uv" in text
    assert "uv sync --locked --all-packages" in text

    # 第一方 package ownership 已在 Task 4 的 workspace metadata 中声明。
    # canonical CI 不得继续用有顺序含义的 editable-install 链隐藏依赖关系。
    assert "-e contracts/python" not in text
    assert "-e hosts/autocad/sidecar" not in text
    assert "-e platform/semantic_runtime" not in text
    assert "-e platform/semantic_service" not in text
    assert "-e platform/semantic_mcp" not in text
    assert "-e providers/semantics" not in text


def test_repository_regression_owns_both_pytest_modes_and_revit_core() -> None:
    text = _workflow_text()
    assert "uv run python -m pytest --import-mode=importlib -q" in text
    assert "uv run python -m pytest -q" in text
    assert (
        "dotnet test "
        "hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj"
        in text
    )


def test_repository_regression_uses_one_locked_ruff_for_base_and_head() -> None:
    """Ruff delta 必须用 HEAD lock 里的同一个二进制检查历史 base 与当前 head。"""

    text = _workflow_text()
    command = (
        '"$RUFF_BIN" check --select E,F,I --output-format=json '
        "platform hosts/autocad/sidecar hosts/revit/sidecar tests"
    )

    assert "Enforce no new repository Ruff diagnostics" in text
    assert 'RUFF_BIN="$GITHUB_WORKSPACE/.venv/bin/ruff"' in text
    assert text.count(command) >= 2
    assert "BASE_SHA" in text
    assert 'git worktree add /tmp/dsp-base "$BASE_SHA"' in text
    assert "Counter" in text
    assert "head - base" in text

    # Task 7 只增加 3.14 兼容性证明；Ruff baseline 的 canonical ownership 仍属于 3.11 lane。
    ruff_step = text.split("- name: Enforce no new repository Ruff diagnostics", 1)[1]
    assert "if: matrix.lane == 'canonical'" in ruff_step.split("run: |", 1)[0]
