from __future__ import annotations

import importlib
from dataclasses import FrozenInstanceError

import pytest


def test_step29_public_package_exposes_frozen_contracts() -> None:
    module = importlib.import_module("design_changeset")

    assert hasattr(module, "__all__")
    assert "CanonicalOperationContractEvidence" in module.__all__
    assert "BoundOperationEvidence" in module.__all__
    assert "CanonicalChangeSet" in module.__all__
    assert "ChangeSetBuildRequest" in module.__all__

    evidence = module.CanonicalOperationContractEvidence(
        canonical_operation="move.v1",
        canonical_operation_version="1.0.0",
        argument_schema={"type": "object"},
        effects=("PLACEMENT", "GEOMETRY"),
        verification_contract={"type": "HOST_READ_BACK"},
        definition_fingerprint="a" * 64,
    )

    with pytest.raises(FrozenInstanceError):
        evidence.canonical_operation = "other.v1"


def test_derived_materialization_cannot_supply_expected_effects() -> None:
    module = importlib.import_module("design_changeset")
    assert "expected_effects" not in module.DerivedOperationMaterialization.__dataclass_fields__


def test_build_request_cannot_supply_identity_hashes() -> None:
    module = importlib.import_module("design_changeset")
    fields = module.ChangeSetBuildRequest.__dataclass_fields__
    assert "changeset_hash" not in fields
    assert "changeset_id" not in fields
