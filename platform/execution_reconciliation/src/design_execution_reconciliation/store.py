"""Atomic CAS persistence for sequential Step33 execution reconciliation."""

from __future__ import annotations

from dataclasses import replace
from threading import RLock
from typing import Protocol

from design_gateway_authorization import AdmittedExecutionAuthority

from .contracts import (
    ActualDelta,
    ReconciliationError,
    ScopeComparisonResult,
    ScopeComparisonStatus,
    SemanticVerificationResult,
    VerificationStatus,
)
from .hashing import (
    compute_execution_saga_definition_hash,
    compute_scope_comparison_hash,
    compute_semantic_verification_hash,
    compute_validation_task_result_hash,
    validate_actual_delta_integrity,
)
from .saga_contracts import ExecutionSagaDefinition
from .saga_state import (
    ExecutionSagaStatus,
    SliceReconciliationState,
    SliceReconciliationStatus,
    StoredExecutionSaga,
)

_ACTIVE_SLICE_STATUSES = frozenset(
    {
        SliceReconciliationStatus.ADMISSION_RESERVED,
        SliceReconciliationStatus.ADMITTED,
        SliceReconciliationStatus.HOST_COMMITTED,
        SliceReconciliationStatus.RECONCILING,
    }
)


def _error(code: str, message: str) -> None:
    raise ReconciliationError(code, message)


