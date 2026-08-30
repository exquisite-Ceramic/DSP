"""Task11 RED: public Step33 reconciliation facade and cross-step integration."""

from __future__ import annotations

from dataclasses import replace

import design_execution_reconciliation as reconciliation
import pytest
from design_approval_scope import CanonicalAspect
from design_changeset import canonical_hash
from design_gateway_authorization import AdmittedExecutionAuthority
from semantic_runtime import (
    Coverage,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotKind,
)

_HAPPY_CONTRACT = {
    "type": "SEMANTIC_ASSERTIONS_V1",
    "version": "1.0.0",
    "assertions": [
        {
            "subjects": {"from_argument": "targets"},
            "path": "properties.thickness",
            "operator": "EQUALS_LITERAL",
            "value": 300.0,
        }
    ],
}


def _service(*, verifier=None):
    return reconciliation.ExecutionReconciliationService(
        store=reconciliation.InMemoryExecutionSagaStore(),
        verifier=verifier,
    )


def _slice_state(stored, slice_hash):
    return next(
        state
        for state in stored.slice_states
        if state.execution_slice_hash == slice_hash
    )


def _execution_slice(transaction, slice_hash):
    return next(
        item
        for item in transaction.execution_plan.execution_slices
        if item.execution_slice_hash == slice_hash
    )


def _assigned_tasks(stored, transaction, slice_hash):
    assignment = next(
        item
        for item in stored.definition.slice_validation_assignments
        if item.execution_slice_hash == slice_hash
    )
    tasks_by_id = {
        task.validation_task_id: task
        for task in transaction.canonical_changeset.validation_tasks
    }
    return tuple(tasks_by_id[task_id] for task_id in assignment.validation_task_ids)


def _dummy_bundle(transaction, authority, delta):
    changeset = transaction.canonical_changeset
    environment = SemanticEnvironmentRef(
        changeset.semantic_environment_ref.environment_id,
        changeset.semantic_environment_ref.content_hash,
    )
    projection = SemanticProjectionRef(
        projection_id="PROJ-TASK11-DUMMY",
        projection_hash=canonical_hash({"task11": "projection"}),
        semantic_model_version="task11-test",
        provider_set_hash=canonical_hash({"task11": "providers"}),
        mapping_profile_set_hash=canonical_hash({"task11": "mappings"}),
        normalized_fact_batch_hash=canonical_hash({"task11": "facts"}),
    )
    snapshot = SemanticSnapshot(
        snapshot_id="PS-TASK11-DUMMY",
        kind=SnapshotKind.PLANNING,
        project_id=changeset.project_id,
        freshness_contract_id="FC-TASK11-DUMMY",
        freshness_contract_hash=canonical_hash({"task11": "freshness"}),
        document_ref=delta.document_ref,
        base_host_revision=str(delta.revision_after),
        coverage=Coverage(delta.document_ref, ("WALL-001",)),
        projection_ref=projection,
        semantic_environment_ref=environment,
        aspect_guarantees=(),
        hash=canonical_hash({"task11": "snapshot"}),
    )
    return reconciliation.VerificationEvidenceBundle(
        evidence_bundle_id="VEB-TASK11-DUMMY",
        changeset_hash=changeset.changeset_hash,
        execution_slice_hash=authority.execution_slice_hash,
        actual_delta_hash=delta.actual_delta_hash,
        semantic_environment_ref=environment,
        post_execution_snapshot_ref=snapshot,
        post_execution_projection_ref=projection,
        base_host_revision=str(delta.revision_after),
        baseline_snapshot_ref=None,
        baseline_projection_ref=None,
        contract_evidence=(),
        subject_evidence=(),
        baseline_subject_evidence=(),
        evidence_bundle_hash="0" * 64,
    )


