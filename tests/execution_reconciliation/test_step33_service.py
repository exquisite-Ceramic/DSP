"""Task11 RED: public Step33 reconciliation facade and omission barrier."""

from __future__ import annotations

import design_execution_reconciliation as reconciliation
import pytest
from design_changeset import canonical_hash
from semantic_runtime import (
    Coverage,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotKind,
)


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
    assignment = next(
        item
        for item in saga.definition.slice_validation_assignments
        if item.execution_slice_hash == step33_admitted_authority.execution_slice_hash
    )
    tasks_by_id = {
        task.validation_task_id: task
        for task in transaction.canonical_changeset.validation_tasks
    }
    request = _verification_request(
        transaction,
        step33_admitted_authority,
        delta,
        tuple(tasks_by_id[task_id] for task_id in assignment.validation_task_ids),
    )

    result = service.verify_semantics(
        saga.definition.saga_id,
        step33_admitted_authority.execution_slice_hash,
        request,
    )

    assert result is marker
    assert spy.requests == [request]


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
