"""Phase I 真实双 Host 验收 PowerShell 包装脚本的离线契约。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests/integration/run_phase_i_live_acceptance.ps1"


def _script_text() -> str:
    assert SCRIPT.is_file()
    return SCRIPT.read_text(encoding="utf-8")


def test_script_exposes_only_one_scenario_per_invocation() -> None:
    text = _script_text()
    assert '[ValidateSet("offline", "positive", "partial_commit")]' in text
    assert '"all"' not in text
    assert "$Scenario" in text


def test_live_preflight_requires_exact_environment_and_fixture_hashes() -> None:
    text = _script_text()
    for name in (
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
    ):
        assert name in text
    assert "Get-FileHash" in text
    assert "SHA256" in text
    assert "FIXTURE_HASH_MISMATCH" in text
    assert "DSP_PHASE_I_LIVE" in text


def test_live_script_bootstraps_phase_i_pythonpath_for_local_runs() -> None:
    text = _script_text()
    assert "PYTHONPATH" in text
    for relative_path in (
        "contracts/python",
        "hosts/autocad/sidecar/src",
        "hosts/revit/sidecar/src",
        "platform/materialization_topology/src",
        "platform/materialization_planning/src",
        "platform/convergence/src",
        "platform/semantic_runtime/src",
    ):
        assert relative_path in text


def test_live_script_builds_revit_2027_before_mutation() -> None:
    text = _script_text()
    assert "Revit.AgentHost.csproj" in text
    assert "DspRevitVersion" in text
    assert "2027" in text
    assert "DspRevitTargetFramework" in text
    assert "net10.0-windows" in text
    assert "DspRevitApiDir" in text


def test_positive_and_partial_scenarios_call_exact_existing_pytest_cases() -> None:
    text = _script_text()
    assert "real_positive_wall_thickness_acceptance" in text
    assert "real_revit_post_readiness_race_is_partial_commit" in text
    assert "test_phase_i_real_cross_host_wall_thickness_live.py" in text
    assert 'DSP_PHASE_I_SCENARIO = "positive"' in text
    assert 'DSP_PHASE_I_SCENARIO = "partial_commit"' in text


def test_partial_scenario_requires_manual_fixture_restore_discipline() -> None:
    text = _script_text()
    assert "DO NOT SAVE" in text
    assert "重新打开" in text
    assert "200 mm" in text
    assert "partial_commit" in text
