"""Phase I 真实双 Host identity 只读探测契约。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tests/integration/probe_phase_i_live_identity.py"
DISCOVERY = ROOT / "tests/integration/discover_phase_i_live_environment.ps1"
REVIT_CONTEXT = (
    ROOT
    / "hosts/revit/plugin/Revit.AgentHost/Native/Context/RevitContextIdentityReader.cs"
)
REVIT_HANDLER = (
    ROOT
    / "hosts/revit/plugin/Revit.AgentHost/Native/ExternalEvents/RevitExternalEventHandler.cs"
)
REVIT_ROUTER = (
    ROOT
    / "hosts/revit/plugin/Revit.AgentHost/Native/ExternalEvents/RevitRequestExecutorRouter.cs"
)


def test_python_probe_reuses_read_only_autocad_context_and_fact_paths() -> None:
    assert PROBE.is_file()
    text = PROBE.read_text(encoding="utf-8")
    assert "current_document" in text
    assert "current_selection" in text
    assert "extract_design_facts" in text
    assert "DSP_AUTOCAD_DOCUMENT_REF" in text
    assert "DSP_AUTOCAD_NATIVE_ID" in text
    assert "DSP_AUTOCAD_HOST_INSTANCE_ID" in text
    assert "set_wall_thickness(" not in text


def test_python_probe_reads_revit_context_without_mutation() -> None:
    assert PROBE.is_file()
    text = PROBE.read_text(encoding="utf-8")
    assert 'operation="context.current_selection"' in text
    assert 'mode="READ"' in text
    assert "DSP_REVIT_LIVE_DOCUMENT_REF" in text
    assert "DSP_REVIT_LIVE_WALL_UNIQUE_ID" in text
    assert "DSP_REVIT_LIVE_HOST_INSTANCE_ID" in text


def test_revit_context_operation_returns_real_document_runtime_and_unique_id() -> None:
    assert REVIT_CONTEXT.is_file()
    text = REVIT_CONTEXT.read_text(encoding="utf-8")
    assert '"context.current_selection"' in text
    assert "uiDocument.Selection.GetElementIds()" in text
    assert ".UniqueId" in text
    assert ".PathName" in text
    assert '"revit-"' in text or '$"revit-' in text
    assert "Transaction" not in text


def test_revit_external_event_routes_ui_document_to_read_only_context_operation() -> None:
    handler = REVIT_HANDLER.read_text(encoding="utf-8")
    router = REVIT_ROUTER.read_text(encoding="utf-8")
    assert "UIDocument" in handler
    assert "executor.Execute(" in handler
    assert "uiDocument" in handler
    assert "RevitContextIdentityReader" in router
    assert "RevitContextIdentityReader.Operation" in router


def test_environment_discovery_consumes_identity_probe_and_stays_read_only() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")
    assert "probe_phase_i_live_identity.py" in text
    assert "DSP_AUTOCAD_DOCUMENT_REF" in text
    assert "DSP_AUTOCAD_NATIVE_ID" in text
    assert "DSP_AUTOCAD_HOST_INSTANCE_ID" in text
    assert "DSP_REVIT_LIVE_DOCUMENT_REF" in text
    assert "DSP_REVIT_LIVE_WALL_UNIQUE_ID" in text
    assert "DSP_REVIT_LIVE_HOST_INSTANCE_ID" in text
    assert "SetEnvironmentVariable" not in text
