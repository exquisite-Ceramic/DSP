"""Task6 RED tests for immutable snapshot-bound verification evidence."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import design_execution_reconciliation as reconciliation
import pytest
from design_approval_scope import CanonicalAspect
from design_changeset import canonical_hash
from semantic_runtime import (
    Coverage,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotKind,
)

_ZERO_HASH = canonical_hash({"placeholder": "step33-verification-evidence"})
_CHANGESET_HASH = canonical_hash({"changeset": "step33-task6"})
_SLICE_HASH = canonical_hash({"slice": "step33-task6"})
_DELTA_HASH = canonical_hash({"delta": "step33-task6"})


def _projection(label: str) -> SemanticProjectionRef:
    return SemanticProjectionRef(
        projection_id=f"PROJ-{label}",
        projection_hash=canonical_hash({"projection": label}),
        semantic_model_version="ifc43+metro-v32",
        provider_set_hash=canonical_hash({"providers": label}),
        mapping_profile_set_hash=canonical_hash({"mappings": label}),
        normalized_fact_batch_hash=canonical_hash({"facts": label}),
    )


def _environment(label: str = "VERIFY") -> SemanticEnvironmentRef:
    return SemanticEnvironmentRef(
        environment_id=f"ENV-{label}",
        content_hash=canonical_hash({"environment": label}),
    )


def _snapshot(
    label: str,
    *,
    projection_ref: SemanticProjectionRef,
    semantic_environment_ref: SemanticEnvironmentRef,
    revision: str,
) -> SemanticSnapshot:
    return SemanticSnapshot(
        snapshot_id=f"PS-{label}",
        kind=SnapshotKind.PLANNING,
        project_id="PROJECT-STEP33",
        freshness_contract_id=f"FC-{label}",
        freshness_contract_hash=canonical_hash({"freshness": label}),
        document_ref="DOC-1",
        base_host_revision=revision,
        coverage=Coverage("DOC-1", ("WALL-001", "WALL-002")),
        projection_ref=projection_ref,
        semantic_environment_ref=semantic_environment_ref,
        aspect_guarantees=(),
        hash=canonical_hash({"snapshot": label, "revision": revision}),
    )


def _contract(label: str):
    body = {
        "type": "SEMANTIC_ASSERTIONS_V1",
        "version": "1.0.0",
        "assertions": [
            {
                "subjects": {"from_argument": "targets"},
                "path": f"properties.{label}",
                "operator": "EXISTS",
            }
        ],
    }
    return reconciliation.VerificationContractEvidence(
        canonical_hash(body),
        body,
    )


def _subject(
    semantic_id: str,
    *,
    snapshot: SemanticSnapshot,
    projection_ref: SemanticProjectionRef,
    thickness: float,
):
    return reconciliation.VerificationSubjectEvidence(
        semantic_id=semantic_id,
        canonical_kind="ifc:IfcWall",
        properties={
            "thickness": {"value": thickness, "unit": "m"},
            "nested": {"bands": [1, 2]},
        },
        placement={"x": 10.0, "frame": {"origin": [0.0, 0.0, 0.0]}},
        geometry_evidence={"bounds": {"min": [0, 0, 0], "max": [1, 1, 1]}},
        relationships=(
            {"type": "HOSTED_BY", "target": "STOREY-001", "meta": {"rank": 1}},
        ),
        constraints=(
            {"type": "MIN_CLEARANCE", "value": {"amount": 0.1, "unit": "m"}},
        ),
        classification=("metro:Wall", "ifc:IfcWall"),
        evidence_aspects=(
            CanonicalAspect.CLASSIFICATION,
            CanonicalAspect.PROPERTIES,
            CanonicalAspect.RELATIONSHIPS,
        ),
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.hash,
        projection_ref=projection_ref,
    )


def _unsigned_bundle(
    *,
    post_projection: SemanticProjectionRef | None = None,
    post_snapshot: SemanticSnapshot | None = None,
    baseline_projection: SemanticProjectionRef | None = None,
    baseline_snapshot: SemanticSnapshot | None = None,
    contract_evidence=None,
    subject_evidence=None,
    baseline_subject_evidence=None,
):
    environment = _environment()
    post_projection = post_projection or _projection("POST")
    post_snapshot = post_snapshot or _snapshot(
        "POST",
        projection_ref=post_projection,
        semantic_environment_ref=environment,
        revision="12",
    )
    baseline_projection = baseline_projection or _projection("BASE")
    baseline_snapshot = baseline_snapshot or _snapshot(
        "BASE",
        projection_ref=baseline_projection,
        semantic_environment_ref=environment,
        revision="11",
    )
    contract_evidence = (
        (_contract("thickness"), _contract("height"))
        if contract_evidence is None
        else tuple(contract_evidence)
    )
    subject_evidence = (
        (
            _subject(
                "WALL-001",
                snapshot=post_snapshot,
                projection_ref=post_projection,
                thickness=0.3,
            ),
            _subject(
                "WALL-002",
                snapshot=post_snapshot,
                projection_ref=post_projection,
                thickness=0.2,
            ),
        )
        if subject_evidence is None
        else tuple(subject_evidence)
    )
    baseline_subject_evidence = (
        (
            _subject(
                "WALL-001",
                snapshot=baseline_snapshot,
                projection_ref=baseline_projection,
                thickness=0.25,
            ),
        )
        if baseline_subject_evidence is None
        else tuple(baseline_subject_evidence)
    )
    return reconciliation.VerificationEvidenceBundle(
        evidence_bundle_id="VEB-STEP33-TASK6",
        changeset_hash=_CHANGESET_HASH,
        execution_slice_hash=_SLICE_HASH,
        actual_delta_hash=_DELTA_HASH,
        semantic_environment_ref=environment,
        post_execution_snapshot_ref=post_snapshot,
        post_execution_projection_ref=post_projection,
        base_host_revision="12",
        baseline_snapshot_ref=baseline_snapshot,
        baseline_projection_ref=baseline_projection,
        contract_evidence=contract_evidence,
        subject_evidence=subject_evidence,
        baseline_subject_evidence=baseline_subject_evidence,
        evidence_bundle_hash=_ZERO_HASH,
    )


def _signed_bundle(**overrides):
    unsigned = _unsigned_bundle(**overrides)
    return replace(
        unsigned,
        evidence_bundle_hash=reconciliation.compute_verification_evidence_bundle_hash(
            unsigned
        ),
    )


def test_contract_body_hash_must_equal_contract_ref() -> None:
    good = _contract("thickness")
    tampered = reconciliation.VerificationContractEvidence(
        good.contract_ref,
        {
            "type": "SEMANTIC_ASSERTIONS_V1",
            "version": "1.0.0",
            "assertions": [{"operator": "NOT_EXISTS"}],
        },
    )
    bundle = _signed_bundle(contract_evidence=(tampered,))

    with pytest.raises(reconciliation.ReconciliationError) as exc_info:
        reconciliation.validate_verification_evidence_bundle_integrity(bundle)

    assert exc_info.value.code == "VERIFY_CONTRACT_MISMATCH"


def test_duplicate_contract_ref_with_different_body_is_mismatch() -> None:
    first = _contract("thickness")
    second = reconciliation.VerificationContractEvidence(
        first.contract_ref,
        {
            "type": "SEMANTIC_ASSERTIONS_V1",
            "version": "1.0.0",
            "assertions": [{"operator": "EXISTS", "path": "properties.height"}],
        },
    )
    bundle = _signed_bundle(contract_evidence=(first, second))

    with pytest.raises(reconciliation.ReconciliationError) as exc_info:
        reconciliation.validate_verification_evidence_bundle_integrity(bundle)

    assert exc_info.value.code == "VERIFY_CONTRACT_MISMATCH"


@pytest.mark.parametrize("set_name", ["subject_evidence", "baseline_subject_evidence"])
def test_subject_evidence_key_is_unique_within_each_snapshot_set(set_name: str) -> None:
    unsigned = _unsigned_bundle()
    source = getattr(unsigned, set_name)[0]
    duplicate = replace(
        source,
        properties={"thickness": {"value": 999.0, "unit": "m"}},
    )
    bundle = _signed_bundle(**{set_name: (source, duplicate)})

    with pytest.raises(reconciliation.ReconciliationError) as exc_info:
        reconciliation.validate_verification_evidence_bundle_integrity(bundle)

    assert exc_info.value.code == "VERIFY_INPUT_INVALID"


def test_evidence_mappings_are_deep_defensive_immutable_copies() -> None:
    contract_body = {
        "type": "SEMANTIC_ASSERTIONS_V1",
        "assertions": [{"path": "properties.thickness", "meta": {"required": True}}],
    }
    properties = {"nested": {"bands": [1, 2]}}
    relationship = {"type": "HOSTED_BY", "meta": {"rank": 1}}
    constraint = {"type": "MIN_CLEARANCE", "meta": {"rank": 1}}

    contract = reconciliation.VerificationContractEvidence(
        canonical_hash(contract_body),
        contract_body,
    )
    unsigned = _unsigned_bundle(contract_evidence=(contract,), subject_evidence=())
    subject = reconciliation.VerificationSubjectEvidence(
        semantic_id="WALL-IMMUTABLE",
        canonical_kind="ifc:IfcWall",
        properties=properties,
        placement=None,
        geometry_evidence=None,
        relationships=(relationship,),
        constraints=(constraint,),
        classification=("ifc:IfcWall",),
        evidence_aspects=(CanonicalAspect.PROPERTIES,),
        snapshot_id=unsigned.post_execution_snapshot_ref.snapshot_id,
        snapshot_hash=unsigned.post_execution_snapshot_ref.hash,
        projection_ref=unsigned.post_execution_projection_ref,
    )

    contract_body["assertions"][0]["meta"]["required"] = False
    properties["nested"]["bands"].append(3)
    relationship["meta"]["rank"] = 9
    constraint["meta"]["rank"] = 9

    assert contract.contract_body["assertions"][0]["meta"]["required"] is True
    assert subject.properties["nested"]["bands"] == (1, 2)
    assert subject.relationships[0]["meta"]["rank"] == 1
    assert subject.constraints[0]["meta"]["rank"] == 1
    assert isinstance(contract.contract_body, MappingProxyType)
    assert isinstance(subject.properties, MappingProxyType)
    assert isinstance(subject.properties["nested"], MappingProxyType)
    assert isinstance(subject.relationships[0]["meta"], MappingProxyType)
    assert isinstance(subject.constraints[0]["meta"], MappingProxyType)

    with pytest.raises(TypeError):
        subject.properties["nested"]["other"] = 1


def test_bundle_hash_is_order_independent_for_contracts_and_subjects() -> None:
    first = _unsigned_bundle()
    second = _unsigned_bundle(
        contract_evidence=tuple(reversed(first.contract_evidence)),
        subject_evidence=tuple(reversed(first.subject_evidence)),
        baseline_subject_evidence=tuple(reversed(first.baseline_subject_evidence)),
    )

    first_hash = reconciliation.compute_verification_evidence_bundle_hash(first)
    second_hash = reconciliation.compute_verification_evidence_bundle_hash(second)

    assert second.contract_evidence == first.contract_evidence
    assert second.subject_evidence == first.subject_evidence
    assert second.baseline_subject_evidence == first.baseline_subject_evidence
    assert second_hash == first_hash


def test_bundle_hash_changes_with_post_snapshot_projection_or_subject_evidence() -> None:
    base = _unsigned_bundle()
    environment = base.semantic_environment_ref
    changed_projection = _projection("POST-CHANGED")
    changed_snapshot = _snapshot(
        "POST-CHANGED",
        projection_ref=base.post_execution_projection_ref,
        semantic_environment_ref=environment,
        revision="12",
    )
    changed_subject = replace(
        base.subject_evidence[0],
        properties={"thickness": {"value": 0.31, "unit": "m"}},
    )

    hashes = {
        reconciliation.compute_verification_evidence_bundle_hash(base),
        reconciliation.compute_verification_evidence_bundle_hash(
            replace(base, post_execution_projection_ref=changed_projection)
        ),
        reconciliation.compute_verification_evidence_bundle_hash(
            replace(base, post_execution_snapshot_ref=changed_snapshot)
        ),
        reconciliation.compute_verification_evidence_bundle_hash(
            replace(base, subject_evidence=(changed_subject, base.subject_evidence[1]))
        ),
    }

    assert len(hashes) == 4


def test_bundle_hash_changes_with_baseline_snapshot_projection_or_evidence() -> None:
    base = _unsigned_bundle()
    environment = base.semantic_environment_ref
    changed_projection = _projection("BASE-CHANGED")
    changed_snapshot = _snapshot(
        "BASE-CHANGED",
        projection_ref=base.baseline_projection_ref,
        semantic_environment_ref=environment,
        revision="11",
    )
    changed_subject = replace(
        base.baseline_subject_evidence[0],
        properties={"thickness": {"value": 0.24, "unit": "m"}},
    )

    hashes = {
        reconciliation.compute_verification_evidence_bundle_hash(base),
        reconciliation.compute_verification_evidence_bundle_hash(
            replace(base, baseline_projection_ref=changed_projection)
        ),
        reconciliation.compute_verification_evidence_bundle_hash(
            replace(base, baseline_snapshot_ref=changed_snapshot)
        ),
        reconciliation.compute_verification_evidence_bundle_hash(
            replace(base, baseline_subject_evidence=(changed_subject,))
        ),
    }

    assert len(hashes) == 4


def test_valid_signed_bundle_passes_intrinsic_integrity() -> None:
    bundle = _signed_bundle()

    reconciliation.validate_verification_evidence_bundle_integrity(bundle)

    assert bundle.evidence_bundle_hash == reconciliation.compute_verification_evidence_bundle_hash(
        bundle
    )
