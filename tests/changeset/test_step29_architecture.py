from __future__ import annotations

from dataclasses import is_dataclass
from pathlib import Path

import design_changeset
from design_changeset import ChangeSetBuildRequest, DerivedOperationMaterialization


ROOT = Path(__file__).resolve().parents[2]
CHANGESET_ROOT = ROOT / "platform" / "changeset" / "src"
CANONICAL_ROOT = CHANGESET_ROOT / "design_changeset"
LEGACY_ROOT = CHANGESET_ROOT / "changeset"


def test_legacy_phase2_changeset_placeholder_is_removed() -> None:
    legacy_files = (
        LEGACY_ROOT / "model.py",
        LEGACY_ROOT / "builder.py",
        LEGACY_ROOT / "execution_slice.py",
        LEGACY_ROOT / "execution_unit.py",
        LEGACY_ROOT / "verification.py",
    )
    assert all(not path.exists() for path in legacy_files)


def test_step29_production_has_no_host_provider_or_later_runtime_leakage() -> None:
    forbidden = (
        "host_contracts",
        "HostCommand",
        "ProviderBinding",
        "provider_tool",
        "native_id",
        "AutoCAD",
        "Revit",
        "Tekla",
        "ApprovalRecord",
        "ExecutionGrant",
        "PolicySnapshot",
        "ExecutionSlice",
        "ExecutionUnit",
        "ActualDelta",
        "VerificationReport",
    )
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(CANONICAL_ROOT.glob("*.py"))
    )
    for marker in forbidden:
        assert marker not in production


def test_public_api_is_explicit_and_builder_inputs_cannot_self_authorize() -> None:
    assert isinstance(design_changeset.__all__, list)
    assert len(design_changeset.__all__) == len(set(design_changeset.__all__))
    assert set(design_changeset.__all__) == {
        name for name in design_changeset.__all__ if not name.startswith("_")
    }

    request_fields = set(ChangeSetBuildRequest.__dataclass_fields__)
    derived_fields = set(DerivedOperationMaterialization.__dataclass_fields__)
    assert {"expected_effects", "changeset_hash", "changeset_id"}.isdisjoint(request_fields)
    assert "expected_effects" not in derived_fields

    for name in (
        "CanonicalOperationContractEvidence",
        "BoundOperationEvidence",
        "ApprovalScopeDefinitionRef",
        "OperationSourceEvidence",
        "CanonicalChangeOperation",
        "DerivedOperationMaterialization",
        "ChangeDependency",
        "ChangePrecondition",
        "SemanticImpactEvidence",
        "ValidationTask",
        "CanonicalChangeSet",
        "ChangeSetBuildRequest",
    ):
        value = getattr(design_changeset, name)
        assert is_dataclass(value)
        assert value.__dataclass_params__.frozen is True
