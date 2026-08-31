"""Deterministic provider-neutral forward coordination for Step37."""

from __future__ import annotations

from design_approval_scope import ApprovalScopeBoundary
from design_changeset import CanonicalChangeSet
from design_execution_planning import ExecutionPlan
from design_execution_reconciliation import (
    ExecutionReconciliationService,
    ExecutionSagaStatus,
    SliceReconciliationStatus,
)

from .contracts import CoordinationError, CoordinationResult, CoordinationStatus
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

        terminal_status = _TERMINAL_COORDINATION_STATUS.get(stored.status)
        if terminal_status is not None:
            return CoordinationResult(
                saga_id=definition.saga_id,
                saga_revision=stored.saga_revision,
                status=terminal_status,
                active_slice_hash=None,
                failure_ref=None,
            )
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

        raise NotImplementedError("Step37 forward execution is implemented in Task4")


__all__ = ["ExecutionSagaCoordinator"]
