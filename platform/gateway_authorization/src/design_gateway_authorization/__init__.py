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
from .v2 import (
    AdmittedExecutionAuthorityV2,
    ApprovalConsumptionRequestV2,
    ExecutionGrantRequestV2,
    ExecutionGrantV2,
    GatewayAuthorizationServiceV2,
    compute_grant_hash_v2,
)
from .store_v2 import InMemoryGatewayAuthorizationStoreV2

__all__ = [
    "AdmittedExecutionAuthority",
    "AdmittedExecutionAuthorityV2",
    "ApprovalAdmission",
    "ApprovalConsumptionRequest",
    "ApprovalConsumptionRequestV2",
    "ApprovalLifecycle",
    "ApprovalRecord",
    "ApprovalState",
    "ExecutionGrant",
    "ExecutionGrantRequest",
    "ExecutionGrantRequestV2",
    "ExecutionGrantV2",
    "GatewayAuthorizationError",
    "GatewayAuthorizationService",
    "GatewayAuthorizationServiceV2",
    "GatewayAuthorizationStore",
    "GrantLifecycle",
    "GrantState",
    "InMemoryGatewayAuthorizationStore",
    "InMemoryGatewayAuthorizationStoreV2",
    "StoredApproval",
    "StoredGrant",
    "compute_admission_fingerprint",
    "compute_approval_hash",
    "compute_grant_hash",
    "compute_grant_hash_v2",
]
