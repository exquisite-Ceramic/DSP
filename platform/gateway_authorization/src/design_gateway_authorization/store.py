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
        requested_lifecycle = ApprovalLifecycle(
            ApprovalState.REVOKED,
            revoked_at=revoked_at,
            revocation_reason=reason,
        )
        with self._lock:
            stored = self._approvals.get(approval_id)
            if stored is None:
                raise GatewayAuthorizationError(
                    "APPROVAL_RECORD_NOT_FOUND",
                    "approval record not found",
                )
            if stored.lifecycle.state is ApprovalState.REVOKED:
                return stored

            revoked_approval = StoredApproval(stored.record, requested_lifecycle)
            child_updates: dict[str, StoredGrant] = {}
            for grant_hash, child in self._grants.items():
                if child.grant.approval_id != approval_id:
                    continue
                if child.lifecycle.state not in (GrantState.ACTIVE, GrantState.ADMITTED):
                    continue
                child_updates[grant_hash] = StoredGrant(
                    child.grant,
                    GrantLifecycle(
                        GrantState.REVOKED,
                        admitted_at=child.lifecycle.admitted_at,
                        revoked_at=requested_lifecycle.revoked_at,
                        revocation_reason=requested_lifecycle.revocation_reason,
                        superseded_by_grant_id=child.lifecycle.superseded_by_grant_id,
                    ),
                )

            self._approvals[approval_id] = revoked_approval
            self._grants.update(child_updates)
            return revoked_approval

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

    @staticmethod
    def _admitted_authority(stored: StoredGrant) -> AdmittedExecutionAuthority:
        admitted_at = stored.lifecycle.admitted_at
        if admitted_at is None:
            raise GatewayAuthorizationError(
                "EXECUTION_GRANT_CONFLICT",
                "admitted grant is missing admission evidence",
            )
        grant = stored.grant
        return AdmittedExecutionAuthority(
            approval_hash=grant.approval_hash,
            grant_hash=grant.grant_hash,
            changeset_hash=grant.changeset_hash,
            approved_scope_hash=grant.approved_scope_hash,
            execution_slice_hash=grant.execution_slice_hash,
            binding_set_hash=grant.binding_set_hash,
            host_instance_id=grant.host_instance_id,
            admitted_at=admitted_at,
        )

    def admit_grant(
        self,
        grant_hash: str,
        admitted_at: str,
    ) -> AdmittedExecutionAuthority:
        requested = GrantLifecycle(GrantState.ADMITTED, admitted_at=admitted_at)
        normalized_at = requested.admitted_at
        if normalized_at is None:
            raise GatewayAuthorizationError(
                "EXECUTION_GRANT_CONFLICT",
                "admitted_at is required",
            )

        with self._lock:
            stored = self._grants.get(grant_hash)
            if stored is None:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_CONFLICT",
                    "execution grant not found",
                )

            parent = self._approvals.get(stored.grant.approval_id)
            if parent is None:
                raise GatewayAuthorizationError(
                    "APPROVAL_RECORD_NOT_FOUND",
                    "parent approval record not found",
                )
            if parent.lifecycle.state is ApprovalState.REVOKED:
                raise GatewayAuthorizationError(
                    "APPROVAL_REVOKED",
                    "parent approval is revoked",
                )

            if stored.lifecycle.state is GrantState.ADMITTED:
                return self._admitted_authority(stored)
            if stored.lifecycle.state is GrantState.REVOKED:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_REVOKED",
                    "execution grant has been revoked",
                )
            if stored.lifecycle.state is GrantState.EXPIRED:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_EXPIRED",
                    "execution grant has expired",
                )

            stored = self._project_expiry(stored, normalized_at)
            if stored.lifecycle.state is GrantState.EXPIRED:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_EXPIRED",
                    "execution grant has expired",
                )

            admitted = StoredGrant(
                stored.grant,
                GrantLifecycle(GrantState.ADMITTED, admitted_at=normalized_at),
            )
            self._grants[grant_hash] = admitted
            return self._admitted_authority(admitted)

    def revoke_grant(
        self,
        grant_hash: str,
        revoked_at: str,
        reason: str,
    ) -> StoredGrant:
        requested = GrantLifecycle(
            GrantState.REVOKED,
            revoked_at=revoked_at,
            revocation_reason=reason,
        )
        with self._lock:
            stored = self._grants.get(grant_hash)
            if stored is None:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_CONFLICT",
                    "execution grant not found",
                )

            if stored.lifecycle.state is GrantState.REVOKED:
                if (
                    stored.lifecycle.revoked_at == requested.revoked_at
                    and stored.lifecycle.revocation_reason == requested.revocation_reason
                ):
                    return stored
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_CONFLICT",
                    "conflicting repeated grant revocation",
                )
            if stored.lifecycle.state is GrantState.EXPIRED:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_EXPIRED",
                    "execution grant has expired",
                )

            revoked = StoredGrant(
                stored.grant,
                GrantLifecycle(
                    GrantState.REVOKED,
                    admitted_at=stored.lifecycle.admitted_at,
                    revoked_at=requested.revoked_at,
                    revocation_reason=requested.revocation_reason,
                    superseded_by_grant_id=stored.lifecycle.superseded_by_grant_id,
                ),
            )
            self._grants[grant_hash] = revoked
            return revoked


__all__ = [
    "GatewayAuthorizationStore",
    "InMemoryGatewayAuthorizationStore",
]
