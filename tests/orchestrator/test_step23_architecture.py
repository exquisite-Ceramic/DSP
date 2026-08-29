from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "platform/orchestrator/src/design_orchestrator/canonical_operations.py"
ORCHESTRATOR_PRODUCTION = ROOT / "platform/orchestrator/src/design_orchestrator"


def test_canonical_action_module_has_no_host_or_provider_specific_routing() -> None:
    text = CANONICAL.read_text(encoding="utf-8").lower()
    for forbidden in (
        "cad.move",
        "handles",
        "elementid",
        "autocad.sidecar",
        "autocad_sidecar",
        "revit",
    ):
        assert forbidden not in text


def test_canonical_action_module_does_not_import_host_or_semantic_provider_packages() -> None:
    text = CANONICAL.read_text(encoding="utf-8")
    for forbidden in (
        "autocad_sidecar",
        "semantic_service",
        "ifc43_provider",
        "metro_v32_provider",
        "enterprise_mapping_provider",
    ):
        assert forbidden not in text


def test_step23_does_not_add_execution_binding_production_modules() -> None:
    production_files = tuple(ORCHESTRATOR_PRODUCTION.glob("*.py"))
    names = {path.name for path in production_files}
    assert "provider_binding.py" not in names
    assert "host_command_builder.py" not in names
    assert "slot_binder.py" not in names
