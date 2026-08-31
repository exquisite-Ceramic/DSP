from __future__ import annotations

from pathlib import Path

import pytest

from design_approval_scope import CanonicalAspect
from design_orchestrator.canonical_operations import OFFSET_V1

_ROOT = Path(__file__).parents[2]

_CORE_ROOTS = (
    _ROOT / "platform/orchestrator/src/design_orchestrator",
    _ROOT / "platform/impact/src/design_impact",
    _ROOT / "platform/approval_scope/src/design_approval_scope",
    _ROOT / "platform/changeset/src/design_changeset",
    _ROOT / "platform/execution_planning/src/design_execution_planning",
)


def _python_source_under(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.py"))
    )


def test_create_remains_separate_from_canonical_aspects() -> None:
    with pytest.raises(ValueError):
        CanonicalAspect("CREATE")


def test_offset_canonical_contract_remains_provider_neutral() -> None:
    assert OFFSET_V1.canonical_operation == "offset.v1"
    assert OFFSET_V1.canonical_entity_constraints == ("ifc:IfcWall",)

    canonical_repr = repr(OFFSET_V1)
    assert "LWPOLYLINE" not in canonical_repr
    assert "GetOffsetCurves" not in canonical_repr
    assert "handles" not in canonical_repr


def test_core_authority_and_planning_sources_exclude_autocad_native_mechanics() -> None:
    forbidden = (
        "Autodesk.AutoCAD",
        "GetOffsetCurves",
        "LWPOLYLINE",
    )

    for root in _CORE_ROOTS:
        source = _python_source_under(root)
        for token in forbidden:
            assert token not in source, f"{token} leaked into provider-neutral core: {root}"


def test_autocad_provider_and_host_own_native_offset_details() -> None:
    provider_source = (
        _ROOT / "hosts/autocad/sidecar/src/autocad_sidecar/mcp_server.py"
    ).read_text(encoding="utf-8")
    host_source = (
        _ROOT
        / "hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADEntityApi.cs"
    ).read_text(encoding="utf-8")

    assert 'operation="offset.v1"' in provider_source
    assert 'entities=["LWPOLYLINE"]' in provider_source
    assert "GetOffsetCurves" in host_source
