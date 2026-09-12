from __future__ import annotations

from design_execution_coordination import (
    HostFailed,
    HostFailurePhase,
    MaterializedCoordinationStatus,
)
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    SliceReconciliationStatusV2,
)

from tests.execution_coordination._materialized_support import execute, materialized_fixture


def test_revit_unknown_commit_requires_recovery_without_retry_or_convergence() -> None:
    failure = HostFailed(
        phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
        failure_ref="REVIT_COMMIT_STATE_UNKNOWN",
        failed_at="2026-09-06T14:03:00Z",
    )
    fixture = materialized_fixture(host_failures={"revit": failure})

    result = execute(fixture)

    assert result.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED
    assert result.failure_ref == "REVIT_COMMIT_STATE_UNKNOWN"
    assert (
        result.active_slice_hash
        == fixture.ctx.execution_plan.execution_slices[1].execution_slice_hash
    )
    assert result.convergence_result_hash is None
    assert fixture.convergence_verifier.calls == []
    assert len(fixture.host_registry.ports["autocad"].calls) == 1
    assert len(fixture.host_registry.ports["revit"].calls) == 1

    stored = fixture.reconciliation.get_saga(result.saga_id)
    assert stored is not None
    assert stored.status is ExecutionSagaStatusV2.EXECUTING
    assert stored.slice_states[0].status is SliceReconciliationStatusV2.SUCCEEDED
    assert stored.slice_states[1].status is SliceReconciliationStatusV2.ADMITTED
    assert stored.slice_states[1].actual_delta_hash is None
