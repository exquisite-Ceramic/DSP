"""Public provider-neutral Step37 execution coordination API."""

from .contracts import (
    AuthorityFailure,
    CoordinationError,
    CoordinationResult,
    CoordinationStatus,
    HostCommitted,
    HostDispatchContext,
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
    HostOutcomeProbe,
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
from .recovery import (
    ExecutionRecoveryDisposition,
    ExecutionRecoveryProjection,
    UnknownOutcomeRecovery,
    project_execution_recovery,
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
    "ExecutionRecoveryDisposition",
    "ExecutionRecoveryProjection",
    "ExecutionSagaCoordinator",
    "HostCommitted",
    "HostDispatchContext",
    "HostExecutionPort",
    "HostExecutionRegistry",
    "HostExecutionResult",
    "HostFailed",
    "HostFailurePhase",
    "HostOutcomeProbe",
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
    "UnknownOutcomeRecovery",
    "VerificationEvidencePort",
    "compute_readiness_receipt_hash",
    "project_execution_recovery",
]
