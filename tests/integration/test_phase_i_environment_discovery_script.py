"""Phase I 真实双 Host 环境变量只读探测脚本的契约测试。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests/integration/discover_phase_i_live_environment.ps1"


def _script_text() -> str:
    assert SCRIPT.is_file()
    return SCRIPT.read_text(encoding="utf-8")


def test_discovery_script_is_read_only_and_emits_copyable_commands() -> None:
    text = _script_text()
    assert "SetEnvironmentVariable" not in text
    assert "[Environment]::SetEnvironmentVariable" not in text
    assert "MANUAL_REQUIRED" in text
    assert "COPYABLE_ENV_COMMANDS" in text
    assert "'$env:{0}=''{1}'''" in text


def test_discovery_script_covers_the_complete_task16_environment_contract() -> None:
    text = _script_text()
    for name in (
        "DSP_PHASE_I_LIVE",
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


def test_discovery_script_uses_real_process_and_named_pipe_identity_rules() -> None:
    text = _script_text()
    assert "Get-Process" in text
    assert '"acad"' in text
    assert '"Revit"' in text
    assert "\\\\.\\pipe\\" in text
    assert "EnterpriseDesignAgent.$env:COMPUTERNAME-" in text
    assert "EnterpriseDesignAgent.Revit.$env:COMPUTERNAME-" in text


def test_discovery_script_hashes_only_explicit_or_existing_fixture_paths() -> None:
    text = _script_text()
    assert "AutoCadFixturePath" in text
    assert "RevitFixturePath" in text
    assert "DSP_AUTOCAD_FIXTURE_PATH" in text
    assert "DSP_REVIT_LIVE_FIXTURE_PATH" in text
    assert "Get-FileHash" in text
    assert "SHA256" in text
    assert "Test-Path" in text


def test_discovery_script_marks_unreliable_semantic_identity_as_manual() -> None:
    text = _script_text()
    for name in (
        "DSP_AUTOCAD_DOCUMENT_REF",
        "DSP_AUTOCAD_NATIVE_ID",
        "DSP_AUTOCAD_HOST_INSTANCE_ID",
        "DSP_REVIT_LIVE_DOCUMENT_REF",
        "DSP_REVIT_LIVE_WALL_UNIQUE_ID",
        "DSP_REVIT_LIVE_HOST_INSTANCE_ID",
        "DSP_PHASE_I_SEMANTIC_ID",
    ):
        assert f'Add-ManualValue -Name "{name}"' in text


def test_discovery_script_uses_powershell_elseif_for_api_directory_fallback() -> None:
    text = _script_text()
    assert "\nelif (" not in text
    assert "\nelseif (" in text
