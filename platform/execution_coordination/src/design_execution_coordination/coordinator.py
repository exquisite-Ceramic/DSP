"""Deterministic provider-neutral forward coordination for Step37."""

from __future__ import annotations

from design_approval_scope import ApprovalScopeBoundary
from design_changeset import CanonicalChangeSet
from design_execution_planning import ExecutionPlan
from design_execution_reconciliation import (
    ExecutionReconciliationService,
    ExecutionSagaStatus,
    ScopeComparisonRequest,
    SemanticVerificationRequest,
    SliceReconciliationStatus,
)
from design_gateway_authorization import AdmittedExecutionAuthority

from .contracts import (
    AuthorityFailure,
    CoordinationError,
    CoordinationResult,
    CoordinationStatus,
    HostCommitted,
)
from .ports import (
    CoordinationClock,
    ExecutionAuthorityPort,
    HostExecutionRegistry,
    VerificationEvidencePort,
)

_ACTIVE_SLICE_STATUSES = frozenset(
    {
        SliceReconciliationStatus.ADMISSION_RESERVED,
        SliceReconciliationStatus.ADMITTED,
        SliceReconciliationStatus.HOST_COMMITTED,
        SliceReconciliationStatus.RECONCILING,
    }
)
_TERMINAL_COORDINATION_STATUS = {
    ExecutionSagaStatus.SUCCEEDED: CoordinationStatus.SUCCEEDED,
    ExecutionSagaStatus.FAILED: CoordinationStatus.FAILED,
    ExecutionSagaStatus.PARTIALLY_COMMITTED: CoordinationStatus.PARTIALLY_COMMITTED,
}
_NON_FORWARD_SAGA_STATUSES = frozenset(
    {
        ExecutionSagaStatus.COMPENSATING,
        ExecutionSagaStatus.COMPENSATED,
        ExecutionSagaStatus.COMPENSATION_FAILED,
    }
)


