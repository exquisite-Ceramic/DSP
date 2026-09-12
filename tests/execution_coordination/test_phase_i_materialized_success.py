from __future__ import annotations

from design_execution_coordination import MaterializedCoordinationStatus
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    SagaConvergenceOutcome,
    SliceReconciliationStatusV2,
)

from tests.execution_coordination._materialized_support import execute, materialized_fixture

_execute = execute
_materialized_fixture = materialized_fixture


def test_materialized_success_runs_hosts_once_in_frozen_order_then_converges() -> None:
    fixture = materialized_fixture()

    result = execute(fixture)

    assert result.status is MaterializedCoordinationStatus.SUCCEEDED
    assert result.failure_ref is None
    assert result.active_slice_hash is None
    assert result.convergence_result_hash is not None
    assert fixture.reconciliation.create_calls == 1
    assert tuple(
        item.host_type for item in fixture.host_registry.resolutions
    ) == ("autocad", "revit")
    assert all(len(port.calls) == 1 for port in fixture.host_registry.ports.values())
    assert len(fixture.convergence_verifier.calls) == 1

    stored = fixture.reconciliation.get_saga(result.saga_id)
    assert stored is not None
    assert stored.status is ExecutionSagaStatusV2.SUCCEEDED
    assert stored.convergence_outcome is SagaConvergenceOutcome.CONVERGED
    assert stored.convergence_result_hash == result.convergence_result_hash
    assert tuple(item.status for item in stored.slice_states) == (
        SliceReconciliationStatusV2.SUCCEEDED,
        SliceReconciliationStatusV2.SUCCEEDED,
    )
    assert result.saga_revision == stored.saga_revision
