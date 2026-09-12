from __future__ import annotations

from design_execution_coordination import (
    MaterializedCoordinationStatus,
    ReadinessStatus,
)

from tests.execution_coordination._materialized_support import execute, materialized_fixture


def test_not_ready_returns_readiness_failed_before_saga_or_host_mutation() -> None:
    fixture = materialized_fixture(
        readiness_statuses={
            "autocad": ReadinessStatus.READY,
            "revit": ReadinessStatus.NOT_READY,
        }
    )

    result = execute(fixture)

    assert result.status is MaterializedCoordinationStatus.READINESS_FAILED
    assert result.saga_id == "NOT_CREATED"
    assert result.saga_revision == 0
    assert result.active_slice_hash is None
    assert result.failure_ref == "REVIT_NOT_READY"
    assert result.convergence_result_hash is None
    assert fixture.reconciliation.create_calls == 0
    assert all(port.calls == [] for port in fixture.host_registry.ports.values())
    assert fixture.evidence_port.bundle_calls == []
    assert fixture.evidence_port.evidence_calls == []
    assert fixture.convergence_verifier.calls == []
    assert all(len(port.calls) == 1 for port in fixture.readiness_ports.values())
