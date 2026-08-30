"""Public API for Step32 Gateway authorization."""

from .contracts import (
    AdmittedExecutionAuthority,
    ApprovalAdmission,
    ApprovalConsumptionRequest,
    ApprovalLifecycle,
    ApprovalRecord,
    ApprovalState,
    ExecutionGrant,
    ExecutionGrantRequest,
    GatewayAuthorizationError,
    GrantLifecycle,
    GrantState,
    StoredApproval,
    StoredGrant,
)
from .hashing import (
    compute_admission_fingerprint,
    compute_approval_hash,
    compute_grant_hash,
)
from .service import GatewayAuthorizationService
from .store import GatewayAuthorizationStore, InMemoryGatewayAuthorizationStore

__all__ = [
    "AdmittedExecutionAuthority",
    "ApprovalAdmission",
    "ApprovalConsumptionRequest",
    "ApprovalLifecycle",
    "ApprovalRecord",
    "ApprovalState",
    "ExecutionGrant",
    "ExecutionGrantRequest",
    "GatewayAuthorizationError",
    "GatewayAuthorizationService",
    "GatewayAuthorizationStore",
    "GrantLifecycle",
    "GrantState",
    "InMemoryGatewayAuthorizationStore",
    "StoredApproval",
    "StoredGrant",
    "compute_admission_fingerprint",
    "compute_approval_hash",
    "compute_grant_hash",
]
