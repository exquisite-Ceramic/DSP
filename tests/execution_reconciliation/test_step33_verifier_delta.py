"""Task7 second RED: baseline delta verification and canonical numeric tolerance."""

from __future__ import annotations

from dataclasses import replace

import design_execution_reconciliation as reconciliation
from design_approval_scope import CanonicalAspect
from design_changeset import canonical_hash
from semantic_runtime import Coverage, SemanticSnapshot, SnapshotKind
from test_step33_verifier import _contract, _projection, _request, _subject, _verify


def _rehash_bundle(bundle):
    draft = replace(bundle, evidence_bundle_hash="0" * 64)
    return replace(
        draft,
        evidence_bundle_hash=reconciliation.compute_verification_evidence_bundle_hash(draft),
    )


def _with_baseline(
    transaction,
    *,
    x=10.0,
    thickness=0.25,
    snapshot_id=None,
    snapshot_hash=None,
    projection=None,
):
    planning = transaction.canonical_changeset.planning_snapshot_ref

    def mutate(bundle):
        baseline_projection = projection or _projection("BASELINE")
        baseline_snapshot = SemanticSnapshot(
            snapshot_id=planning.snapshot_id if snapshot_id is None else snapshot_id,
            kind=SnapshotKind.PLANNING,
            project_id=bundle.post_execution_snapshot_ref.project_id,
            freshness_contract_id="FC-STEP33-BASELINE",
            freshness_contract_hash=canonical_hash({"freshness": "baseline"}),
            document_ref=planning.document_ref,
            base_host_revision="10",
            coverage=Coverage(planning.document_ref, ("WALL-001",)),
            projection_ref=baseline_projection,
            semantic_environment_ref=bundle.semantic_environment_ref,
            aspect_guarantees=(),
            hash=planning.snapshot_hash if snapshot_hash is None else snapshot_hash,
        )
        baseline_subject = reconciliation.VerificationSubjectEvidence(
            semantic_id="WALL-001",
            canonical_kind="ifc:IfcWall",
            properties={"thickness": thickness},
            placement={} if x is None else {"x": x},
            geometry_evidence=None,
            relationships=(),
            constraints=(),
            classification=("ifc:IfcWall",),
            evidence_aspects=(
                CanonicalAspect.PLACEMENT,
                CanonicalAspect.PROPERTIES,
            ),
            snapshot_id=baseline_snapshot.snapshot_id,
            snapshot_hash=baseline_snapshot.hash,
            projection_ref=baseline_projection,
        )
        return _rehash_bundle(
            replace(
                bundle,
                baseline_snapshot_ref=baseline_snapshot,
                baseline_projection_ref=baseline_projection,
                baseline_subject_evidence=(baseline_subject,),
            )
        )

    return mutate


def test_delta_equals_argument_passes_with_exact_planning_baseline(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {
            "subjects": {"from_argument": "targets"},
            "path": "placement.x",
            "operator": "DELTA_EQUALS_ARGUMENT",
            "argument": "dx",
        }
    )
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        arguments={"targets": ["WALL-001"], "dx": 5.0},
        bundle_mutator=_with_baseline(step33_single_slice_transaction, x=10.0),
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.PASSED
    assert result.task_results[0].failure_codes == ()


def test_delta_missing_baseline_is_insufficient(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {
            "subjects": {"from_argument": "targets"},
            "path": "placement.x",
            "operator": "DELTA_EQUALS_ARGUMENT",
            "argument": "dx",
        }
    )
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        arguments={"targets": ["WALL-001"], "dx": 5.0},
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.EVIDENCE_INSUFFICIENT
    assert result.task_results[0].failure_codes == ("REQUIRED_BASELINE_MISSING",)


def test_delta_wrong_baseline_snapshot_identity_is_insufficient(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {
            "subjects": {"from_argument": "targets"},
            "path": "placement.x",
            "operator": "DELTA_EQUALS_ARGUMENT",
            "argument": "dx",
        }
    )
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        arguments={"targets": ["WALL-001"], "dx": 5.0},
        bundle_mutator=_with_baseline(
            step33_single_slice_transaction,
            x=10.0,
            snapshot_id="PS-WRONG-BASELINE",
        ),
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.EVIDENCE_INSUFFICIENT
    assert result.task_results[0].failure_codes == ("REQUIRED_BASELINE_MISSING",)


