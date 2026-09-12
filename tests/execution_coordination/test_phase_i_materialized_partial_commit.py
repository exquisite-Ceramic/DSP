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

from tests.execution_coordination.test_phase_i_materialized_success import (
    _execute,
    _materialized_fixture,
)


def test_revit_before_commit_after_autocad_success_is_partially_committed() -> None:
    failure = HostFailed(
        phase=HostFailurePhase.BEFORE_COMMIT,
        failure_ref="REVIT_REVISION_CONFLICT",
        failed_at="2026-09-06T14:03:00Z",
    )
    fixture = _materialized_fixture(host_failures={"revit": failure})

    result = _execute(fixture)

    assert result.status is MaterializedCoordinationStatus.PARTIALLY_COMMITTED
    assert result.failure_ref == "REVIT_REVISION_CONFLICT"
    assert result.convergence_result_hash is None
    assert fixture.convergence_verifier.calls == []
    assert len(fixture.host_registry.ports["autocad"].calls) == 1
    assert len(fixture.host_registry.ports["revit"].calls) == 1
    assert len(fixture.evidence_port.evidence_calls) == 1

    stored = fixture.reconciliation.get_saga(result.saga_id)
    assert stored is not None
    assert stored.status is ExecutionSagaStatusV2.PARTIALLY_COMMITTED
    assert stored.slice_states[0].status is SliceReconciliationStatusV2.SUCCEEDED
    assert stored.slice_states[1].status is SliceReconciliationStatusV2.FAILED_BEFORE_COMMIT
    assert stored.slice_states[1].actual_delta_hash is None
