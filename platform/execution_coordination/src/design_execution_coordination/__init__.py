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
from .materialized_contracts import (
    MaterializedCoordinationResult,
    MaterializedCoordinationStatus,
)
from .materialized_coordinator import MaterializedExecutionSagaCoordinator
from .ports import (
    ConvergenceEvidencePort,
    CoordinationClock,
    ExecutionAuthorityPort,
    HostExecutionPort,
    HostExecutionRegistry,
    HostReadinessPort,
    HostReadinessRegistry,
    MaterializedHostExecutionPort,
    MaterializedHostExecutionRegistry,
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
    "ConvergenceEvidencePort",
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
    "MaterializedCoordinationResult",
    "MaterializedCoordinationStatus",
    "MaterializedExecutionSagaCoordinator",
    "MaterializedHostExecutionPort",
    "MaterializedHostExecutionRegistry",
    "ReadinessBarrierResult",
    "ReadinessBarrierStatus",
    "ReadinessError",
    "ReadinessStatus",
    "VerificationEvidencePort",
    "compute_readiness_receipt_hash",
]
