"""Public provider-neutral Step37 execution coordination API."""

from .contracts import (
    AuthorityFailure,
    CoordinationError,
    CoordinationResult,
    CoordinationStatus,
    HostCommitted,
    HostExecutionResult,
    HostFailed,
    HostFailurePhase,
)
from .coordinator import ExecutionSagaCoordinator
from .ports import (
    CoordinationClock,
    ExecutionAuthorityPort,
    HostExecutionPort,
    HostExecutionRegistry,
    HostReadinessPort,
    HostReadinessRegistry,
    VerificationEvidencePort,
)
from .readiness import CrossHostReadinessBarrier
from .readiness_contracts import (
    HostReadinessReceipt,
    ReadinessBarrierResult,
    ReadinessBarrierStatus,
    ReadinessError,
    ReadinessStatus,
    compute_readiness_receipt_hash,
)

__all__ = [
    "AuthorityFailure",
    "CoordinationClock",
    "CoordinationError",
    "CoordinationResult",
    "CoordinationStatus",
    "CrossHostReadinessBarrier",
    "ExecutionAuthorityPort",
    "ExecutionSagaCoordinator",
    "HostCommitted",
    "HostExecutionPort",
    "HostExecutionRegistry",
    "HostExecutionResult",
    "HostFailed",
    "HostFailurePhase",
    "HostReadinessPort",
    "HostReadinessReceipt",
    "HostReadinessRegistry",
    "ReadinessBarrierResult",
    "ReadinessBarrierStatus",
    "ReadinessError",
    "ReadinessStatus",
    "VerificationEvidencePort",
    "compute_readiness_receipt_hash",
]
