"""Phase I 本地成功但全局 canonical 不一致时的离线发散证明。"""

from __future__ import annotations

from design_execution_coordination import MaterializedCoordinationStatus
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    SagaConvergenceOutcome,
    SliceReconciliationStatusV2,
)

from tests.execution_coordination.test_phase_i_materialized_success import (
    _execute,
    _materialized_fixture,
)


def test_phase_i_offline_local_success_can_finish_diverged_without_rewriting_slices() -> None:
    fixture = _materialized_fixture(divergent_host="revit")

    result = _execute(fixture)

    assert result.status is MaterializedCoordinationStatus.DIVERGED
    assert result.failure_ref == "CONVERGENCE_DIVERGED"
    assert result.convergence_result_hash is not None
    assert tuple(item.host_type for item in fixture.host_registry.resolutions) == (
        "autocad",
        "revit",
    )
    assert all(len(port.calls) == 1 for port in fixture.host_registry.ports.values())
    assert len(fixture.evidence_port.bundle_calls) == 2
    assert len(fixture.evidence_port.evidence_calls) == 2
    assert len(fixture.convergence_verifier.calls) == 1

    stored = fixture.reconciliation.get_saga(result.saga_id)
    assert stored is not None
    assert stored.status is ExecutionSagaStatusV2.DIVERGED
    assert stored.convergence_outcome is SagaConvergenceOutcome.DIVERGED
    assert stored.convergence_result_hash == result.convergence_result_hash
    assert tuple(item.status for item in stored.slice_states) == (
        SliceReconciliationStatusV2.SUCCEEDED,
        SliceReconciliationStatusV2.SUCCEEDED,
    )
    assert all(item.verification_hash is not None for item in stored.slice_states)