def _signed_happy_bundle(transaction, authority, delta):
    changeset = transaction.canonical_changeset
    environment = SemanticEnvironmentRef(
        changeset.semantic_environment_ref.environment_id,
        changeset.semantic_environment_ref.content_hash,
    )
    projection = SemanticProjectionRef(
        projection_id="PROJ-TASK11-HAPPY",
        projection_hash=canonical_hash({"task11": "happy-projection"}),
        semantic_model_version="ifc43+metro-v32",
        provider_set_hash=canonical_hash({"task11": "happy-providers"}),
        mapping_profile_set_hash=canonical_hash({"task11": "happy-mappings"}),
        normalized_fact_batch_hash=canonical_hash({"task11": "happy-facts"}),
    )
    snapshot = SemanticSnapshot(
        snapshot_id="PS-TASK11-HAPPY",
        kind=SnapshotKind.PLANNING,
        project_id=changeset.project_id,
        freshness_contract_id="FC-TASK11-HAPPY",
        freshness_contract_hash=canonical_hash({"task11": "happy-freshness"}),
        document_ref=delta.document_ref,
        base_host_revision=str(delta.revision_after),
        coverage=Coverage(delta.document_ref, ("WALL-001",)),
        projection_ref=projection,
        semantic_environment_ref=environment,
        aspect_guarantees=(),
        hash=canonical_hash(
            {"task11": "happy-snapshot", "delta": delta.actual_delta_hash}
        ),
    )
    subject = reconciliation.VerificationSubjectEvidence(
        semantic_id="WALL-001",
        canonical_kind="ifc:IfcWall",
        properties={"thickness": 300.0},
        placement=None,
        geometry_evidence=None,
        relationships=(),
        constraints=(),
        classification=("ifc:IfcWall",),
        evidence_aspects=(CanonicalAspect.PROPERTIES,),
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.hash,
        projection_ref=projection,
    )
    draft = reconciliation.VerificationEvidenceBundle(
        evidence_bundle_id="VEB-TASK11-HAPPY",
        changeset_hash=changeset.changeset_hash,
        execution_slice_hash=authority.execution_slice_hash,
        actual_delta_hash=delta.actual_delta_hash,
        semantic_environment_ref=environment,
        post_execution_snapshot_ref=snapshot,
        post_execution_projection_ref=projection,
        base_host_revision=str(delta.revision_after),
        baseline_snapshot_ref=None,
        baseline_projection_ref=None,
        contract_evidence=(
            reconciliation.VerificationContractEvidence(
                contract_ref=canonical_hash(_HAPPY_CONTRACT),
                contract_body=_HAPPY_CONTRACT,
            ),
        ),
        subject_evidence=(subject,),
        baseline_subject_evidence=(),
        evidence_bundle_hash="0" * 64,
    )
    return replace(
        draft,
        evidence_bundle_hash=reconciliation.compute_verification_evidence_bundle_hash(
            draft
        ),
    )


def _verification_request(transaction, authority, delta, tasks):
    return reconciliation.SemanticVerificationRequest(
        admitted_execution_authority=authority,
        approval_scope_boundary=transaction.approval_scope_boundary,
        canonical_changeset=transaction.canonical_changeset,
        actual_delta=delta,
        validation_tasks=tuple(tasks),
        verification_evidence_bundle=_dummy_bundle(transaction, authority, delta),
        verified_at="2026-08-30T16:40:00Z",
    )


def _drive_to_scope(service, transaction, authority, delta):
    execution_slice = transaction.execution_slice
    assert execution_slice is not None
    saga = service.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    saga = service.reserve_slice_admission(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=saga.saga_revision,
        reserved_at="2026-08-30T16:31:00Z",
    )
    saga = service.confirm_slice_admitted(
        saga.definition.saga_id,
        authority,
        expected_revision=saga.saga_revision,
    )
    saga = service.record_host_commit(
        saga.definition.saga_id,
        delta,
        expected_revision=saga.saga_revision,
        committed_at="2026-08-30T16:32:00Z",
    )
    saga = service.begin_reconciliation(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=saga.saga_revision,
    )
    scope_result = service.compare_scope(
        reconciliation.ScopeComparisonRequest(
            admitted_execution_authority=authority,
            actual_delta=delta,
            approval_scope_boundary=transaction.approval_scope_boundary,
            execution_slice=execution_slice,
        )
    )
    saga = service.record_scope_result(
        saga.definition.saga_id,
        scope_result,
        expected_revision=saga.saga_revision,
    )
    return saga, scope_result


def _manual_authority(transaction, slice_hash, marker):
    execution_slice = _execution_slice(transaction, slice_hash)
    return AdmittedExecutionAuthority(
        approval_hash=marker * 64,
        grant_hash=("a" if marker == "1" else "b") * 64,
        changeset_hash=transaction.canonical_changeset.changeset_hash,
        approved_scope_hash=transaction.approval_scope_boundary.scope_hash,
        execution_slice_hash=slice_hash,
        binding_set_hash=("c" if marker == "1" else "d") * 64,
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
        admitted_at=f"2026-08-30T17:0{marker}:00Z",
    )


