"""Frozen public contracts for Step32 Gateway authorization."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest
from design_gateway_authorization import (
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


def _field_names(contract) -> set[str]:
    return {field.name for field in fields(contract)}


def test_public_contract_field_sets_are_frozen() -> None:
    assert _field_names(ApprovalAdmission) == {
        "admission_id",
        "changeset_hash",
        "approved_scope_hash",
        "semantic_environment_ref",
        "approver",
        "policy_snapshot_hash",
        "policy_allowed_operations",
        "approved_at",
        "expires_at",
        "admission_fingerprint",
    }
    assert _field_names(ApprovalConsumptionRequest) == {
        "admission",
        "canonical_changeset",
        "approval_scope_boundary",
        "consumed_at",
    }
    assert _field_names(ApprovalRecord) == {
        "approval_id",
        "admission_id",
        "admission_fingerprint",
        "changeset_hash",
        "approved_scope_hash",
        "semantic_environment_ref",
        "approver",
        "policy_snapshot_hash",
        "allowed_operations",
        "approved_at",
        "consumed_at",
        "approval_hash",
    }
    assert _field_names(ApprovalLifecycle) == {
        "state",
        "revoked_at",
        "revocation_reason",
    }
    assert _field_names(StoredApproval) == {"record", "lifecycle"}
    assert _field_names(ExecutionGrantRequest) == {
        "approval_id",
        "execution_slice",
        "provider_binding_set",
        "issued_at",
    }
    assert _field_names(ExecutionGrant) == {
        "grant_id",
        "approval_id",
        "approval_hash",
        "changeset_hash",
        "approved_scope_hash",
        "execution_slice_id",
        "execution_slice_hash",
        "binding_set_hash",
        "host_instance_id",
        "allowed_operations",
        "issued_at",
        "expires_at",
        "grant_hash",
    }
    assert _field_names(GrantLifecycle) == {
        "state",
        "admitted_at",
        "revoked_at",
        "revocation_reason",
        "superseded_by_grant_id",
    }
    assert _field_names(StoredGrant) == {"grant", "lifecycle"}
    assert _field_names(AdmittedExecutionAuthority) == {
        "approval_hash",
        "grant_hash",
        "changeset_hash",
        "approved_scope_hash",
        "execution_slice_hash",
        "binding_set_hash",
        "host_instance_id",
        "admitted_at",
    }


def test_lifecycle_enums_are_closed_world() -> None:
    assert {state.value for state in ApprovalState} == {"ACTIVE", "REVOKED"}
    assert {state.value for state in GrantState} == {
        "ACTIVE",
        "ADMITTED",
        "REVOKED",
        "EXPIRED",
    }


def test_admission_normalizes_operations_and_utc_timestamps() -> None:
    admission = ApprovalAdmission(
        admission_id="ADM-1",
        changeset_hash="a" * 64,
        approved_scope_hash="b" * 64,
        semantic_environment_ref="ENV-1",
        approver="user:42",
        policy_snapshot_hash="c" * 64,
        policy_allowed_operations=("move.v1", "copy.v1", "move.v1"),
        approved_at="2026-08-30T07:00:00+00:00",
        expires_at="2026-08-30T08:00:00Z",
        admission_fingerprint="d" * 64,
    )
    assert admission.policy_allowed_operations == ("copy.v1", "move.v1")
    assert admission.approved_at == "2026-08-30T07:00:00Z"
    assert admission.expires_at == "2026-08-30T08:00:00Z"

    with pytest.raises(ValueError):
        ApprovalAdmission(
            admission_id="ADM-2",
            changeset_hash="a" * 64,
            approved_scope_hash="b" * 64,
            semantic_environment_ref="ENV-1",
            approver="user:42",
            policy_snapshot_hash="c" * 64,
            policy_allowed_operations=("move.v1",),
            approved_at="2026-08-30T07:00:00",
            expires_at="2026-08-30T08:00:00Z",
            admission_fingerprint="d" * 64,
        )


def test_authority_contracts_are_immutable() -> None:
    lifecycle = ApprovalLifecycle(ApprovalState.ACTIVE)
    with pytest.raises(FrozenInstanceError):
        lifecycle.state = ApprovalState.REVOKED


def test_gateway_error_carries_stable_upstream_code() -> None:
    error = GatewayAuthorizationError(
        "APPROVAL_INTEGRITY_INVALID",
        "invalid upstream evidence",
        upstream_code="SCOPE_INTEGRITY_INVALID",
    )
    assert error.code == "APPROVAL_INTEGRITY_INVALID"
    assert error.upstream_code == "SCOPE_INTEGRITY_INVALID"
