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


def test_repository_regression_owns_both_pytest_modes_and_revit_core() -> None:
    text = _workflow_text()
    assert "python -m pytest --import-mode=importlib -q" in text
    assert "python -m pytest -q" in text
    assert (
        "dotnet test "
        "hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj"
        in text
    )


def test_repository_regression_uses_ruff_baseline_delta() -> None:
    text = _workflow_text()
    command = (
        "ruff check --select E,F,I --output-format=json "
        "platform hosts/autocad/sidecar tests"
    )
    assert "Enforce no new repository Ruff diagnostics" in text
    assert text.count(command) >= 2
    assert "BASE_SHA" in text
    assert 'git worktree add /tmp/dsp-base "$BASE_SHA"' in text
    assert "Counter" in text
    assert "head - base" in text