def _signed_delta_for_slice(transaction, authority, *changes, marker):
    execution_slice = _execution_slice(transaction, authority.execution_slice_hash)
    draft = reconciliation.ActualDelta(
        actual_delta_id=f"AD-TASK11-{marker}",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=authority.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=30,
        revision_after=31,
        changes=tuple(changes),
        actual_delta_hash="0" * 64,
    )
    return replace(
        draft,
        actual_delta_hash=reconciliation.compute_actual_delta_hash(draft),
    )


def _passed_verification(transaction, stored, slice_hash, delta_hash):
    assignment = next(
        item
        for item in stored.definition.slice_validation_assignments
        if item.execution_slice_hash == slice_hash
    )
    task_results = []
    for task_id in assignment.validation_task_ids:
        draft_task = reconciliation.ValidationTaskResult(
            validation_task_id=task_id,
            status=reconciliation.VerificationStatus.PASSED,
            observations=("Task11 service integration pass",),
            failure_codes=(),
            task_result_hash="0" * 64,
        )
        task_results.append(
            replace(
                draft_task,
                task_result_hash=reconciliation.compute_validation_task_result_hash(
                    draft_task
                ),
            )
        )
    draft = reconciliation.SemanticVerificationResult(
        verification_id=f"VR-TASK11-{slice_hash[:12]}",
        changeset_hash=transaction.canonical_changeset.changeset_hash,
        execution_slice_hash=slice_hash,
        actual_delta_hash=delta_hash,
        evidence_bundle_hash="e" * 64,
        task_results=tuple(task_results),
        status=reconciliation.VerificationStatus.PASSED,
        verification_hash="0" * 64,
    )
    return replace(
        draft,
        verification_hash=reconciliation.compute_semantic_verification_hash(draft),
    )


def test_facade_exposes_only_explicit_reconciliation_composition_methods() -> None:
    service = _service()

    for method_name in (
        "create_saga",
        "reserve_slice_admission",
        "confirm_slice_admitted",
        "record_host_commit",
        "begin_reconciliation",
        "compare_scope",
        "record_scope_result",
        "verify_semantics",
        "record_verification_result",
        "fail_slice_before_commit",
        "create_compensation_proposal",
        "begin_compensation",
        "record_compensation_result",
        "get_saga",
    ):
        assert hasattr(service, method_name)

    for forbidden_name in (
        "execute_host",
        "admit_execution_grant",
        "reconstruct_semantics",
        "create_compensating_changeset",
        "native_undo",
    ):
        assert not hasattr(service, forbidden_name)


def test_facade_composes_builder_store_and_scope_without_hiding_host_execution(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_delta,
) -> None:
    transaction = step33_single_slice_transaction
    service = _service()
    delta = step33_signed_actual_delta()

    saga, scope_result = _drive_to_scope(
        service,
        transaction,
        step33_admitted_authority,
        delta,
    )

    assert scope_result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    state = _slice_state(saga, step33_admitted_authority.execution_slice_hash)
    assert state.status is reconciliation.SliceReconciliationStatus.RECONCILING
    assert state.actual_delta_hash == delta.actual_delta_hash
    assert state.scope_comparison_hash == scope_result.comparison_hash
    assert service.get_saga(saga.definition.saga_id) == saga


def test_verify_semantics_rejects_caller_task_omission_before_verifier(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_delta,
) -> None:
    class NeverCalledVerifier:
        def verify(self, request):  # pragma: no cover - omission must stop earlier.
            raise AssertionError("SemanticVerifier must not run for omitted Saga tasks")

    transaction = step33_single_slice_transaction
    service = _service(verifier=NeverCalledVerifier())
    delta = step33_signed_actual_delta()
    saga, _ = _drive_to_scope(service, transaction, step33_admitted_authority, delta)
    request = _verification_request(transaction, step33_admitted_authority, delta, ())

    with pytest.raises(reconciliation.ReconciliationError) as exc_info:
        service.verify_semantics(
            saga.definition.saga_id,
            step33_admitted_authority.execution_slice_hash,
            request,
        )

    assert exc_info.value.code == "SAGA_INTEGRITY_INVALID"


