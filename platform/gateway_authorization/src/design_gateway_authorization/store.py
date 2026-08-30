"""Provider-neutral transactional store contract for Step32 authorization state."""

from __future__ import annotations

import threading
from typing import Protocol

from .contracts import (
    AdmittedExecutionAuthority,
    ApprovalLifecycle,
    ApprovalRecord,
    ApprovalState,
    ExecutionGrant,
    GatewayAuthorizationError,
    GrantLifecycle,
    GrantState,
    StoredApproval,
    StoredGrant,
)


class GatewayAuthorizationStore(Protocol):
    """Atomic persistence boundary required by GatewayAuthorizationService."""

    def consume_admission_once(
        self,
        admission_id: str,
        admission_fingerprint: str,
        approval_record: ApprovalRecord,
    ) -> ApprovalRecord: ...

    def get_approval(self, approval_id: str) -> StoredApproval | None: ...

    def revoke_approval(
        self,
        approval_id: str,
        revoked_at: str,
        reason: str,
    ) -> StoredApproval: ...

    def issue_or_get_grant(self, grant: ExecutionGrant) -> ExecutionGrant: ...

    def get_grant(self, grant_hash: str) -> StoredGrant | None: ...

    def admit_grant(
        self,
        grant_hash: str,
        admitted_at: str,
    ) -> AdmittedExecutionAuthority: ...

    def revoke_grant(
        self,
        grant_hash: str,
        revoked_at: str,
        reason: str,
    ) -> StoredGrant: ...


class InMemoryGatewayAuthorizationStore:
    """Thread-safe reference semantics for the Step32 transactional store boundary."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._consumptions: dict[str, tuple[str, str]] = {}
        self._approvals: dict[str, StoredApproval] = {}
        self._grants: dict[str, StoredGrant] = {}
        self._lineages: dict[tuple[str, str], list[str]] = {}

    def consume_admission_once(
        self,
        admission_id: str,
        admission_fingerprint: str,
        approval_record: ApprovalRecord,
    ) -> ApprovalRecord:
        if not isinstance(approval_record, ApprovalRecord):
            raise TypeError("approval_record must be ApprovalRecord")
        if admission_id != approval_record.admission_id:
            raise ValueError("admission_id must match ApprovalRecord")
        if admission_fingerprint != approval_record.admission_fingerprint:
            raise ValueError("admission_fingerprint must match ApprovalRecord")

        stored = StoredApproval(
            record=approval_record,
            lifecycle=ApprovalLifecycle(ApprovalState.ACTIVE),
        )
        with self._lock:
            existing = self._consumptions.get(admission_id)
            if existing is not None:
                existing_fingerprint, _approval_id = existing
                if existing_fingerprint == admission_fingerprint:
                    raise GatewayAuthorizationError(
                        "APPROVAL_ADMISSION_ALREADY_CONSUMED",
                        "ApprovalAdmission has already been consumed",
                    )
                raise GatewayAuthorizationError(
                    "APPROVAL_ADMISSION_CONFLICT",
                    "ApprovalAdmission id is already bound to different authority content",
                )

            self._approvals[approval_record.approval_id] = stored
            self._consumptions[admission_id] = (
                admission_fingerprint,
                approval_record.approval_id,
            )
            return approval_record

    def get_approval(self, approval_id: str) -> StoredApproval | None:
        with self._lock:
            return self._approvals.get(approval_id)

    def revoke_approval(
        self,
        approval_id: str,
        revoked_at: str,
        reason: str,
    ) -> StoredApproval:
        raise NotImplementedError("approval revocation is implemented in Step32 Task 9")

    def issue_or_get_grant(self, grant: ExecutionGrant) -> ExecutionGrant:
        if not isinstance(grant, ExecutionGrant):
            raise TypeError("grant must be ExecutionGrant")
        stored = StoredGrant(grant, GrantLifecycle(GrantState.ACTIVE))
        with self._lock:
            existing = self._grants.get(grant.grant_hash)
            if existing is not None:
                return existing.grant
            self._grants[grant.grant_hash] = stored
            return grant

    def get_grant(self, grant_hash: str) -> StoredGrant | None:
        with self._lock:
            return self._grants.get(grant_hash)

    def admit_grant(
        self,
        grant_hash: str,
        admitted_at: str,
    ) -> AdmittedExecutionAuthority:
        raise NotImplementedError("grant admission is implemented in Step32 Task 9")

    def revoke_grant(
        self,
        grant_hash: str,
        revoked_at: str,
        reason: str,
    ) -> StoredGrant:
        raise NotImplementedError("grant revocation is implemented in Step32 Task 9")


__all__ = [
    "GatewayAuthorizationStore",
    "InMemoryGatewayAuthorizationStore",
]
