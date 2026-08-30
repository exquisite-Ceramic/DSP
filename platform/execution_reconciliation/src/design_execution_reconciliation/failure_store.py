"""Task10 failure and compensation transitions layered over the Task9 CAS store."""

from __future__ import annotations

from dataclasses import replace

from .compensation import (
    CompensationExecutionRef,
    CompensationProposal,
    CompensationProposalRequest,
    ExecutionSagaPlanner,
    validate_compensation_proposal_integrity,
)
from .contracts import (
    ReconciliationError,
    ScopeComparisonResult,
    ScopeComparisonStatus,
    SemanticVerificationResult,
    VerificationStatus,
)
from .hashing import (
    compute_scope_comparison_hash,
    compute_semantic_verification_hash,
    compute_validation_task_result_hash,
)
from .saga_state import (
    ExecutionSagaStatus,
    SliceReconciliationState,
    SliceReconciliationStatus,
    StoredExecutionSaga,
)
from .store import InMemoryExecutionSagaStore as _Task9ExecutionSagaStore
from .store import (
    _assignment_task_ids,
    _state_index,
)

_FAILURE_SLICE_STATUSES = frozenset(
    {
        SliceReconciliationStatus.FAILED_BEFORE_COMMIT,
        SliceReconciliationStatus.SCOPE_BREACH,
        SliceReconciliationStatus.VERIFY_FAILED,
    }
)


def _error(code: str, message: str) -> None:
    raise ReconciliationError(code, message)


def _blocked_after(
    stored: StoredExecutionSaga,
    failed_index: int,
    failed_state: SliceReconciliationState,
) -> tuple[SliceReconciliationState, ...]:
    states = list(stored.slice_states)
    states[failed_index] = failed_state
    for index in range(failed_index + 1, len(states)):
        if states[index].status is SliceReconciliationStatus.NOT_STARTED:
            states[index] = replace(
                states[index],
                status=SliceReconciliationStatus.BLOCKED,
            )
    return tuple(states)


def _rebuild(
    stored: StoredExecutionSaga,
    *,
    status: ExecutionSagaStatus,
    slice_states: tuple[SliceReconciliationState, ...] | None = None,
    compensation_refs: tuple[str, ...] | None = None,
    compensation_proposal_hash: str | None = None,
    compensating_changeset_hash: str | None = None,
    compensation_succeeded: bool | None = None,
    compensation_completed_at: str | None = None,
) -> StoredExecutionSaga:
    return StoredExecutionSaga(
        definition=stored.definition,
        saga_revision=stored.saga_revision + 1,
        status=status,
        slice_states=stored.slice_states if slice_states is None else slice_states,
        compensation_refs=(
            stored.compensation_refs
            if compensation_refs is None
            else compensation_refs
        ),
        compensation_proposal_hash=(
            stored.compensation_proposal_hash
            if compensation_proposal_hash is None
            else compensation_proposal_hash
        ),
        compensating_changeset_hash=(
            stored.compensating_changeset_hash
            if compensating_changeset_hash is None
            else compensating_changeset_hash
        ),
        compensation_succeeded=(
            stored.compensation_succeeded
            if compensation_succeeded is None
            else compensation_succeeded
        ),
        compensation_completed_at=(
            stored.compensation_completed_at
            if compensation_completed_at is None
            else compensation_completed_at
        ),
    )