def test_verify_semantics_delegates_only_exact_assigned_tasks(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_delta,
) -> None:
    marker = object()

    class SpyVerifier:
        def __init__(self) -> None:
            self.requests = []

        def verify(self, request):
            self.requests.append(request)
            return marker

    transaction = step33_single_slice_transaction
    spy = SpyVerifier()
    service = _service(verifier=spy)
    delta = step33_signed_actual_delta()
    saga, _ = _drive_to_scope(service, transaction, step33_admitted_authority, delta)
    request = _verification_request(
        transaction,
        step33_admitted_authority,
        delta,
        _assigned_tasks(
            saga,
            transaction,
            step33_admitted_authority.execution_slice_hash,
        ),
    )

    result = service.verify_semantics(
        saga.definition.saga_id,
        step33_admitted_authority.execution_slice_hash,
        request,
    )

    assert result is marker
    assert spy.requests == [request]


def test_complete_single_slice_path_uses_real_authority_scope_and_verifier(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    transaction = step33_single_slice_transaction
    authority = step33_admitted_authority
    execution_slice = transaction.execution_slice
    assert execution_slice is not None
    service = _service()
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        canonical_kind="ifc:IfcWall",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    delta = step33_signed_actual_delta(change)

    saga, scope_result = _drive_to_scope(service, transaction, authority, delta)
    tasks = _assigned_tasks(saga, transaction, execution_slice.execution_slice_hash)
    bundle = _signed_happy_bundle(transaction, authority, delta)
    request = reconciliation.SemanticVerificationRequest(
        admitted_execution_authority=authority,
        approval_scope_boundary=transaction.approval_scope_boundary,
        canonical_changeset=transaction.canonical_changeset,
        actual_delta=delta,
        validation_tasks=tasks,
        verification_evidence_bundle=bundle,
        verified_at="2026-08-30T17:20:00Z",
    )

    verification = service.verify_semantics(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        request,
    )
    final = service.record_verification_result(
        saga.definition.saga_id,
        verification,
        expected_revision=saga.saga_revision,
        reconciled_at="2026-08-30T17:21:00Z",
    )

    assert scope_result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    assert verification.status is reconciliation.VerificationStatus.PASSED
    assert verification.changeset_hash == authority.changeset_hash
    assert verification.execution_slice_hash == authority.execution_slice_hash
    assert verification.actual_delta_hash == delta.actual_delta_hash
    assert verification.evidence_bundle_hash == bundle.evidence_bundle_hash
    assert final.status is reconciliation.ExecutionSagaStatus.SUCCEEDED
    state = _slice_state(final, execution_slice.execution_slice_hash)
    assert state.status is reconciliation.SliceReconciliationStatus.SUCCEEDED
    assert state.scope_comparison_hash == scope_result.comparison_hash
    assert state.verification_hash == verification.verification_hash


def test_two_slice_partial_failure_seals_compensation_proposal(
    step33_two_slice_transaction,
    step33_signed_actual_change,
) -> None:
    transaction = step33_two_slice_transaction
    service = _service()
    saga = service.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    first, second = saga.definition.ordered_slice_hashes

    authority_a = _manual_authority(transaction, first, "1")
    delta_a = _signed_delta_for_slice(transaction, authority_a, marker="A")
    saga = service.reserve_slice_admission(
        saga.definition.saga_id,
        first,
        expected_revision=saga.saga_revision,
        reserved_at="2026-08-30T17:30:00Z",
    )
    saga = service.confirm_slice_admitted(
        saga.definition.saga_id,
        authority_a,
        expected_revision=saga.saga_revision,
    )
    saga = service.record_host_commit(
        saga.definition.saga_id,
        delta_a,
        expected_revision=saga.saga_revision,
        committed_at="2026-08-30T17:31:00Z",
    )
    saga = service.begin_reconciliation(
        saga.definition.saga_id,
        first,
        expected_revision=saga.saga_revision,
    )
    scope_a = service.compare_scope(
        reconciliation.ScopeComparisonRequest(
            authority_a,
            delta_a,
            transaction.approval_scope_boundary,
            _execution_slice(transaction, first),
        )
    )
    saga = service.record_scope_result(
        saga.definition.saga_id,
        scope_a,
        expected_revision=saga.saga_revision,
    )
    verification_a = _passed_verification(
        transaction,
        saga,
        first,
        delta_a.actual_delta_hash,
    )
    saga = service.record_verification_result(
        saga.definition.saga_id,
        verification_a,
        expected_revision=saga.saga_revision,
        reconciled_at="2026-08-30T17:32:00Z",
    )
    assert _slice_state(saga, first).status is reconciliation.SliceReconciliationStatus.SUCCEEDED

    authority_b = _manual_authority(transaction, second, "2")
    outside = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="OUTSIDE-STEP33",
        canonical_kind="ifc:IfcWall",
        changed_aspects=(CanonicalAspect.PLACEMENT,),
    )
    delta_b = _signed_delta_for_slice(
        transaction,
        authority_b,
        outside,
        marker="B",
    )
    saga = service.reserve_slice_admission(
        saga.definition.saga_id,
        second,
        expected_revision=saga.saga_revision,
        reserved_at="2026-08-30T17:33:00Z",
    )
    saga = service.confirm_slice_admitted(
        saga.definition.saga_id,
        authority_b,
        expected_revision=saga.saga_revision,
    )
    saga = service.record_host_commit(
        saga.definition.saga_id,
        delta_b,
        expected_revision=saga.saga_revision,
        committed_at="2026-08-30T17:34:00Z",
    )
    saga = service.begin_reconciliation(
        saga.definition.saga_id,
        second,
        expected_revision=saga.saga_revision,
    )
    scope_b = service.compare_scope(
        reconciliation.ScopeComparisonRequest(
            authority_b,
            delta_b,
            transaction.approval_scope_boundary,
            _execution_slice(transaction, second),
        )
    )
    saga = service.record_scope_result(
        saga.definition.saga_id,
        scope_b,
        expected_revision=saga.saga_revision,
    )
    proposal = service.create_compensation_proposal(
        reconciliation.CompensationProposalRequest(
            source_saga_id=saga.definition.saga_id,
            failed_slice_hash=second,
            desired_recovery_effects=(
                {
                    "semantic_id": "WALL-001",
                    "canonical_aspect": "PLACEMENT",
                    "desired": "restore-approved-semantic-state",
                },
            ),
        )
    )

    assert scope_b.status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH
    assert saga.status is reconciliation.ExecutionSagaStatus.PARTIALLY_COMMITTED
    assert _slice_state(saga, first).status is reconciliation.SliceReconciliationStatus.SUCCEEDED
    assert _slice_state(saga, second).status is reconciliation.SliceReconciliationStatus.SCOPE_BREACH
    assert proposal.source_saga_id == saga.definition.saga_id
    assert proposal.source_changeset_hash == transaction.canonical_changeset.changeset_hash
    assert proposal.failed_slice_hash == second
    assert proposal.actual_delta_refs == (
        delta_a.actual_delta_hash,
        delta_b.actual_delta_hash,
    )
    assert proposal.scope_breach_refs == (scope_b.comparison_hash,)


