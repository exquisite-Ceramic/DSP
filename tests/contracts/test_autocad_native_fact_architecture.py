from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "hosts" / "autocad" / "plugin" / "AutoCAD.AgentHost"
HANDLER = PLUGIN / "Commands" / "Design" / "ExtractNativeSnapshotHandler.cs"
NATIVE_API = PLUGIN / "Native" / "AutoCADNativeFactApi.cs"
REGISTRY = PLUGIN / "Commands" / "HostCommandHandler.cs"


def test_native_snapshot_read_path_exists_and_is_registered():
    assert HANDLER.is_file(), "Step 19 READ handler is missing"
    assert NATIVE_API.is_file(), "Step 19 native extractor is missing"

    handler = HANDLER.read_text(encoding="utf-8")
    registry = REGISTRY.read_text(encoding="utf-8")

    assert 'CommandType => "design.extract_native_snapshot"' in handler
    assert "AutoCADNativeFactApi.Extract" in handler
    assert "Autodesk." not in handler
    assert "Register(new Design.ExtractNativeSnapshotHandler())" in registry


def test_autodesk_sdk_usage_for_step19_is_confined_to_native_zone():
    assert HANDLER.is_file()
    assert NATIVE_API.is_file()

    handler = HANDLER.read_text(encoding="utf-8")
    native_api = NATIVE_API.read_text(encoding="utf-8")

    assert "Autodesk.AutoCAD" not in handler
    assert "Autodesk.AutoCAD" in native_api


def test_step19_extractor_has_no_step20_or_canonical_semantic_mapping():
    assert HANDLER.is_file()
    assert NATIVE_API.is_file()

    source = HANDLER.read_text(encoding="utf-8") + "\n" + NATIVE_API.read_text(encoding="utf-8")
    forbidden = (
        "A-WALL",
        "ifc:IfcWall",
        "IfcWall",
        "semantic_service",
        "semantic_runtime",
        "Metro",
        "EnterpriseSemantic",
        "SemanticId",
        "DesignFactContracts",
    )
    for token in forbidden:
        assert token not in source, f"Step 20+ semantic token leaked into Step 19 extractor: {token}"


def test_native_extractor_freezes_host_instance_revision_and_native_evidence_shape():
    assert NATIVE_API.is_file()
    source = NATIVE_API.read_text(encoding="utf-8")

    assert 'private static readonly string HostInstanceId = $"autocad-{Guid.NewGuid():N}";' in source
    assert "ActiveDocumentRevision()" in source
    assert "TryResolveObjectId" in source
    assert "GetRXClass().DxfName" in source
    assert ".Layer" in source
    assert "GeometricExtents" in source


def test_handler_is_read_only_and_delegates_native_access():
    assert HANDLER.is_file()
    source = HANDLER.read_text(encoding="utf-8")

    assert '"READ"' in source
    assert "DocumentLockManager.Acquire" in source
    assert "AutoCADNativeFactApi.Extract" in source
    assert "JsonSerializer.SerializeToElement" in source