class InMemoryExecutionSagaStore(_Task9ExecutionSagaStore):
    """Task9 CAS store extended with atomic failure and compensation truth."""

    def fail_slice_before_commit(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        failed_at: str,
    ) -> StoredExecutionSaga:
        with self._lock:
            stored = self._get_required(saga_id)
            index = _state_index(stored, execution_slice_hash)
            state = stored.slice_states[index]

            if state.status is SliceReconciliationStatus.FAILED_BEFORE_COMMIT:
                if state.failed_at == failed_at:
                    return stored
                _error("SAGA_CONFLICT", "pre-commit failure evidence differs")

            self._require_cas(stored, expected_revision)
            if state.status not in {
                SliceReconciliationStatus.ADMISSION_RESERVED,
                SliceReconciliationStatus.ADMITTED,
            }:
                _error(
                    "SAGA_CONFLICT",
                    "Slice can fail-before-commit only before Host commit",
                )
            if state.actual_delta_hash is not None:
                _error(
                    "SAGA_CONFLICT",
                    "Slice with Host commit evidence cannot fail-before-commit",
                )

            failed_state = replace(
                state,
                status=SliceReconciliationStatus.FAILED_BEFORE_COMMIT,
                failed_at=failed_at,
            )
            states = _blocked_after(stored, index, failed_state)
            prior_committed = any(
                item.actual_delta_hash is not None for item in stored.slice_states[:index]
            )
            final_status = (
                ExecutionSagaStatus.PARTIALLY_COMMITTED
                if prior_committed
                else ExecutionSagaStatus.FAILED
            )
            result = _rebuild(stored, status=final_status, slice_states=states)
            self._sagas[saga_id] = result
            return result

    def record_scope_result(
        self,
        saga_id: str,
        result: ScopeComparisonResult,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga:
        if not isinstance(result, ScopeComparisonResult):
            raise TypeError("result must be ScopeComparisonResult")
        if result.comparison_hash != compute_scope_comparison_hash(result):
            _error("SAGA_INTEGRITY_INVALID", "scope comparison hash is invalid")

        with self._lock:
            stored = self._get_required(saga_id)
            index = _state_index(stored, result.execution_slice_hash)
            state = stored.slice_states[index]

            if state.scope_comparison_hash is not None:
                if state.scope_comparison_hash == result.comparison_hash:
                    return stored
                _error("SAGA_CONFLICT", "scope comparison evidence differs")

            self._require_cas(stored, expected_revision)
            if state.status is not SliceReconciliationStatus.RECONCILING:
                _error("SAGA_CONFLICT", "Slice is not reconciling")
            if (
                result.actual_delta_hash != state.actual_delta_hash
                or result.approved_scope_hash != stored.definition.approved_scope_hash
            ):
                _error(
                    "SAGA_INTEGRITY_INVALID",
                    "scope result does not join committed Slice evidence",
                )

            if result.status is ScopeComparisonStatus.WITHIN_SCOPE:
                states = list(stored.slice_states)
                states[index] = replace(
                    state,
                    scope_comparison_hash=result.comparison_hash,
                )
                updated = _rebuild(
                    stored,
                    status=stored.status,
                    slice_states=tuple(states),
                )
            else:
                failed_state = replace(
                    state,
                    status=SliceReconciliationStatus.SCOPE_BREACH,
                    scope_comparison_hash=result.comparison_hash,
                )
                updated = _rebuild(
                    stored,
                    status=ExecutionSagaStatus.PARTIALLY_COMMITTED,
                    slice_states=_blocked_after(stored, index, failed_state),
                )
            self._sagas[saga_id] = updated
            return updated

    def record_verification_result(
        self,
        saga_id: str,
        result: SemanticVerificationResult,
        *,
        expected_revision: int,
        reconciled_at: str,
    ) -> StoredExecutionSaga:
        if not isinstance(result, SemanticVerificationResult):
            raise TypeError("result must be SemanticVerificationResult")
        if result.verification_hash != compute_semantic_verification_hash(result):
            _error("SAGA_INTEGRITY_INVALID", "semantic verification hash is invalid")
        for task_result in result.task_results:
            if task_result.task_result_hash != compute_validation_task_result_hash(task_result):
                _error("SAGA_INTEGRITY_INVALID", "validation task result hash is invalid")

        with self._lock:
            stored = self._get_required(saga_id)
            index = _state_index(stored, result.execution_slice_hash)
            state = stored.slice_states[index]

            if state.verification_hash is not None:
                if (
                    state.verification_hash == result.verification_hash
                    and state.reconciled_at == reconciled_at
                ):
                    return stored
                _error("SAGA_CONFLICT", "semantic verification evidence differs")

            self._require_cas(stored, expected_revision)
            if state.status is not SliceReconciliationStatus.RECONCILING:
                _error("SAGA_CONFLICT", "Slice is not reconciling")
            if state.scope_comparison_hash is None:
                _error(
                    "SAGA_CONFLICT",
                    "semantic verification cannot finalize before WITHIN_SCOPE is persisted",
                )
            if (
                result.changeset_hash != stored.definition.changeset_hash
                or result.actual_delta_hash != state.actual_delta_hash
            ):
                _error(
                    "SAGA_INTEGRITY_INVALID",
                    "verification result does not join committed Saga evidence",
                )

            expected_tasks = _assignment_task_ids(
                stored.definition,
                result.execution_slice_hash,
            )
            actual_tasks = tuple(item.validation_task_id for item in result.task_results)
            if actual_tasks != expected_tasks:
                _error(
                    "SAGA_INTEGRITY_INVALID",
                    "verification must cover exactly the tasks assigned to this Slice",
                )

            all_tasks_passed = all(
                item.status is VerificationStatus.PASSED for item in result.task_results
            )
            if result.status is VerificationStatus.PASSED:
                if not all_tasks_passed:
                    _error(
                        "SAGA_INTEGRITY_INVALID",
                        "PASSED verification contains a non-PASSED task result",
                    )
                succeeded_state = replace(
                    state,
                    status=SliceReconciliationStatus.SUCCEEDED,
                    verification_hash=result.verification_hash,
                    reconciled_at=reconciled_at,
                )
                states = list(stored.slice_states)
                states[index] = succeeded_state
                all_succeeded = all(
                    item.status is SliceReconciliationStatus.SUCCEEDED for item in states
                )
                final_status = (
                    ExecutionSagaStatus.SUCCEEDED
                    if all_succeeded
                    else ExecutionSagaStatus.EXECUTING
                )
                updated = _rebuild(
                    stored,
                    status=final_status,
                    slice_states=tuple(states),
                )
            else:
                failed_state = replace(
                    state,
                    status=SliceReconciliationStatus.VERIFY_FAILED,
                    verification_hash=result.verification_hash,
                    reconciled_at=reconciled_at,
                )
                updated = _rebuild(
                    stored,
                    status=ExecutionSagaStatus.PARTIALLY_COMMITTED,
                    slice_states=_blocked_after(stored, index, failed_state),
                )

            self._sagas[saga_id] = updated
            return updated

    def begin_compensation(
        self,
        saga_id: str,
        proposal: CompensationProposal,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga:
        if not isinstance(proposal, CompensationProposal):
            raise TypeError("proposal must be CompensationProposal")
        with self._lock:
            stored = self._get_required(saga_id)
            if stored.compensation_proposal_hash is not None:
                if (
                    stored.compensation_proposal_hash == proposal.proposal_hash
                    and stored.status is ExecutionSagaStatus.COMPENSATING
                ):
                    return stored
                _error("COMPENSATION_CONFLICT", "compensation proposal evidence differs")

            self._require_cas(stored, expected_revision)
            if stored.status is not ExecutionSagaStatus.PARTIALLY_COMMITTED:
                _error(
                    "COMPENSATION_CONFLICT",
                    "only a PARTIALLY_COMMITTED Saga can begin compensation",
                )
            validate_compensation_proposal_integrity(proposal)
            if (
                proposal.source_saga_id != stored.definition.saga_id
                or proposal.source_changeset_hash != stored.definition.changeset_hash
            ):
                _error(
                    "COMPENSATION_CONFLICT",
                    "proposal does not join the durable source Saga",
                )

            expected = ExecutionSagaPlanner(self).create_compensation_proposal(
                CompensationProposalRequest(
                    source_saga_id=proposal.source_saga_id,
                    failed_slice_hash=proposal.failed_slice_hash,
                    desired_recovery_effects=proposal.desired_recovery_effects,
                )
            )
            if expected != proposal:
                _error(
                    "COMPENSATION_CONFLICT",
                    "proposal does not match durable Saga failure evidence",
                )

            refs = tuple(sorted({*stored.compensation_refs, proposal.proposal_hash}))
            updated = _rebuild(
                stored,
                status=ExecutionSagaStatus.COMPENSATING,
                compensation_refs=refs,
                compensation_proposal_hash=proposal.proposal_hash,
            )
            self._sagas[saga_id] = updated
            return updated

    def record_compensation_result(
        self,
        saga_id: str,
        execution_ref: CompensationExecutionRef,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga:
        if not isinstance(execution_ref, CompensationExecutionRef):
            raise TypeError("execution_ref must be CompensationExecutionRef")
        with self._lock:
            stored = self._get_required(saga_id)

            if stored.compensating_changeset_hash is not None:
                if (
                    stored.compensation_proposal_hash
                    == execution_ref.compensation_proposal_hash
                    and stored.compensating_changeset_hash
                    == execution_ref.compensating_changeset_hash
                    and stored.compensation_succeeded is execution_ref.succeeded
                    and stored.compensation_completed_at == execution_ref.completed_at
                ):
                    return stored
                _error("COMPENSATION_CONFLICT", "compensation result evidence differs")

            self._require_cas(stored, expected_revision)
            if stored.status is not ExecutionSagaStatus.COMPENSATING:
                _error("COMPENSATION_CONFLICT", "Saga is not compensating")
            if (
                stored.compensation_proposal_hash
                != execution_ref.compensation_proposal_hash
            ):
                _error(
                    "COMPENSATION_CONFLICT",
                    "compensation result does not join the active proposal",
                )

            final_status = (
                ExecutionSagaStatus.COMPENSATED
                if execution_ref.succeeded
                else ExecutionSagaStatus.COMPENSATION_FAILED
            )
            refs = tuple(
                sorted(
                    {
                        *stored.compensation_refs,
                        execution_ref.compensating_changeset_hash,
                    }
                )
            )
            updated = _rebuild(
                stored,
                status=final_status,
                compensation_refs=refs,
                compensation_proposal_hash=execution_ref.compensation_proposal_hash,
                compensating_changeset_hash=execution_ref.compensating_changeset_hash,
                compensation_succeeded=execution_ref.succeeded,
                compensation_completed_at=execution_ref.completed_at,
            )
            self._sagas[saga_id] = updated
            return updated


__all__ = ["InMemoryExecutionSagaStore"]
