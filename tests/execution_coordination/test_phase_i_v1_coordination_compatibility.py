from __future__ import annotations

from pathlib import Path

from design_execution_coordination import (
    CoordinationResult,
    CoordinationStatus,
    ReadinessBarrierResult,
    ReadinessBarrierStatus,
)

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "platform" / "execution_coordination" / "src" / "design_execution_coordination"
READINESS_SOURCE = (PACKAGE / "readiness.py").read_text(encoding="utf-8")


def test_v1_coordination_status_enum_is_byte_for_byte_unchanged() -> None:
    assert tuple(item.value for item in CoordinationStatus) == (
        "SUCCEEDED",
        "FAILED",
        "PARTIALLY_COMMITTED",
        "RECOVERY_REQUIRED",
    )


def test_readiness_result_is_not_a_v1_coordination_result() -> None:
    result = ReadinessBarrierResult(
        status=ReadinessBarrierStatus.NOT_READY,
        receipts=(),
        failure_ref="HOST_NOT_READY",
    )
    assert not isinstance(result, CoordinationResult)
    assert ReadinessBarrierStatus is not CoordinationStatus


def test_readiness_layer_cannot_execute_hosts_admit_authority_or_create_sagas() -> None:
    forbidden = (
        "CoordinationResult",
        "CoordinationStatus",
        "ExecutionSagaCoordinator",
        "HostExecutionPort",
        "HostExecutionRegistry",
        ".execute(",
        ".admit(",
        "Saga",
    )
    for marker in forbidden:
        assert marker not in READINESS_SOURCE
