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
from design_execution_planning import (
    ExecutionPlanningError,
    ExecutionSlice,
    validate_execution_slice_integrity,
)
from design_provider_binding import (
    ProviderBindingError,
    ProviderBindingSet,
    validate_provider_binding_set,
)

from .contracts import (
    AdmittedExecutionAuthority,
    ApprovalConsumptionRequest,
    ApprovalRecord,
    ApprovalState,
    ExecutionGrant,
    ExecutionGrantRequest,
    GatewayAuthorizationError,
    StoredApproval,
    StoredGrant,
)
from .hashing import (
    compute_admission_fingerprint,
    compute_approval_hash,
    compute_grant_hash,
)


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
    """Validate immutable approval and execution authority before store mutation."""

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

    def issue_execution_grant(self, request: ExecutionGrantRequest) -> ExecutionGrant:
        self._require_grant_request(request)
        get_approval = getattr(self._store, "get_approval", None)
        if not callable(get_approval):
            raise TypeError("store must provide get_approval")
        stored = get_approval(request.approval_id)
        if stored is None:
            _error("APPROVAL_RECORD_NOT_FOUND", "approval record not found")
        if stored.lifecycle.state is ApprovalState.REVOKED:
            _error("APPROVAL_REVOKED", "approval is revoked")

        self._validate_slice_integrity(request.execution_slice)
        self._validate_slice_approval_join(stored.record, request.execution_slice)
        self._validate_binding_set(
            request.provider_binding_set,
            request.execution_slice,
        )
        self._validate_host_consistency(
            request.execution_slice,
            request.provider_binding_set,
        )
        allowed_operations = self._validate_grant_operations(
            stored.record,
            request.execution_slice,
        )
        expires_at = self._derive_grant_expiry(
            request.provider_binding_set,
            request.issued_at,
        )
        grant = self._build_grant(
            stored.record,
            request,
            allowed_operations,
            expires_at,
        )
        issue_or_get_grant = getattr(self._store, "issue_or_get_grant", None)
        if not callable(issue_or_get_grant):
            raise TypeError("store must provide issue_or_get_grant")
        return issue_or_get_grant(grant)

    def admit_execution_grant(
        self,
        grant_hash: str,
        admitted_at: str,
    ) -> AdmittedExecutionAuthority:
        admit_grant = getattr(self._store, "admit_grant", None)
        if not callable(admit_grant):
            raise TypeError("store must provide admit_grant")
        return admit_grant(grant_hash, admitted_at)

    def revoke_approval(
        self,
        approval_id: str,
        revoked_at: str,
        reason: str,
    ) -> StoredApproval:
        revoke_approval = getattr(self._store, "revoke_approval", None)
        if not callable(revoke_approval):
            raise TypeError("store must provide revoke_approval")
        return revoke_approval(approval_id, revoked_at, reason)

    def revoke_execution_grant(
        self,
        grant_hash: str,
        revoked_at: str,
        reason: str,
    ) -> StoredGrant:
        revoke_grant = getattr(self._store, "revoke_grant", None)
        if not callable(revoke_grant):
            raise TypeError("store must provide revoke_grant")
        return revoke_grant(grant_hash, revoked_at, reason)

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
    def _require_grant_request(request: ExecutionGrantRequest) -> None:
        if not isinstance(request, ExecutionGrantRequest):
            _error(
                "EXECUTION_GRANT_INPUT_INVALID",
                "request must be ExecutionGrantRequest",
            )
        if not isinstance(request.execution_slice, ExecutionSlice):
            _error(
                "EXECUTION_GRANT_INPUT_INVALID",
                "execution_slice must be ExecutionSlice",
            )
        if not isinstance(request.provider_binding_set, ProviderBindingSet):
            _error(
                "EXECUTION_GRANT_INPUT_INVALID",
                "provider_binding_set must be ProviderBindingSet",
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
    def _validate_slice_integrity(execution_slice: ExecutionSlice) -> None:
        try:
            validate_execution_slice_integrity(execution_slice)
        except ExecutionPlanningError as exc:
            _error(
                "EXECUTION_GRANT_SLICE_MISMATCH",
                "Step30 ExecutionSlice integrity validation failed",
                upstream_code=exc.code,
            )

    @staticmethod
    def _validate_slice_approval_join(
        approval: ApprovalRecord,
        execution_slice: ExecutionSlice,
    ) -> None:
        if execution_slice.changeset_hash != approval.changeset_hash:
            _error(
                "EXECUTION_GRANT_SLICE_MISMATCH",
                "ExecutionSlice changeset does not match ApprovalRecord",
            )
        if execution_slice.approved_scope_ref.scope_hash != approval.approved_scope_hash:
            _error(
                "EXECUTION_GRANT_SLICE_MISMATCH",
                "ExecutionSlice scope does not match ApprovalRecord",
            )

    @staticmethod
    def _validate_binding_set(
        binding_set: ProviderBindingSet,
        execution_slice: ExecutionSlice,
    ) -> None:
        try:
            validate_provider_binding_set(binding_set, execution_slice)
        except ProviderBindingError as exc:
            _error(
                "EXECUTION_GRANT_BINDING_MISMATCH",
                "Step31 ProviderBindingSet validation failed",
                upstream_code=exc.code,
            )

    @staticmethod
    def _validate_host_consistency(
        execution_slice: ExecutionSlice,
        binding_set: ProviderBindingSet,
    ) -> None:
        expected_host = execution_slice.host_runtime_ref.host_instance_id
        if any(binding.host_instance_id != expected_host for binding in binding_set.bindings):
            _error(
                "EXECUTION_GRANT_BINDING_MISMATCH",
                "Provider bindings do not target the ExecutionSlice host instance",
            )

    @staticmethod
    def _validate_grant_operations(
        approval: ApprovalRecord,
        execution_slice: ExecutionSlice,
    ) -> tuple[str, ...]:
        operations = tuple(
            sorted({unit.canonical_operation for unit in execution_slice.execution_units})
        )
        if not set(operations).issubset(approval.allowed_operations):
            _error(
                "EXECUTION_GRANT_OPERATION_FORBIDDEN",
                "ExecutionSlice contains operations outside ApprovalRecord authority",
            )
        return operations

    @staticmethod
    def _derive_grant_expiry(
        binding_set: ProviderBindingSet,
        issued_at: str,
    ) -> str:
        expires_at = min(binding.binding_expires_at for binding in binding_set.bindings)
        if _parse_utc(issued_at) >= _parse_utc(expires_at):
            _error(
                "EXECUTION_BINDING_EXPIRED",
                "provider binding authority is expired at issued_at",
            )
        return expires_at

    @staticmethod
    def _build_grant(
        approval: ApprovalRecord,
        request: ExecutionGrantRequest,
        allowed_operations: tuple[str, ...],
        expires_at: str,
    ) -> ExecutionGrant:
        execution_slice = request.execution_slice
        binding_set = request.provider_binding_set
        grant_hash = compute_grant_hash(
            approval_hash=approval.approval_hash,
            changeset_hash=execution_slice.changeset_hash,
            approved_scope_hash=execution_slice.approved_scope_ref.scope_hash,
            execution_slice_hash=execution_slice.execution_slice_hash,
            binding_set_hash=binding_set.binding_set_hash,
            host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
            allowed_operations=allowed_operations,
            issued_at=request.issued_at,
            expires_at=expires_at,
        )
        return ExecutionGrant(
            grant_id=f"EG-{grant_hash[:12]}",
            approval_id=approval.approval_id,
            approval_hash=approval.approval_hash,
            changeset_hash=execution_slice.changeset_hash,
            approved_scope_hash=execution_slice.approved_scope_ref.scope_hash,
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            binding_set_hash=binding_set.binding_set_hash,
            host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
            allowed_operations=allowed_operations,
            issued_at=request.issued_at,
            expires_at=expires_at,
            grant_hash=grant_hash,
        )

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
