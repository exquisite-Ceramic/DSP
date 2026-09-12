from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github/workflows"

HISTORICAL_STEP_WORKFLOWS = (
    "step25-d6-parameter-binder.yml",
    "step26-interaction-session.yml",
    "step27-impact-layer.yml",
    "step28-approval-scope.yml",
    "step29-immutable-changeset.yml",
    "step30-execution-partitioning.yml",
    "step31-provider-binding.yml",
    "step32-gateway-authorization.yml",
    "step33-execution-reconciliation.yml",
    "step34-autocad-wall-thickness.yml",
    "step36-offset-create-scope-breach.yml",
    "step37-cross-host-saga-failure-injection.yml",
)


def _text(name: str) -> str:
    path = WORKFLOWS / name
    assert path.is_file(), f"workflow must remain present: {name}"
    return path.read_text(encoding="utf-8")


def test_historical_step_workflows_no_longer_own_importlib_full_repo_regression() -> None:
    offenders = [
        name
        for name in HISTORICAL_STEP_WORKFLOWS
        if "--import-mode=importlib" in _text(name)
    ]
    assert offenders == []


def test_phase_h_focused_acceptance_proofs_remain_present() -> None:
    text = _text("phase-h-revit-wall-thickness.yml")
    for expected in (
        "Verify Revit architecture boundary",
        "Verify Revit sidecar adapter",
        "Verify Revit design facts and enterprise mappings",
        "Verify Revit and AutoCAD reconciliation parity",
        "Verify live Revit gate remains external-only",
        "Verify Revit-free .NET core",
    ):
        assert expected in text


def test_phase_i_offline_and_real_dual_host_jobs_remain_present() -> None:
    text = _text("phase-i-real-cross-host-materialization-saga.yml")
    assert "phase-i-offline:" in text
    assert "phase-i-real-dual-host:" in text


def test_step36_and_step37_ruff_delta_guards_remain_present() -> None:
    for name in (
        "step36-offset-create-scope-breach.yml",
        "step37-cross-host-saga-failure-injection.yml",
    ):
        text = _text(name)
        assert "Ruff" in text
        assert "ruff check" in text
        assert "/tmp/main-ruff.json" in text
        assert "/tmp/head-ruff.json" in text
        assert "new diagnostics" in text
