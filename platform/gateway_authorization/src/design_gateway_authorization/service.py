"""Deterministic Step32 Gateway authorization service."""

from __future__ import annotations

from datetime import datetime

from design_approval_scope import (
    ApprovalScopeBoundary,
    ApprovalScopeError,
    validate_approval_scope_boundary,
)
from design_changeset import (
    CanonicalChangeSet,
    ChangeSetError,
    validate_changeset_integrity,
)

from .contracts import (
    ApprovalConsumptionRequest,
    ApprovalRecord,
    GatewayAuthorizationError,
)
from .hashing import compute_admission_fingerprint, compute_approval_hash


def _error(
    code: str,
    message: str,
    *,
    upstream_code: str | None = None,
) -> None:
    raise GatewayAuthorizationError(
        code,
        message,
        upstream_code=upstream_code,
    )


def _parse_utc(value: str) -> datetime:
    raw = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(raw)


class GatewayAuthorizationService:
    """Validate immutable approval evidence before one atomic store consumption."""

    def __init__(self, store) -> None:
        if store is None or not callable(getattr(store, "consume_admission_once", None)):
            raise TypeError("store must provide consume_admission_once")
        self._store = store

    def consume_approval(self, request: ApprovalConsumptionRequest) -> ApprovalRecord:
        self._require_approval_request(request)
        self._validate_admission_fingerprint(request)
        self._validate_admission_expiry(request)
        self._validate_scope_integrity(request.approval_scope_boundary)
        self._validate_changeset_integrity(
            request.canonical_changeset,
            request.approval_scope_boundary,
        )
        self._validate_approval_join(request)
        allowed_operations = self._least_privilege_operations(request)
        record = self._build_approval_record(request, allowed_operations)
        return self._store.consume_admission_once(
            request.admission.admission_id,
            request.admission.admission_fingerprint,
            record,
        )

    @staticmethod
    def _require_approval_request(request: ApprovalConsumptionRequest) -> None:
        if not isinstance(request, ApprovalConsumptionRequest):
            _error("APPROVAL_INPUT_INVALID", "request must be ApprovalConsumptionRequest")
        if not isinstance(request.approval_scope_boundary, ApprovalScopeBoundary):
            _error(
                "APPROVAL_INPUT_INVALID",
                "approval_scope_boundary must be ApprovalScopeBoundary",
            )
        if not isinstance(request.canonical_changeset, CanonicalChangeSet):
            _error(
                "APPROVAL_INPUT_INVALID",
                "canonical_changeset must be CanonicalChangeSet",
            )

    @staticmethod
    def _validate_admission_fingerprint(request: ApprovalConsumptionRequest) -> None:
        expected = compute_admission_fingerprint(request.admission)
        if expected != request.admission.admission_fingerprint:
            _error(
                "APPROVAL_INTEGRITY_INVALID",
                "ApprovalAdmission fingerprint does not match immutable authority content",
            )

    @staticmethod
    def _validate_admission_expiry(request: ApprovalConsumptionRequest) -> None:
        if _parse_utc(request.consumed_at) >= _parse_utc(request.admission.expires_at):
            _error(
                "APPROVAL_ADMISSION_EXPIRED",
                "ApprovalAdmission is not valid at consumed_at",
            )

    @staticmethod
    def _validate_scope_integrity(boundary: ApprovalScopeBoundary) -> None:
        try:
            validate_approval_scope_boundary(boundary)
        except ApprovalScopeError as exc:
            _error(
                "APPROVAL_INTEGRITY_INVALID",
                "Step28 ApprovalScopeBoundary integrity validation failed",
                upstream_code=exc.code,
            )

    @staticmethod
    def _validate_changeset_integrity(
        changeset: CanonicalChangeSet,
        boundary: ApprovalScopeBoundary,
    ) -> None:
        try:
            validate_changeset_integrity(changeset, boundary)
        except ChangeSetError as exc:
            _error(
                "APPROVAL_INTEGRITY_INVALID",
                "Step29 CanonicalChangeSet integrity validation failed",
                upstream_code=exc.code,
            )

    @staticmethod
    def _validate_approval_join(request: ApprovalConsumptionRequest) -> None:
        admission = request.admission
        changeset = request.canonical_changeset
        boundary = request.approval_scope_boundary

        if not (
            admission.changeset_hash
            == changeset.changeset_hash
            == boundary.changeset_hash
        ):
            _error(
                "APPROVAL_SCOPE_MISMATCH",
                "ApprovalAdmission, ChangeSet, and Boundary changeset hashes differ",
            )
        if (
            changeset.approval_scope_definition_ref.scope_body_hash
            != boundary.scope_body_hash
        ):
            _error(
                "APPROVAL_SCOPE_MISMATCH",
                "ChangeSet scope body does not match final ApprovalScopeBoundary",
            )
        if admission.approved_scope_hash != boundary.scope_hash:
            _error(
                "APPROVAL_SCOPE_MISMATCH",
                "ApprovalAdmission approved scope does not match final Boundary",
            )
        if not (
            admission.semantic_environment_ref
            == changeset.semantic_environment_ref
            == boundary.semantic_environment_ref
        ):
            _error(
                "SEMANTIC_ENVIRONMENT_MISMATCH",
                "approval semantic environments do not match exactly",
            )

    @staticmethod
    def _least_privilege_operations(
        request: ApprovalConsumptionRequest,
    ) -> tuple[str, ...]:
        changeset = request.canonical_changeset
        operations = tuple(
            sorted(
                {
                    changeset.root_operation.canonical_operation,
                    *(
                        operation.canonical_operation
                        for operation in changeset.derived_operations
                    ),
                }
            )
        )
        if not set(operations).issubset(request.admission.policy_allowed_operations):
            _error(
                "APPROVAL_OPERATION_FORBIDDEN",
                "ChangeSet contains canonical operations outside policy authority",
            )
        return operations

    @staticmethod
    def _build_approval_record(
        request: ApprovalConsumptionRequest,
        allowed_operations: tuple[str, ...],
    ) -> ApprovalRecord:
        admission = request.admission
        approval_hash = compute_approval_hash(
            admission_fingerprint=admission.admission_fingerprint,
            changeset_hash=admission.changeset_hash,
            approved_scope_hash=admission.approved_scope_hash,
            semantic_environment_ref=admission.semantic_environment_ref,
            approver=admission.approver,
            policy_snapshot_hash=admission.policy_snapshot_hash,
            allowed_operations=allowed_operations,
            approved_at=admission.approved_at,
        )
        return ApprovalRecord(
            approval_id=f"AR-{approval_hash[:12]}",
            admission_id=admission.admission_id,
            admission_fingerprint=admission.admission_fingerprint,
            changeset_hash=admission.changeset_hash,
            approved_scope_hash=admission.approved_scope_hash,
            semantic_environment_ref=admission.semantic_environment_ref,
            approver=admission.approver,
            policy_snapshot_hash=admission.policy_snapshot_hash,
            allowed_operations=allowed_operations,
            approved_at=admission.approved_at,
            consumed_at=request.consumed_at,
            approval_hash=approval_hash,
        )


__all__ = ["GatewayAuthorizationService"]