def _require_revision(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _error("SAGA_CONFLICT", "expected_revision must be a non-negative integer")
    return value


def _definition_integrity(definition: ExecutionSagaDefinition) -> None:
    if not isinstance(definition, ExecutionSagaDefinition):
        raise TypeError("definition must be ExecutionSagaDefinition")
    expected_hash = compute_execution_saga_definition_hash(definition)
    if definition.saga_definition_hash != expected_hash:
        _error("SAGA_INTEGRITY_INVALID", "Saga definition body does not match its hash")
    if definition.saga_id != f"SG-{expected_hash[:12]}":
        _error("SAGA_INTEGRITY_INVALID", "Saga id does not match its definition hash")

    slice_hashes = set(definition.ordered_slice_hashes)
    assignment_hashes = {
        assignment.execution_slice_hash
        for assignment in definition.slice_validation_assignments
    }
    if assignment_hashes != slice_hashes:
        _error(
            "SAGA_INTEGRITY_INVALID",
            "Saga validation assignments must cover every Slice exactly once",
        )
    for dependency in definition.slice_dependencies:
        if (
            dependency.predecessor_slice_hash not in slice_hashes
            or dependency.successor_slice_hash not in slice_hashes
        ):
            _error(
                "SAGA_INTEGRITY_INVALID",
                "Saga dependency references a Slice outside the definition",
            )


def _state_index(stored: StoredExecutionSaga, execution_slice_hash: str) -> int:
    for index, state in enumerate(stored.slice_states):
        if state.execution_slice_hash == execution_slice_hash:
            return index
    _error("SAGA_INTEGRITY_INVALID", "execution Slice is not part of this Saga")


def _assignment_task_ids(
    definition: ExecutionSagaDefinition,
    execution_slice_hash: str,
) -> tuple[str, ...]:
    matches = tuple(
        assignment.validation_task_ids
        for assignment in definition.slice_validation_assignments
        if assignment.execution_slice_hash == execution_slice_hash
    )
    if len(matches) != 1:
        _error("SAGA_INTEGRITY_INVALID", "Slice validation assignment is unresolved")
    return matches[0]


def _with_state(
    stored: StoredExecutionSaga,
    index: int,
    state: SliceReconciliationState,
    *,
    saga_status: ExecutionSagaStatus | None = None,
) -> StoredExecutionSaga:
    states = list(stored.slice_states)
    states[index] = state
    return StoredExecutionSaga(
        definition=stored.definition,
        saga_revision=stored.saga_revision + 1,
        status=stored.status if saga_status is None else saga_status,
        slice_states=tuple(states),
        compensation_refs=stored.compensation_refs,
    )


def _authority_matches_state(
    authority: AdmittedExecutionAuthority,
    state: SliceReconciliationState,
) -> bool:
    return (
        state.approval_hash == authority.approval_hash
        and state.grant_hash == authority.grant_hash
        and state.binding_set_hash == authority.binding_set_hash
        and state.admitted_host_instance_id == authority.host_instance_id
        and state.admitted_at == authority.admitted_at
    )


class ExecutionSagaStore(Protocol):
    def create_saga(self, definition: ExecutionSagaDefinition) -> StoredExecutionSaga: ...

    def get_saga(self, saga_id: str) -> StoredExecutionSaga | None: ...

    def reserve_slice_admission(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        reserved_at: str,
    ) -> StoredExecutionSaga: ...

    def confirm_slice_admitted(
        self,
        saga_id: str,
        authority: AdmittedExecutionAuthority,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga: ...

    def record_host_commit(
        self,
        saga_id: str,
        actual_delta: ActualDelta,
        *,
        expected_revision: int,
        committed_at: str,
    ) -> StoredExecutionSaga: ...

    def begin_reconciliation(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga: ...

    def record_scope_result(
        self,
        saga_id: str,
        result: ScopeComparisonResult,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga: ...

    def record_verification_result(
        self,
        saga_id: str,
        result: SemanticVerificationResult,
        *,
        expected_revision: int,
        reconciled_at: str,
    ) -> StoredExecutionSaga: ...


class InMemoryExecutionSagaStore:
    """Thread-safe reference implementation with evidence-aware CAS replay."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sagas: dict[str, StoredExecutionSaga] = {}

    def create_saga(self, definition: ExecutionSagaDefinition) -> StoredExecutionSaga:
        if not isinstance(definition, ExecutionSagaDefinition):
            raise TypeError("definition must be ExecutionSagaDefinition")
        with self._lock:
            existing = self._sagas.get(definition.saga_id)
            if existing is not None:
                if existing.definition == definition:
                    return existing
                _error("SAGA_CONFLICT", "Saga id already binds a different definition")

            _definition_integrity(definition)
            states = tuple(
                SliceReconciliationState(
                    execution_slice_hash=slice_hash,
                    sequence_index=index,
                )
                for index, slice_hash in enumerate(definition.ordered_slice_hashes)
            )
            stored = StoredExecutionSaga(
                definition=definition,
                saga_revision=0,
                status=ExecutionSagaStatus.READY,
                slice_states=states,
            )
            self._sagas[definition.saga_id] = stored
            return stored

    def get_saga(self, saga_id: str) -> StoredExecutionSaga | None:
        if not isinstance(saga_id, str) or not saga_id.strip():
            raise ValueError("saga_id is required")
        with self._lock:
            return self._sagas.get(saga_id.strip())

    def _get_required(self, saga_id: str) -> StoredExecutionSaga:
        stored = self._sagas.get(saga_id)
        if stored is None:
            _error("SAGA_NOT_FOUND", "execution Saga was not found")
        return stored

    @staticmethod
    def _require_cas(stored: StoredExecutionSaga, expected_revision: int) -> None:
        expected = _require_revision(expected_revision)
        if stored.saga_revision != expected:
            _error(
                "SAGA_CONFLICT",
                "Saga revision changed before the requested transition",
            )

    @staticmethod
    def _require_no_other_active(
        stored: StoredExecutionSaga,
        execution_slice_hash: str,
    ) -> None:
        for state in stored.slice_states:
            if (
                state.execution_slice_hash != execution_slice_hash
                and state.status in _ACTIVE_SLICE_STATUSES
            ):
                _error("SAGA_CONFLICT", "another Slice is already active")

    @staticmethod
    def _require_next_eligible(
        stored: StoredExecutionSaga,
        execution_slice_hash: str,
    ) -> None:
        predecessors: dict[str, set[str]] = {
            slice_hash: set() for slice_hash in stored.definition.ordered_slice_hashes
        }
        for dependency in stored.definition.slice_dependencies:
            predecessors[dependency.successor_slice_hash].add(
                dependency.predecessor_slice_hash
            )
        status_by_hash = {
            state.execution_slice_hash: state.status for state in stored.slice_states
        }
        eligible = tuple(
            state.execution_slice_hash
            for state in stored.slice_states
            if state.status is SliceReconciliationStatus.NOT_STARTED
            and all(
                status_by_hash[pred] is SliceReconciliationStatus.SUCCEEDED
                for pred in predecessors[state.execution_slice_hash]
            )
        )
        if not eligible or execution_slice_hash != eligible[0]:
            _error(
                "SAGA_CONFLICT",
                "Slice is not the lowest canonical eligible admission candidate",
            )

    def reserve_slice_admission(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        reserved_at: str,
    ) -> StoredExecutionSaga:
        with self._lock:
            stored = self._get_required(saga_id)
            index = _state_index(stored, execution_slice_hash)
            state = stored.slice_states[index]

            if state.reserved_at is not None:
                if state.reserved_at == reserved_at:
                    return stored
                _error("SAGA_CONFLICT", "Slice reservation evidence differs")

            self._require_cas(stored, expected_revision)
            if stored.status in {
                ExecutionSagaStatus.SUCCEEDED,
                ExecutionSagaStatus.COMPENSATED,
                ExecutionSagaStatus.COMPENSATION_FAILED,
                ExecutionSagaStatus.FAILED,
            }:
                _error("SAGA_CONFLICT", "terminal Saga cannot reserve a Slice")
            self._require_no_other_active(stored, execution_slice_hash)
            self._require_next_eligible(stored, execution_slice_hash)
            if state.status is not SliceReconciliationStatus.NOT_STARTED:
                _error("SAGA_CONFLICT", "Slice is not available for admission reservation")

            updated = replace(
                state,
                status=SliceReconciliationStatus.ADMISSION_RESERVED,
                reserved_at=reserved_at,
            )
            result = _with_state(
                stored,
                index,
                updated,
                saga_status=ExecutionSagaStatus.EXECUTING,
            )
            self._sagas[saga_id] = result
            return result

    def confirm_slice_admitted(
        self,
        saga_id: str,
        authority: AdmittedExecutionAuthority,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga:
        if not isinstance(authority, AdmittedExecutionAuthority):
            raise TypeError("authority must be AdmittedExecutionAuthority")
        with self._lock:
            stored = self._get_required(saga_id)
            index = _state_index(stored, authority.execution_slice_hash)
            state = stored.slice_states[index]

            if state.grant_hash is not None:
                if _authority_matches_state(authority, state):
                    return stored
                _error("SAGA_CONFLICT", "Slice admission evidence differs")

            self._require_cas(stored, expected_revision)
            if state.status is not SliceReconciliationStatus.ADMISSION_RESERVED:
                _error("SAGA_CONFLICT", "Slice has no active admission reservation")
            if (
                authority.changeset_hash != stored.definition.changeset_hash
                or authority.approved_scope_hash != stored.definition.approved_scope_hash
            ):
                _error(
                    "SAGA_INTEGRITY_INVALID",
                    "admitted authority does not join immutable Saga lineage",
                )

            updated = replace(
                state,
                status=SliceReconciliationStatus.ADMITTED,
                approval_hash=authority.approval_hash,
                grant_hash=authority.grant_hash,
                binding_set_hash=authority.binding_set_hash,
                admitted_host_instance_id=authority.host_instance_id,
                admitted_at=authority.admitted_at,
            )
            result = _with_state(stored, index, updated)
            self._sagas[saga_id] = result
            return result

    def record_host_commit(
        self,
        saga_id: str,
        actual_delta: ActualDelta,
        *,
        expected_revision: int,
        committed_at: str,
    ) -> StoredExecutionSaga:
        validate_actual_delta_integrity(actual_delta)
        with self._lock:
            stored = self._get_required(saga_id)
            index = _state_index(stored, actual_delta.execution_slice_hash)
            state = stored.slice_states[index]

            if state.actual_delta_hash is not None:
                if (
                    state.actual_delta_hash == actual_delta.actual_delta_hash
                    and state.committed_at == committed_at
                ):
                    return stored
                _error("SAGA_CONFLICT", "Host commit evidence differs")

            self._require_cas(stored, expected_revision)
            if state.status is not SliceReconciliationStatus.ADMITTED:
                _error("SAGA_CONFLICT", "Slice must be ADMITTED before Host commit")
            if (
                actual_delta.grant_hash != state.grant_hash
                or actual_delta.binding_set_hash != state.binding_set_hash
                or actual_delta.changeset_hash != stored.definition.changeset_hash
                or actual_delta.approved_scope_hash != stored.definition.approved_scope_hash
                or actual_delta.host_instance_id != state.admitted_host_instance_id
            ):
                _error(
                    "SAGA_INTEGRITY_INVALID",
                    "ActualDelta does not join admitted Slice authority",
                )

            updated = replace(
                state,
                status=SliceReconciliationStatus.HOST_COMMITTED,
                actual_delta_hash=actual_delta.actual_delta_hash,
                committed_at=committed_at,
            )
            result = _with_state(stored, index, updated)
            self._sagas[saga_id] = result
            return result

    def begin_reconciliation(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga:
        with self._lock:
            stored = self._get_required(saga_id)
            index = _state_index(stored, execution_slice_hash)
            state = stored.slice_states[index]
            if state.status in {
                SliceReconciliationStatus.RECONCILING,
                SliceReconciliationStatus.SUCCEEDED,
            }:
                return stored

            self._require_cas(stored, expected_revision)
            if state.status is not SliceReconciliationStatus.HOST_COMMITTED:
                _error("SAGA_CONFLICT", "Slice must be HOST_COMMITTED before reconciliation")
            updated = replace(state, status=SliceReconciliationStatus.RECONCILING)
            result = _with_state(stored, index, updated)
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
            if result.status is not ScopeComparisonStatus.WITHIN_SCOPE:
                _error(
                    "SAGA_CONFLICT",
                    "Task9 success store accepts only WITHIN_SCOPE; breach handling is separate",
                )

            updated = replace(state, scope_comparison_hash=result.comparison_hash)
            stored = _with_state(stored, index, updated)
            self._sagas[saga_id] = stored
            return stored

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
            if (
                result.status is not VerificationStatus.PASSED
                or any(
                    item.status is not VerificationStatus.PASSED
                    for item in result.task_results
                )
            ):
                _error(
                    "SAGA_CONFLICT",
                    "non-PASSED verification cannot transition a Slice to SUCCEEDED",
                )

            updated = replace(
                state,
                status=SliceReconciliationStatus.SUCCEEDED,
                verification_hash=result.verification_hash,
                reconciled_at=reconciled_at,
            )
            states = list(stored.slice_states)
            states[index] = updated
            all_succeeded = all(
                item.status is SliceReconciliationStatus.SUCCEEDED for item in states
            )
            final_status = (
                ExecutionSagaStatus.SUCCEEDED
                if all_succeeded
                else ExecutionSagaStatus.EXECUTING
            )
            final = StoredExecutionSaga(
                definition=stored.definition,
                saga_revision=stored.saga_revision + 1,
                status=final_status,
                slice_states=tuple(states),
                compensation_refs=stored.compensation_refs,
            )
            self._sagas[saga_id] = final
            return final


__all__ = ["ExecutionSagaStore", "InMemoryExecutionSagaStore"]
