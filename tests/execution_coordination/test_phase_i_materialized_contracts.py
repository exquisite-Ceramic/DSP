from __future__ import annotations

from dataclasses import fields

from design_execution_coordination import (
    MaterializedCoordinationResult,
    MaterializedCoordinationStatus,
)


def test_materialized_coordination_status_is_exact() -> None:
    assert tuple(item.value for item in MaterializedCoordinationStatus) == (
        "SUCCEEDED",
        "FAILED",
        "PARTIALLY_COMMITTED",
        "RECOVERY_REQUIRED",
        "READINESS_FAILED",
        "DIVERGED",
    )


def test_materialized_coordination_result_has_exact_frozen_fields() -> None:
    assert {field.name for field in fields(MaterializedCoordinationResult)} == {
        "saga_id",
        "saga_revision",
        "status",
        "active_slice_hash",
        "failure_ref",
        "convergence_result_hash",
    }

    result = MaterializedCoordinationResult(
        saga_id="SGV2-EXAMPLE",
        saga_revision=3,
        status=MaterializedCoordinationStatus.DIVERGED,
        active_slice_hash=None,
        failure_ref="CONVERGENCE_DIVERGED",
        convergence_result_hash="a" * 64,
    )
    assert result.status is MaterializedCoordinationStatus.DIVERGED
    assert result.convergence_result_hash == "a" * 64
