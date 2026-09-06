"""Phase I 真实 AutoCAD + Revit 双 Host 验收门的离线契约与 live 入口。"""

from __future__ import annotations

import hashlib
import importlib
import os
from dataclasses import is_dataclass
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/phase-i-real-cross-host-materialization-saga.yml"
RUNBOOK = ROOT / "docs/runbooks/phase-i-real-cross-host-wall-thickness.md"

EXPECTED_ENVIRONMENT = {
    "DSP_AUTOCAD_ENDPOINT",
    "DSP_AUTOCAD_DOCUMENT_REF",
    "DSP_AUTOCAD_FIXTURE_PATH",
    "DSP_AUTOCAD_FIXTURE_SHA256",
    "DSP_AUTOCAD_NATIVE_ID",
    "DSP_AUTOCAD_HOST_INSTANCE_ID",
    "DSP_REVIT_LIVE_PIPE",
    "DSP_REVIT_LIVE_DOCUMENT_REF",
    "DSP_REVIT_LIVE_FIXTURE_PATH",
    "DSP_REVIT_LIVE_FIXTURE_SHA256",
    "DSP_REVIT_LIVE_WALL_UNIQUE_ID",
    "DSP_REVIT_LIVE_HOST_INSTANCE_ID",
    "DSP_REVIT_LIVE_VERSION",
    "DSP_REVIT_LIVE_TFM",
    "DSP_REVIT_LIVE_API_DIR",
    "DSP_PHASE_I_SEMANTIC_ID",
}
EXPECTED_HELPER_SURFACE = {
    "AutoCadMaterializedExecutionPort",
    "PhaseIConvergenceEvidencePort",
    "PhaseILiveConfig",
    "PhaseILiveConfigurationError",
    "PhaseIRealReadinessRegistry",
    "RevitMaterializedExecutionPort",
    "run_partial_commit_acceptance",
    "run_positive_acceptance",
    "verify_fixture_sha256",
}


def _helper():
    return importlib.import_module("tests.integration.phase_i_live_host")


def _require_live() -> None:
    if os.environ.get("DSP_PHASE_I_LIVE") != "1":
        pytest.skip("set DSP_PHASE_I_LIVE=1 to run the real AutoCAD + Revit Phase I gate")
    if os.name != "nt":
        pytest.fail("DSP_PHASE_I_LIVE=1 requires the controlled Windows dual-Host machine")


def test_live_helper_surface_and_environment_contract_are_frozen() -> None:
    helper = _helper()
    assert EXPECTED_HELPER_SURFACE <= set(helper.__all__)
    assert is_dataclass(helper.PhaseILiveConfig)
    assert helper.PhaseILiveConfig.__dataclass_params__.frozen is True
    assert set(helper.PhaseILiveConfig.required_environment_variables()) == EXPECTED_ENVIRONMENT


def test_fixture_hash_guard_accepts_exact_hash_and_fails_closed(tmp_path: Path) -> None:
    helper = _helper()
    fixture = tmp_path / "controlled-fixture.bin"
    fixture.write_bytes(b"phase-i-controlled-fixture")
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()

    assert helper.verify_fixture_sha256(fixture, digest) == digest
    with pytest.raises(helper.PhaseILiveConfigurationError) as exc:
        helper.verify_fixture_sha256(fixture, "0" * 64)
    assert exc.value.code == "FIXTURE_HASH_MISMATCH"


def test_dedicated_workflow_separates_offline_and_real_dual_host_jobs() -> None:
    assert WORKFLOW.is_file()
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    dispatch = workflow["on"]["workflow_dispatch"]
    assert dispatch["inputs"]["scenario"]["options"] == ["positive", "partial_commit"]

    offline = workflow["jobs"]["phase-i-offline"]
    assert offline["runs-on"] == "ubuntu-latest"
    assert offline["env"]["DSP_PHASE_I_LIVE"] == "0"
    offline_runs = "\n".join(
        step.get("run", "") for step in offline["steps"] if isinstance(step, dict)
    )
    assert "test_phase_i_real_cross_host_wall_thickness_live.py" in offline_runs
    assert "Revit.AgentHost.Core.Tests.csproj" in offline_runs

    live = workflow["jobs"]["phase-i-real-dual-host"]
    assert live["runs-on"] == ["self-hosted", "Windows", "dsp-phase-i-dual-host"]
    assert live["env"]["DSP_PHASE_I_LIVE"] == "1"
    assert "workflow_dispatch" in live["if"]
    live_runs = "\n".join(
        step.get("run", "") for step in live["steps"] if isinstance(step, dict)
    )
    assert "DSP_PHASE_I_SCENARIO" in live_runs
    assert "test_phase_i_real_cross_host_wall_thickness_live.py" in live_runs


def test_runbook_freezes_fixture_integrity_build_and_reset_discipline() -> None:
    assert RUNBOOK.is_file()
    text = RUNBOOK.read_text(encoding="utf-8")
    for marker in (
        "DO NOT SAVE",
        "SHA-256",
        "200 mm",
        "300 mm",
        "201 mm",
        "REVISION_CONFLICT",
        "BEFORE_COMMIT",
        "PARTIALLY_COMMITTED",
        "DSP_PHASE_I_LIVE",
        "DSP_AUTOCAD_FIXTURE_SHA256",
        "DSP_REVIT_LIVE_FIXTURE_SHA256",
        'DspRevitVersion="2027"',
        'DspRevitTargetFramework="net10.0-windows"',
    ):
        assert marker in text


def test_real_positive_wall_thickness_acceptance() -> None:
    _require_live()
    helper = _helper()
    config = helper.PhaseILiveConfig.from_environment()

    evidence = helper.run_positive_acceptance(config)

    assert evidence["required_hosts"] == ["autocad", "revit"]
    assert evidence["readiness_status"] == "READY"
    assert evidence["autocad_post_wall_thickness"] == {"value": 300.0, "unit": "mm"}
    assert evidence["revit_post_wall_thickness"] == {"value": 300.0, "unit": "mm"}
    assert evidence["convergence_status"] == "CONVERGED"
    assert evidence["saga_status"] == "SUCCEEDED"
    assert evidence["materialized_status"] == "SUCCEEDED"


def test_real_revit_post_readiness_race_is_partial_commit() -> None:
    _require_live()
    helper = _helper()
    config = helper.PhaseILiveConfig.from_environment()

    evidence = helper.run_partial_commit_acceptance(config)

    assert evidence["required_hosts"] == ["autocad", "revit"]
    assert evidence["readiness_status"] == "READY"
    assert evidence["autocad_slice_status"] == "SUCCEEDED"
    assert evidence["revit_failure_ref"] == "REVISION_CONFLICT"
    assert evidence["revit_failure_phase"] == "BEFORE_COMMIT"
    assert evidence["revit_actual_delta_hash"] is None
    assert evidence["race_wall_thickness"] == {"value": 201.0, "unit": "mm"}
    assert evidence["convergence_status"] is None
    assert evidence["saga_status"] == "PARTIALLY_COMMITTED"
    assert evidence["materialized_status"] == "PARTIALLY_COMMITTED"
