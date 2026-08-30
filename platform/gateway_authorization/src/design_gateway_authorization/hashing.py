"""Canonical Step32-only hashing for Gateway authorization evidence."""

from __future__ import annotations

from typing import Any

from design_changeset import canonical_hash

from .contracts import ApprovalAdmission, _texts, _utc_timestamp


def compute_admission_fingerprint(admission: ApprovalAdmission) -> str:
    """Commit authoritative Admission content, excluding its one-time store id."""
    if not isinstance(admission, ApprovalAdmission):
        raise TypeError("admission must be ApprovalAdmission")
    return canonical_hash(
        {
            "changeset_hash": admission.changeset_hash,
            "approved_scope_hash": admission.approved_scope_hash,
            "semantic_environment_ref": admission.semantic_environment_ref,
            "approver": admission.approver,
            "policy_snapshot_hash": admission.policy_snapshot_hash,
            "policy_allowed_operations": sorted(admission.policy_allowed_operations),
            "approved_at": admission.approved_at,
            "expires_at": admission.expires_at,
        }
    )


def compute_approval_hash(
    *,
    admission_fingerprint: str,
    changeset_hash: str,
    approved_scope_hash: str,
    semantic_environment_ref: Any,
    approver: str,
    policy_snapshot_hash: str,
    allowed_operations,
    approved_at: str,
) -> str:
    """Commit immutable durable approval authority, excluding lifecycle/audit ids."""
    return canonical_hash(
        {
            "admission_fingerprint": admission_fingerprint,
            "changeset_hash": changeset_hash,
            "approved_scope_hash": approved_scope_hash,
            "semantic_environment_ref": semantic_environment_ref,
            "approver": approver,
            "policy_snapshot_hash": policy_snapshot_hash,
            "allowed_operations": list(
                _texts(allowed_operations, "allowed_operation", required=True)
            ),
            "approved_at": _utc_timestamp(approved_at, "approved_at"),
        }
    )


def compute_grant_hash(
    *,
    approval_hash: str,
    changeset_hash: str,
    approved_scope_hash: str,
    execution_slice_hash: str,
    binding_set_hash: str,
    host_instance_id: str,
    allowed_operations,
    issued_at: str,
    expires_at: str,
) -> str:
    """Commit immutable execution authority, excluding construction/lifecycle ids."""
    return canonical_hash(
        {
            "approval_hash": approval_hash,
            "changeset_hash": changeset_hash,
            "approved_scope_hash": approved_scope_hash,
            "execution_slice_hash": execution_slice_hash,
            "binding_set_hash": binding_set_hash,
            "host_instance_id": host_instance_id,
            "allowed_operations": list(
                _texts(allowed_operations, "allowed_operation", required=True)
            ),
            "issued_at": _utc_timestamp(issued_at, "issued_at"),
            "expires_at": _utc_timestamp(expires_at, "expires_at"),
        }
    )


__all__ = [
    "compute_admission_fingerprint",
    "compute_approval_hash",
    "compute_grant_hash",
]
