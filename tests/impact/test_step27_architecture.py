from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
IMPACT_ROOT = REPO_ROOT / "platform" / "impact" / "src" / "design_impact"


def test_step27_impact_package_exists_as_standalone_boundary() -> None:
    assert IMPACT_ROOT.is_dir(), "Step27 design_impact package does not exist yet"


def test_step27_core_has_no_host_or_execution_dependency_leaks() -> None:
    assert IMPACT_ROOT.is_dir(), "Step27 design_impact package does not exist yet"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(IMPACT_ROOT.glob("*.py"))
    )

    forbidden = (
        "AutoCAD",
        "Revit",
        "Tekla",
        "HostCommand",
        "ChangeSetBuilder",
        "ProviderBinding",
        "ExecutionGrant",
        "platform.changeset",
        "from changeset",
        "import changeset",
    )
    for token in forbidden:
        assert token not in source, f"Step27 impact core leaked forbidden boundary token: {token}"


def test_step27_public_contract_source_has_no_native_identifier_fields() -> None:
    contracts = IMPACT_ROOT / "contracts.py"
    assert contracts.exists(), "Step27 contracts.py does not exist yet"
    source = contracts.read_text(encoding="utf-8").lower()

    forbidden_field_fragments = (
        "handle:",
        "element_id:",
        "provider_tool:",
        "native_id:",
        "object_id:",
    )
    for token in forbidden_field_fragments:
        assert token not in source, f"provider/native identifier leaked into public impact contract: {token}"
