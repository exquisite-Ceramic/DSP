import pytest

from design_execution_coordination import (
    AuthorityFailure,
    CoordinationResult,
    CoordinationStatus,
    HostFailed,
    HostFailurePhase,
)


def test_step37_coordination_contracts_are_closed_and_validated():
    result = CoordinationResult(
        saga_id="SG-STEP37",
        saga_revision=3,
        status=CoordinationStatus.RECOVERY_REQUIRED,
        active_slice_hash="a" * 64,
        failure_ref="HOST-TIMEOUT-001",
    )
    assert result.status is CoordinationStatus.RECOVERY_REQUIRED

    failure = HostFailed(
        phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
        failure_ref="HOST-TIMEOUT-001",
        failed_at="2026-08-31T12:00:00Z",
    )
    assert failure.phase is HostFailurePhase.COMMIT_STATE_UNKNOWN

    with pytest.raises(ValueError):
        CoordinationResult(
            saga_id="SG-STEP37",
            saga_revision=-1,
            status=CoordinationStatus.FAILED,
            active_slice_hash=None,
            failure_ref=None,
        )

    with pytest.raises(ValueError):
        AuthorityFailure(failure_ref="", failed_at="2026-08-31T12:00:00Z")
