"""Provider-neutral transactional store contract for Step32 authorization state."""

from __future__ import annotations

import threading
from datetime import datetime
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


def _parse_utc(value: str) -> datetime:
    raw = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(raw)


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

    @staticmethod
    def _lineage(grant: ExecutionGrant) -> tuple[str, str]:
        return grant.approval_hash, grant.execution_slice_hash

    def _project_expiry(
        self,
        stored: StoredGrant,
        evaluated_at: str,
    ) -> StoredGrant:
        if (
            stored.lifecycle.state is GrantState.ACTIVE
            and _parse_utc(evaluated_at) >= _parse_utc(stored.grant.expires_at)
        ):
            projected = StoredGrant(
                stored.grant,
                GrantLifecycle(GrantState.EXPIRED),
            )
            self._grants[stored.grant.grant_hash] = projected
            return projected
        return stored

    def issue_or_get_grant(self, grant: ExecutionGrant) -> ExecutionGrant:
        if not isinstance(grant, ExecutionGrant):
            raise TypeError("grant must be ExecutionGrant")

        lineage = self._lineage(grant)
        with self._lock:
            grant_hashes = self._lineages.get(lineage)
            if not grant_hashes:
                existing = self._grants.get(grant.grant_hash)
                if existing is not None:
                    self._lineages[lineage] = [existing.grant.grant_hash]
                    return existing.grant
                self._grants[grant.grant_hash] = StoredGrant(
                    grant,
                    GrantLifecycle(GrantState.ACTIVE),
                )
                self._lineages[lineage] = [grant.grant_hash]
                return grant

            current_hash = grant_hashes[-1]
            current = self._project_expiry(
                self._grants[current_hash],
                grant.issued_at,
            )
            same_binding = current.grant.binding_set_hash == grant.binding_set_hash
            state = current.lifecycle.state

            if same_binding:
                if state in (GrantState.ACTIVE, GrantState.ADMITTED):
                    return current.grant
                if state is GrantState.REVOKED:
                    raise GatewayAuthorizationError(
                        "EXECUTION_GRANT_REVOKED",
                        "execution grant has been revoked",
                    )
                if state is GrantState.EXPIRED:
                    raise GatewayAuthorizationError(
                        "EXECUTION_GRANT_EXPIRED",
                        "execution grant has expired",
                    )

            if state is GrantState.ADMITTED:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_ALREADY_ADMITTED",
                    "admitted execution authority cannot switch provider binding",
                )

            if state is GrantState.ACTIVE:
                superseded = StoredGrant(
                    current.grant,
                    GrantLifecycle(
                        GrantState.REVOKED,
                        revoked_at=grant.issued_at,
                        revocation_reason="provider binding superseded",
                        superseded_by_grant_id=grant.grant_id,
                    ),
                )
                new_stored = StoredGrant(
                    grant,
                    GrantLifecycle(GrantState.ACTIVE),
                )
                self._grants[current.grant.grant_hash] = superseded
                self._grants[grant.grant_hash] = new_stored
                grant_hashes.append(grant.grant_hash)
                return grant

            if state in (GrantState.REVOKED, GrantState.EXPIRED):
                new_stored = StoredGrant(
                    grant,
                    GrantLifecycle(GrantState.ACTIVE),
                )
                self._grants[grant.grant_hash] = new_stored
                grant_hashes.append(grant.grant_hash)
                return grant

            raise GatewayAuthorizationError(
                "EXECUTION_GRANT_CONFLICT",
                "unsupported grant lineage state",
            )

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