class ExecutionSagaCoordinator:
    """Drive one immutable Step33 Saga without owning its durable state machine."""

    def __init__(
        self,
        *,
        reconciliation: ExecutionReconciliationService,
        authority_port: ExecutionAuthorityPort,
        host_registry: HostExecutionRegistry,
        evidence_port: VerificationEvidencePort,
        clock: CoordinationClock,
    ) -> None:
        self._reconciliation = reconciliation
        self._authority_port = authority_port
        self._host_registry = host_registry
        self._evidence_port = evidence_port
        self._clock = clock

    @staticmethod
    def _terminal_result(stored) -> CoordinationResult | None:
        status = _TERMINAL_COORDINATION_STATUS.get(stored.status)
        if status is None:
            return None
        return CoordinationResult(
            saga_id=stored.definition.saga_id,
            saga_revision=stored.saga_revision,
            status=status,
            active_slice_hash=None,
            failure_ref=None,
        )

    @staticmethod
    def _assigned_tasks(stored, canonical_changeset, execution_slice_hash):
        assignments = tuple(
            assignment
            for assignment in stored.definition.slice_validation_assignments
            if assignment.execution_slice_hash == execution_slice_hash
        )
        if len(assignments) != 1:
            raise CoordinationError(
                "SAGA_INTEGRITY_INVALID",
                "Slice validation assignment is unresolved",
            )
        tasks_by_id = {
            task.validation_task_id: task
            for task in canonical_changeset.validation_tasks
        }
        try:
            return tuple(
                tasks_by_id[task_id]
                for task_id in assignments[0].validation_task_ids
            )
        except KeyError as exc:
            raise CoordinationError(
                "SAGA_INTEGRITY_INVALID",
                f"Saga validation assignment references unknown task {exc.args[0]}",
            ) from exc

    def execute(
        self,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundary,
        execution_plan: ExecutionPlan,
    ) -> CoordinationResult:
        stored = self._reconciliation.create_saga(
            canonical_changeset,
            approval_scope_boundary,
            execution_plan,
        )
        definition = stored.definition
        if definition.changeset_hash != canonical_changeset.changeset_hash:
            raise CoordinationError(
                "SAGA_INTEGRITY_INVALID",
                "Step33 Saga does not join the supplied CanonicalChangeSet",
            )
        if definition.approved_scope_hash != approval_scope_boundary.scope_hash:
            raise CoordinationError(
                "SAGA_INTEGRITY_INVALID",
                "Step33 Saga does not join the supplied ApprovalScopeBoundary",
            )
        if definition.execution_plan_hash != execution_plan.execution_plan_hash:
            raise CoordinationError(
                "SAGA_INTEGRITY_INVALID",
                "Step33 Saga does not join the supplied ExecutionPlan",
            )

        slice_by_hash = {
            item.execution_slice_hash: item for item in execution_plan.execution_slices
        }
        if len(slice_by_hash) != len(execution_plan.execution_slices):
            raise CoordinationError(
                "SAGA_INTEGRITY_INVALID",
                "ExecutionPlan contains duplicate Slice hashes",
            )
        if set(slice_by_hash) != set(definition.ordered_slice_hashes):
            raise CoordinationError(
                "SAGA_INTEGRITY_INVALID",
                "ExecutionPlan Slices differ from immutable Step33 Saga ordering",
            )

        terminal = self._terminal_result(stored)
        if terminal is not None:
            return terminal
        if stored.status in _NON_FORWARD_SAGA_STATUSES:
            raise CoordinationError(
                "SAGA_NOT_FORWARD_EXECUTABLE",
                "Step33 Saga is in compensation lifecycle and cannot execute forward",
            )

        active = tuple(
            state
            for state in stored.slice_states
            if state.status in _ACTIVE_SLICE_STATUSES
        )
        if len(active) > 1:
            raise CoordinationError(
                "SAGA_INTEGRITY_INVALID",
                "Step33 Saga contains more than one active Slice",
            )
        if active:
            return CoordinationResult(
                saga_id=definition.saga_id,
                saga_revision=stored.saga_revision,
                status=CoordinationStatus.RECOVERY_REQUIRED,
                active_slice_hash=active[0].execution_slice_hash,
                failure_ref=None,
            )

        for execution_slice_hash in definition.ordered_slice_hashes:
            state = next(
                item
                for item in stored.slice_states
                if item.execution_slice_hash == execution_slice_hash
            )
            if state.status is SliceReconciliationStatus.SUCCEEDED:
                continue
            if state.status is not SliceReconciliationStatus.NOT_STARTED:
                raise CoordinationError(
                    "SAGA_NOT_FORWARD_EXECUTABLE",
                    "non-terminal Saga contains a non-replayable Slice state",
                )

            execution_slice = slice_by_hash[execution_slice_hash]
            stored = self._reconciliation.reserve_slice_admission(
                definition.saga_id,
                execution_slice_hash,
                expected_revision=stored.saga_revision,
                reserved_at=self._clock.now(),
            )

            authority = self._authority_port.admit(execution_slice)
            if isinstance(authority, AuthorityFailure):
                raise NotImplementedError(
                    "Step37 authority failure handling is implemented in Task5"
                )
            if not isinstance(authority, AdmittedExecutionAuthority):
                raise CoordinationError(
                    "AUTHORITY_RESULT_INVALID",
                    "authority port returned an invalid result",
                )
            stored = self._reconciliation.confirm_slice_admitted(
                definition.saga_id,
                authority,
                expected_revision=stored.saga_revision,
            )

            host = self._host_registry.resolve(execution_slice.host_runtime_ref)
            host_result = host.execute(execution_slice, authority)
            if not isinstance(host_result, HostCommitted):
                raise NotImplementedError(
                    "Step37 Host failure handling is implemented in Task5"
                )
            delta = host_result.actual_delta
            stored = self._reconciliation.record_host_commit(
                definition.saga_id,
                delta,
                expected_revision=stored.saga_revision,
                committed_at=host_result.committed_at,
            )
            stored = self._reconciliation.begin_reconciliation(
                definition.saga_id,
                execution_slice_hash,
                expected_revision=stored.saga_revision,
            )

            scope_result = self._reconciliation.compare_scope(
                ScopeComparisonRequest(
                    admitted_execution_authority=authority,
                    actual_delta=delta,
                    approval_scope_boundary=approval_scope_boundary,
                    execution_slice=execution_slice,
                )
            )
            stored = self._reconciliation.record_scope_result(
                definition.saga_id,
                scope_result,
                expected_revision=stored.saga_revision,
            )
            terminal = self._terminal_result(stored)
            if terminal is not None:
                return terminal

            evidence_bundle = self._evidence_port.build_bundle(
                execution_slice=execution_slice,
                actual_delta=delta,
                canonical_changeset=canonical_changeset,
                approval_scope_boundary=approval_scope_boundary,
            )
            verification = self._reconciliation.verify_semantics(
                definition.saga_id,
                execution_slice_hash,
                SemanticVerificationRequest(
                    admitted_execution_authority=authority,
                    approval_scope_boundary=approval_scope_boundary,
                    canonical_changeset=canonical_changeset,
                    actual_delta=delta,
                    validation_tasks=self._assigned_tasks(
                        stored,
                        canonical_changeset,
                        execution_slice_hash,
                    ),
                    verification_evidence_bundle=evidence_bundle,
                    verified_at=self._clock.now(),
                ),
            )
            stored = self._reconciliation.record_verification_result(
                definition.saga_id,
                verification,
                expected_revision=stored.saga_revision,
                reconciled_at=self._clock.now(),
            )
            terminal = self._terminal_result(stored)
            if terminal is not None:
                return terminal

        raise CoordinationError(
            "SAGA_INTEGRITY_INVALID",
            "forward execution exhausted Saga order without reaching a terminal state",
        )


__all__ = ["ExecutionSagaCoordinator"]
