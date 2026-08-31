from __future__ import annotations

import pytest
from design_approval_scope import (
    CanonicalAspect,
    CanonicalCreationContract,
    CanonicalExistenceEffect,
)
from design_changeset import (
    CanonicalChangeOperation,
    CanonicalOperationContractEvidence,
    OperationOrigin,
    OperationSourceEvidence,
    OperationSourceKind,
    canonical_hash,
    compute_contract_definition_fingerprint,
    compute_operation_semantic_hash,
)


def _creation_contract() -> CanonicalCreationContract:
    return CanonicalCreationContract(
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )


def _root_source() -> OperationSourceEvidence:
    return OperationSourceEvidence(
        source_kind=OperationSourceKind.ROOT_BOUND_OPERATION,
        source_fingerprint="1" * 64,
    )


def test_contract_evidence_accepts_create_only_authority() -> None:
    evidence = CanonicalOperationContractEvidence(
        canonical_operation="offset.v1",
        canonical_operation_version="1.0.0",
        argument_schema={"type": "object"},
        effects=(),
        verification_contract={},
        definition_fingerprint="0" * 64,
        existence_effects=("CREATE", CanonicalExistenceEffect.CREATE),
        creation_contract=_creation_contract(),
    )

    assert evidence.effects == ()
    assert evidence.existence_effects == (CanonicalExistenceEffect.CREATE,)
    assert evidence.creation_contract == _creation_contract()


def test_contract_evidence_legacy_defaults_remain_empty() -> None:
    evidence = CanonicalOperationContractEvidence(
        canonical_operation="move.v1",
        canonical_operation_version="1.0.0",
        argument_schema={"type": "object"},
        effects=(CanonicalAspect.GEOMETRY,),
        verification_contract={},
        definition_fingerprint="0" * 64,
    )

    assert evidence.existence_effects == ()
    assert evidence.creation_contract is None


def test_contract_evidence_rejects_empty_total_authority() -> None:
    with pytest.raises(ValueError):
        CanonicalOperationContractEvidence(
            canonical_operation="offset.v1",
            canonical_operation_version="1.0.0",
            argument_schema={"type": "object"},
            effects=(),
            verification_contract={},
            definition_fingerprint="0" * 64,
        )


def test_contract_evidence_rejects_creation_contract_without_create() -> None:
    with pytest.raises(ValueError):
        CanonicalOperationContractEvidence(
            canonical_operation="move.v1",
            canonical_operation_version="1.0.0",
            argument_schema={"type": "object"},
            effects=(CanonicalAspect.GEOMETRY,),
            verification_contract={},
            definition_fingerprint="0" * 64,
            creation_contract=_creation_contract(),
        )


def test_change_operation_accepts_create_only_expected_authority() -> None:
    operation = CanonicalChangeOperation(
        operation_id="COP-CREATE",
        origin=OperationOrigin.ROOT,
        canonical_operation="offset.v1",
        canonical_operation_version="1.0.0",
        canonical_definition_fingerprint="2" * 64,
        targets=("WALL-001",),
        arguments={"targets": ["WALL-001"]},
        expected_effects=(),
        scope_rule_ids=("CR-1",),
        source_evidence=_root_source(),
        expected_existence_effects=(CanonicalExistenceEffect.CREATE,),
    )

    assert operation.expected_effects == ()
    assert operation.expected_existence_effects == (CanonicalExistenceEffect.CREATE,)


def test_change_operation_rejects_empty_total_expected_authority() -> None:
    with pytest.raises(ValueError):
        CanonicalChangeOperation(
            operation_id="COP-EMPTY",
            origin=OperationOrigin.ROOT,
            canonical_operation="offset.v1",
            canonical_operation_version="1.0.0",
            canonical_definition_fingerprint="2" * 64,
            targets=("WALL-001",),
            arguments={"targets": ["WALL-001"]},
            expected_effects=(),
            scope_rule_ids=("CR-1",),
            source_evidence=_root_source(),
        )


def test_legacy_contract_fingerprint_payload_is_unchanged() -> None:
    expected_payload = {
        "canonical_operation": "move.v1",
        "canonical_operation_version": "1.0.0",
        "argument_schema": {"type": "object"},
        "effects": ["GEOMETRY"],
        "verification_contract": {},
    }

    assert compute_contract_definition_fingerprint(
        canonical_operation="move.v1",
        canonical_operation_version="1.0.0",
        argument_schema={"type": "object"},
        effects=(CanonicalAspect.GEOMETRY,),
        verification_contract={},
    ) == canonical_hash(expected_payload)


def test_contract_fingerprint_adds_nonempty_creation_authority() -> None:
    contract = _creation_contract()
    expected_payload = {
        "canonical_operation": "offset.v1",
        "canonical_operation_version": "1.0.0",
        "argument_schema": {"type": "object"},
        "effects": [],
        "verification_contract": {},
        "existence_effects": ["CREATE"],
        "creation_contract": contract,
    }

    assert compute_contract_definition_fingerprint(
        canonical_operation="offset.v1",
        canonical_operation_version="1.0.0",
        argument_schema={"type": "object"},
        effects=(),
        verification_contract={},
        existence_effects=(CanonicalExistenceEffect.CREATE,),
        creation_contract=contract,
    ) == canonical_hash(expected_payload)


def test_legacy_operation_semantic_hash_payload_is_unchanged() -> None:
    source = _root_source()
    expected_payload = {
        "origin": OperationOrigin.ROOT,
        "canonical_operation": "move.v1",
        "canonical_operation_version": "1.0.0",
        "canonical_definition_fingerprint": "2" * 64,
        "targets": ["WALL-001"],
        "arguments": {"targets": ["WALL-001"]},
        "expected_effects": ["GEOMETRY"],
        "scope_rule_fingerprints": ["3" * 64],
        "source_evidence": source,
    }

    assert compute_operation_semantic_hash(
        origin=OperationOrigin.ROOT,
        canonical_operation="move.v1",
        canonical_operation_version="1.0.0",
        canonical_definition_fingerprint="2" * 64,
        targets=("WALL-001",),
        arguments={"targets": ["WALL-001"]},
        expected_effects=(CanonicalAspect.GEOMETRY,),
        scope_rule_fingerprints=("3" * 64,),
        source_evidence=source,
    ) == canonical_hash(expected_payload)


def test_operation_semantic_hash_adds_nonempty_creation_authority() -> None:
    source = _root_source()
    expected_payload = {
        "origin": OperationOrigin.ROOT,
        "canonical_operation": "offset.v1",
        "canonical_operation_version": "1.0.0",
        "canonical_definition_fingerprint": "2" * 64,
        "targets": ["WALL-001"],
        "arguments": {"targets": ["WALL-001"]},
        "expected_effects": [],
        "scope_rule_fingerprints": ["3" * 64],
        "source_evidence": source,
        "expected_existence_effects": ["CREATE"],
    }

    assert compute_operation_semantic_hash(
        origin=OperationOrigin.ROOT,
        canonical_operation="offset.v1",
        canonical_operation_version="1.0.0",
        canonical_definition_fingerprint="2" * 64,
        targets=("WALL-001",),
        arguments={"targets": ["WALL-001"]},
        expected_effects=(),
        scope_rule_fingerprints=("3" * 64,),
        source_evidence=source,
        expected_existence_effects=(CanonicalExistenceEffect.CREATE,),
    ) == canonical_hash(expected_payload)
