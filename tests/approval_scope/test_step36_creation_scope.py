import pytest

from design_approval_scope import (
    CanonicalCreationContract,
    CanonicalEffectEvidence,
    CanonicalExistenceEffect,
)


def _creation_contract() -> CanonicalCreationContract:
    return CanonicalCreationContract(
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )


def test_create_only_canonical_effect_evidence_allows_empty_aspects() -> None:
    evidence = CanonicalEffectEvidence(
        canonical_operation="offset.v1",
        canonical_operation_version="1.0.0",
        allowed_aspects=(),
        allowed_existence_effects=("CREATE", CanonicalExistenceEffect.CREATE),
        creation_contract=_creation_contract(),
    )

    assert evidence.allowed_aspects == ()
    assert evidence.allowed_existence_effects == (CanonicalExistenceEffect.CREATE,)
    assert evidence.creation_contract == _creation_contract()


def test_canonical_effect_evidence_rejects_empty_authority() -> None:
    with pytest.raises(ValueError, match="effect authority"):
        CanonicalEffectEvidence(
            canonical_operation="offset.v1",
            canonical_operation_version="1.0.0",
            allowed_aspects=(),
        )