def test_delta_missing_baseline_subject_path_is_insufficient(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {
            "subjects": {"from_argument": "targets"},
            "path": "placement.x",
            "operator": "DELTA_EQUALS_ARGUMENT",
            "argument": "dx",
        }
    )
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        arguments={"targets": ["WALL-001"], "dx": 5.0},
        bundle_mutator=_with_baseline(step33_single_slice_transaction, x=None),
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.EVIDENCE_INSUFFICIENT
    assert result.task_results[0].failure_codes == ("REQUIRED_BASELINE_MISSING",)


def test_absolute_numeric_tolerance_passes_inside_bound(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {
            "subjects": {"from_argument": "targets"},
            "path": "properties.thickness",
            "operator": "EQUALS_ARGUMENT",
            "argument": "thickness",
            "tolerance": {"absolute": 0.001},
        }
    )

    def subject_for_bundle(bundle):
        evidence = _subject(
            bundle.post_execution_snapshot_ref,
            bundle.post_execution_projection_ref,
            thickness=0.3004,
        )
        return _rehash_bundle(replace(bundle, subject_evidence=(evidence,)))

    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        arguments={"targets": ["WALL-001"], "thickness": 0.3},
        bundle_mutator=subject_for_bundle,
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.PASSED


def test_absolute_numeric_tolerance_fails_outside_bound(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {
            "subjects": {"from_argument": "targets"},
            "path": "properties.thickness",
            "operator": "EQUALS_ARGUMENT",
            "argument": "thickness",
            "tolerance": {"absolute": 0.001},
        }
    )

    def subject_for_bundle(bundle):
        evidence = _subject(
            bundle.post_execution_snapshot_ref,
            bundle.post_execution_projection_ref,
            thickness=0.302,
        )
        return _rehash_bundle(replace(bundle, subject_evidence=(evidence,)))

    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        arguments={"targets": ["WALL-001"], "thickness": 0.3},
        bundle_mutator=subject_for_bundle,
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.FAILED
    assert result.task_results[0].failure_codes == ("EXPECTED_VALUE_MISMATCH",)


def test_tolerance_with_matching_explicit_units_passes_without_conversion(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {
            "subjects": {"from_argument": "targets"},
            "path": "properties.thickness",
            "operator": "EQUALS_ARGUMENT",
            "argument": "thickness",
            "tolerance": {"absolute": 0.001, "unit": "m"},
        }
    )

    def subject_for_bundle(bundle):
        evidence = _subject(
            bundle.post_execution_snapshot_ref,
            bundle.post_execution_projection_ref,
            thickness={"value": 0.3004, "unit": "m"},
        )
        return _rehash_bundle(replace(bundle, subject_evidence=(evidence,)))

    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        arguments={
            "targets": ["WALL-001"],
            "thickness": {"value": 0.3, "unit": "m"},
        },
        bundle_mutator=subject_for_bundle,
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.PASSED


def test_tolerance_unit_mismatch_is_insufficient_not_converted(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {
            "subjects": {"from_argument": "targets"},
            "path": "properties.thickness",
            "operator": "EQUALS_ARGUMENT",
            "argument": "thickness",
            "tolerance": {"absolute": 1.0, "unit": "mm"},
        }
    )

    def subject_for_bundle(bundle):
        evidence = _subject(
            bundle.post_execution_snapshot_ref,
            bundle.post_execution_projection_ref,
            thickness={"value": 0.3, "unit": "m"},
        )
        return _rehash_bundle(replace(bundle, subject_evidence=(evidence,)))

    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        arguments={
            "targets": ["WALL-001"],
            "thickness": {"value": 300.0, "unit": "mm"},
        },
        bundle_mutator=subject_for_bundle,
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.EVIDENCE_INSUFFICIENT
