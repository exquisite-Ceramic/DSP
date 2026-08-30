"""Thin provider-neutral composition facade for Step33 execution reconciliation."""

from __future__ import annotations

from design_approval_scope import ApprovalScopeBoundary
from design_changeset import CanonicalChangeSet
from design_execution_planning import ExecutionPlan
from design_gateway_authorization import AdmittedExecutionAuthority

from .compensation import (
    CompensationExecutionRef,
    CompensationProposal,
    CompensationProposalRequest,
    ExecutionSagaPlanner,
)
from .contracts import (
    ActualDelta,
    ReconciliationError,
    ScopeComparisonRequest,
    ScopeComparisonResult,
    SemanticVerificationRequest,
    SemanticVerificationResult,
)
from .saga import ExecutionSagaBuilder
from .saga_state import StoredExecutionSaga
from .scope_comparator import ScopeComparator
from .store_protocol import ExecutionSagaStore
from .verifier import SemanticVerifier


class ExecutionReconciliationService:
    """Compose Step33 pure components without hiding Host, Step32, or D5 work."""

    def __init__(
        self,
        *,
        store: ExecutionSagaStore,
        builder: ExecutionSagaBuilder | None = None,
        scope_comparator: ScopeComparator | None = None,
        verifier: SemanticVerifier | None = None,
        compensation_planner: ExecutionSagaPlanner | None = None,
    ) -> None:
        self._store = store
        self._builder = builder or ExecutionSagaBuilder()
        self._scope_comparator = scope_comparator or ScopeComparator()
        self._verifier = verifier or SemanticVerifier()
        self._compensation_planner = compensation_planner or ExecutionSagaPlanner(store)

    def create_saga(
        self,
        changeset: CanonicalChangeSet,
        boundary: ApprovalScopeBoundary,
        execution_plan: ExecutionPlan,
    ) -> StoredExecutionSaga:
        definition = self._builder.build(changeset, boundary, execution_plan)
        return self._store.create_saga(definition)

    def get_saga(self, saga_id: str) -> StoredExecutionSaga | None:
        return self._store.get_saga(saga_id)

    def reserve_slice_admission(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        reserved_at: str,
    ) -> StoredExecutionSaga:
        return self._store.reserve_slice_admission(
            saga_id,
            execution_slice_hash,
            expected_revision=expected_revision,
            reserved_at=reserved_at,
        )

    def confirm_slice_admitted(
        self,
        saga_id: str,
        authority: AdmittedExecutionAuthority,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga:
        return self._store.confirm_slice_admitted(
            saga_id,
            authority,
            expected_revision=expected_revision,
        )

    def record_host_commit(
        self,
        saga_id: str,
        actual_delta: ActualDelta,
        *,
        expected_revision: int,
        committed_at: str,
    ) -> StoredExecutionSaga:
        return self._store.record_host_commit(
            saga_id,
            actual_delta,
            expected_revision=expected_revision,
            committed_at=committed_at,
        )

    def begin_reconciliation(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga:
        return self._store.begin_reconciliation(
            saga_id,
            execution_slice_hash,
            expected_revision=expected_revision,
        )

    def compare_scope(self, request: ScopeComparisonRequest) -> ScopeComparisonResult:
        return self._scope_comparator.compare(request)

    def record_scope_result(
        self,
        saga_id: str,
        result: ScopeComparisonResult,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga:
        return self._store.record_scope_result(
            saga_id,
            result,
            expected_revision=expected_revision,
        )

    def verify_semantics(
        self,
        saga_id: str,
        execution_slice_hash: str,
        request: SemanticVerificationRequest,
    ) -> SemanticVerificationResult:
        stored = self._store.get_saga(saga_id)
        if stored is None:
            raise ReconciliationError("SAGA_NOT_FOUND", "execution Saga was not found")
        if request.admitted_execution_authority.execution_slice_hash != execution_slice_hash:
            raise ReconciliationError(
                "SAGA_INTEGRITY_INVALID",
                "verification authority does not match the requested Slice",
            )

        assignments = tuple(
            assignment
            for assignment in stored.definition.slice_validation_assignments
            if assignment.execution_slice_hash == execution_slice_hash
        )
        if len(assignments) != 1:
            raise ReconciliationError(
                "SAGA_INTEGRITY_INVALID",
                "Slice validation assignment is unresolved",
            )
        expected_task_ids = assignments[0].validation_task_ids
        actual_task_ids = tuple(
            task.validation_task_id for task in request.validation_tasks
        )
        if actual_task_ids != expected_task_ids:
            raise ReconciliationError(
                "SAGA_INTEGRITY_INVALID",
                "verification must cover exactly the tasks assigned to this Slice",
            )
        return self._verifier.verify(request)

    def record_verification_result(
        self,
        saga_id: str,
        result: SemanticVerificationResult,
        *,
        expected_revision: int,
        reconciled_at: str,
    ) -> StoredExecutionSaga:
        return self._store.record_verification_result(
            saga_id,
            result,
            expected_revision=expected_revision,
            reconciled_at=reconciled_at,
        )

    def fail_slice_before_commit(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        failed_at: str,
    ) -> StoredExecutionSaga:
        return self._store.fail_slice_before_commit(
            saga_id,
            execution_slice_hash,
            expected_revision=expected_revision,
            failed_at=failed_at,
        )

    def create_compensation_proposal(
        self,
        request: CompensationProposalRequest,
    ) -> CompensationProposal:
        return self._compensation_planner.create_compensation_proposal(request)

    def begin_compensation(
        self,
        saga_id: str,
        proposal: CompensationProposal,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga:
        return self._store.begin_compensation(
            saga_id,
            proposal,
            expected_revision=expected_revision,
        )

    def record_compensation_result(
        self,
        saga_id: str,
        execution_ref: CompensationExecutionRef,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga:
        return self._store.record_compensation_result(
            saga_id,
            execution_ref,
            expected_revision=expected_revision,
        )


__all__ = ["ExecutionReconciliationService"]