def test_service_response_loss_replays_every_evidence_mutation(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_delta,
) -> None:
    transaction = step33_single_slice_transaction
    authority = step33_admitted_authority
    execution_slice = transaction.execution_slice
    assert execution_slice is not None
    service = _service()
    delta = step33_signed_actual_delta()
    saga = service.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    assert service.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    ) == saga

    reserved = service.reserve_slice_admission(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=0,
        reserved_at="2026-08-30T17:40:00Z",
    )
    assert service.reserve_slice_admission(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=0,
        reserved_at="2026-08-30T17:40:00Z",
    ) == reserved
    with pytest.raises(reconciliation.ReconciliationError) as reserve_conflict:
        service.reserve_slice_admission(
            saga.definition.saga_id,
            execution_slice.execution_slice_hash,
            expected_revision=0,
            reserved_at="2026-08-30T17:40:01Z",
        )
    assert reserve_conflict.value.code == "SAGA_CONFLICT"

    admitted = service.confirm_slice_admitted(
        saga.definition.saga_id,
        authority,
        expected_revision=reserved.saga_revision,
    )
    assert service.confirm_slice_admitted(
        saga.definition.saga_id,
        authority,
        expected_revision=reserved.saga_revision,
    ) == admitted
    with pytest.raises(reconciliation.ReconciliationError) as admit_conflict:
        service.confirm_slice_admitted(
            saga.definition.saga_id,
            replace(authority, grant_hash="f" * 64),
            expected_revision=reserved.saga_revision,
        )
    assert admit_conflict.value.code == "SAGA_CONFLICT"

    committed = service.record_host_commit(
        saga.definition.saga_id,
        delta,
        expected_revision=admitted.saga_revision,
        committed_at="2026-08-30T17:41:00Z",
    )
    assert service.record_host_commit(
        saga.definition.saga_id,
        delta,
        expected_revision=admitted.saga_revision,
        committed_at="2026-08-30T17:41:00Z",
    ) == committed
    with pytest.raises(reconciliation.ReconciliationError) as commit_conflict:
        service.record_host_commit(
            saga.definition.saga_id,
            delta,
            expected_revision=admitted.saga_revision,
            committed_at="2026-08-30T17:41:01Z",
        )
    assert commit_conflict.value.code == "SAGA_CONFLICT"

    reconciling = service.begin_reconciliation(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=committed.saga_revision,
    )
    assert service.begin_reconciliation(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=committed.saga_revision,
    ) == reconciling

    scope = service.compare_scope(
        reconciliation.ScopeComparisonRequest(
            authority,
            delta,
            transaction.approval_scope_boundary,
            execution_slice,
        )
    )
    scoped = service.record_scope_result(
        saga.definition.saga_id,
        scope,
        expected_revision=reconciling.saga_revision,
    )
    assert service.record_scope_result(
        saga.definition.saga_id,
        scope,
        expected_revision=reconciling.saga_revision,
    ) == scoped
    different_scope_draft = reconciliation.ScopeComparisonResult(
        status=reconciliation.ScopeComparisonStatus.SCOPE_BREACH,
        actual_delta_hash=delta.actual_delta_hash,
        approved_scope_hash=transaction.approval_scope_boundary.scope_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        matched_changes=(),
        violations=(
            reconciliation.ScopeViolation(
                code="TASK11_DIFFERENT_SCOPE",
                actual_change_hash="f" * 64,
            ),
        ),
        comparison_hash="0" * 64,
    )
    different_scope = replace(
        different_scope_draft,
        comparison_hash=reconciliation.compute_scope_comparison_hash(
            different_scope_draft
        ),
    )
    with pytest.raises(reconciliation.ReconciliationError) as scope_conflict:
        service.record_scope_result(
            saga.definition.saga_id,
            different_scope,
            expected_revision=reconciling.saga_revision,
        )
    assert scope_conflict.value.code == "SAGA_CONFLICT"

    verification = _passed_verification(
        transaction,
        scoped,
        execution_slice.execution_slice_hash,
        delta.actual_delta_hash,
    )
    succeeded = service.record_verification_result(
        saga.definition.saga_id,
        verification,
        expected_revision=scoped.saga_revision,
        reconciled_at="2026-08-30T17:42:00Z",
    )
    assert service.record_verification_result(
        saga.definition.saga_id,
        verification,
        expected_revision=scoped.saga_revision,
        reconciled_at="2026-08-30T17:42:00Z",
    ) == succeeded
    with pytest.raises(reconciliation.ReconciliationError) as verify_conflict:
        service.record_verification_result(
            saga.definition.saga_id,
            verification,
            expected_revision=scoped.saga_revision,
            reconciled_at="2026-08-30T17:42:01Z",
        )
    assert verify_conflict.value.code == "SAGA_CONFLICT"


def test_facade_preserves_store_replay_and_cas_semantics(
    step33_single_slice_transaction,
) -> None:
    transaction = step33_single_slice_transaction
    execution_slice = transaction.execution_slice
    assert execution_slice is not None
    service = _service()
    saga = service.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    first = service.reserve_slice_admission(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=0,
        reserved_at="2026-08-30T16:31:00Z",
    )
    replay = service.reserve_slice_admission(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=0,
        reserved_at="2026-08-30T16:31:00Z",
    )
    assert replay == first

    with pytest.raises(reconciliation.ReconciliationError) as exc_info:
        service.reserve_slice_admission(
            saga.definition.saga_id,
            execution_slice.execution_slice_hash,
            expected_revision=0,
            reserved_at="2026-08-30T16:31:01Z",
        )
    assert exc_info.value.code == "SAGA_CONFLICT"
