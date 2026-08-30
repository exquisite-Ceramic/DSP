"""Authoritative ExecutionGrant validation and construction for Step32."""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_planning import (
    compute_execution_slice_hash,
    compute_execution_unit_hash,
)
from design_gateway_authorization import (
    ApprovalLifecycle,
    ApprovalState,
    ExecutionGrantRequest,
    GatewayAuthorizationError,
    GatewayAuthorizationService,
    StoredApproval,
    compute_approval_hash,
    compute_grant_hash,
)
from design_provider_binding import (
    compute_binding_hash,
    compute_binding_set_hash,
)


class StaticGrantStore:
    def __init__(self, stored_approval) -> None:
        self.stored_approval = stored_approval
        self.grants = []

    def consume_admission_once(self, admission_id, admission_fingerprint, approval_record):
        return approval_record

    def get_approval(self, approval_id):
        if self.stored_approval.record.approval_id != approval_id:
            return None
        return self.stored_approval

    def issue_or_get_grant(self, grant):
        self.grants.append(grant)
        return grant


def _assert_error(code, service, request, *, upstream_code=None):
    with pytest.raises(GatewayAuthorizationError) as exc:
        service.issue_execution_grant(request)
    assert exc.value.code == code
    if upstream_code is not None:
        assert exc.value.upstream_code == upstream_code


def _slice_with_changeset_hash(execution_slice, changeset_hash):
    units = []
    for unit in execution_slice.execution_units:
        unit_hash = compute_execution_unit_hash(
            changeset_hash=changeset_hash,
            source_operation_hash=unit.source_operation_hash,
            canonical_operation=unit.canonical_operation,
            canonical_operation_version=unit.canonical_operation_version,
            canonical_definition_fingerprint=unit.canonical_definition_fingerprint,
            targets=unit.targets,
            arguments=unit.arguments,
            preconditions=unit.preconditions,
            expected_effects=unit.expected_effects,
        )
        units.append(
            replace(
                unit,
                execution_unit_id=f"EU-{unit_hash[:12]}",
                execution_unit_hash=unit_hash,
            )
        )
    slice_hash = compute_execution_slice_hash(
        changeset_hash=changeset_hash,
        scope_hash=execution_slice.approved_scope_ref.scope_hash,
        execution_slice_scope_rule_id=(
            execution_slice.approved_scope_ref.execution_slice_scope_rule_id
        ),
        host_runtime_ref=execution_slice.host_runtime_ref,
        execution_unit_hashes=(unit.execution_unit_hash for unit in units),
    )
    return replace(
        execution_slice,
        changeset_hash=changeset_hash,
        execution_units=tuple(units),
        execution_slice_id=f"XS-{slice_hash[:12]}",
        execution_slice_hash=slice_hash,
    )


def _slice_with_scope_hash(execution_slice, scope_hash):
    scope_ref = replace(execution_slice.approved_scope_ref, scope_hash=scope_hash)
    slice_hash = compute_execution_slice_hash(
        changeset_hash=execution_slice.changeset_hash,
        scope_hash=scope_hash,
        execution_slice_scope_rule_id=scope_ref.execution_slice_scope_rule_id,
        host_runtime_ref=execution_slice.host_runtime_ref,
        execution_unit_hashes=(
            unit.execution_unit_hash for unit in execution_slice.execution_units
        ),
    )
    return replace(
        execution_slice,
        approved_scope_ref=scope_ref,
        execution_slice_id=f"XS-{slice_hash[:12]}",
        execution_slice_hash=slice_hash,
    )


def _binding_with_host(binding, host_instance_id):
    binding_hash = compute_binding_hash(
        execution_unit_hash=binding.execution_unit_hash,
        execution_slice_hash=binding.execution_slice_hash,
        canonical_operation=binding.canonical_operation,
        provider_server=binding.provider_server,
        provider_tool=binding.provider_tool,
        provider_version=binding.provider_version,
        selected_candidate_fingerprint=binding.selected_candidate_fingerprint,
        host_instance_id=host_instance_id,
        document_ref=binding.document_ref,
        input_adapter_version=binding.input_adapter_version,
        native_targets=binding.native_targets,
        provider_arguments=binding.provider_arguments,
        provider_preconditions=binding.provider_preconditions,
        native_binding_metadata=binding.native_binding_metadata,
        verification_contract=binding.verification_contract,
        rollback_contract=binding.rollback_contract,
        binding_expires_at=binding.binding_expires_at,
    )
    return replace(
        binding,
        host_instance_id=host_instance_id,
        binding_id=f"PB-{binding_hash[:12]}",
        binding_hash=binding_hash,
    )


def _binding_set_with_bindings(binding_set, bindings):
    binding_set_hash = compute_binding_set_hash(
        execution_slice_hash=binding_set.execution_slice_hash,
        binding_hashes=(binding.binding_hash for binding in bindings),
    )
    return replace(
        binding_set,
        bindings=tuple(bindings),
        binding_set_id=f"PBS-{binding_set_hash[:12]}",
        binding_set_hash=binding_set_hash,
    )


def test_unknown_approval_is_rejected(gateway_cross_step) -> None:
    store, _approval, _slice, _bindings, request = gateway_cross_step
    _assert_error(
        "APPROVAL_RECORD_NOT_FOUND",
        GatewayAuthorizationService(store),
        replace(request, approval_id="AR-MISSING"),
    )


def test_revoked_approval_is_rejected(gateway_cross_step) -> None:
    _store, approval, _slice, _bindings, request = gateway_cross_step
    stored = StoredApproval(approval, ApprovalLifecycle(ApprovalState.REVOKED))
    service = GatewayAuthorizationService(StaticGrantStore(stored))
    _assert_error("APPROVAL_REVOKED", service, request)


def test_step30_integrity_failure_maps_with_upstream_detail(gateway_cross_step) -> None:
    store, _approval, execution_slice, _bindings, request = gateway_cross_step
    unit = execution_slice.execution_units[0]
    bad_unit = replace(unit, arguments={**dict(unit.arguments), "tampered": True})
    bad_slice = replace(
        execution_slice,
        execution_units=(bad_unit, *execution_slice.execution_units[1:]),
    )
    _assert_error(
        "EXECUTION_GRANT_SLICE_MISMATCH",
        GatewayAuthorizationService(store),
        replace(request, execution_slice=bad_slice),
        upstream_code="EXECUTION_UNIT_INTEGRITY_INVALID",
    )


def test_slice_changeset_must_match_approval(gateway_cross_step) -> None:
    store, _approval, execution_slice, _bindings, request = gateway_cross_step
    bad_slice = _slice_with_changeset_hash(execution_slice, "e" * 64)
    _assert_error(
        "EXECUTION_GRANT_SLICE_MISMATCH",
        GatewayAuthorizationService(store),
        replace(request, execution_slice=bad_slice),
    )


def test_slice_scope_must_match_approval(gateway_cross_step) -> None:
    store, _approval, execution_slice, _bindings, request = gateway_cross_step
    bad_slice = _slice_with_scope_hash(execution_slice, "e" * 64)
    _assert_error(
        "EXECUTION_GRANT_SLICE_MISMATCH",
        GatewayAuthorizationService(store),
        replace(request, execution_slice=bad_slice),
    )


def test_step31_binding_integrity_failure_is_mapped(gateway_cross_step) -> None:
    store, _approval, _slice, binding_set, request = gateway_cross_step
    bad_set = replace(binding_set, binding_set_hash="e" * 64)
    _assert_error(
        "EXECUTION_GRANT_BINDING_MISMATCH",
        GatewayAuthorizationService(store),
        replace(request, provider_binding_set=bad_set),
        upstream_code="PROVIDER_BINDING_SET_INVALID",
    )


def test_binding_set_must_reference_exact_slice(gateway_cross_step) -> None:
    store, _approval, _slice, binding_set, request = gateway_cross_step
    bad_set = replace(binding_set, execution_slice_id="XS-OTHER")
    _assert_error(
        "EXECUTION_GRANT_BINDING_MISMATCH",
        GatewayAuthorizationService(store),
        replace(request, provider_binding_set=bad_set),
    )


def test_binding_hosts_must_match_slice_host(gateway_cross_step) -> None:
    store, _approval, _slice, binding_set, request = gateway_cross_step
    bad_binding = _binding_with_host(binding_set.bindings[0], "RVT-OTHER")
    bad_set = _binding_set_with_bindings(
        binding_set,
        (bad_binding, *binding_set.bindings[1:]),
    )
    _assert_error(
        "EXECUTION_GRANT_BINDING_MISMATCH",
        GatewayAuthorizationService(store),
        replace(request, provider_binding_set=bad_set),
    )


def test_slice_operation_must_be_allowed_by_approval(gateway_cross_step) -> None:
    _store, approval, _slice, _bindings, request = gateway_cross_step
    approval_hash = compute_approval_hash(
        admission_fingerprint=approval.admission_fingerprint,
        changeset_hash=approval.changeset_hash,
        approved_scope_hash=approval.approved_scope_hash,
        semantic_environment_ref=approval.semantic_environment_ref,
        approver=approval.approver,
        policy_snapshot_hash=approval.policy_snapshot_hash,
        allowed_operations=("copy.v1",),
        approved_at=approval.approved_at,
    )
    restricted = replace(
        approval,
        approval_id=f"AR-{approval_hash[:12]}",
        allowed_operations=("copy.v1",),
        approval_hash=approval_hash,
    )
    stored = StoredApproval(restricted, ApprovalLifecycle(ApprovalState.ACTIVE))
    service = GatewayAuthorizationService(StaticGrantStore(stored))
    _assert_error(
        "EXECUTION_GRANT_OPERATION_FORBIDDEN",
        service,
        replace(request, approval_id=restricted.approval_id),
    )


def test_issued_at_at_binding_expiry_is_rejected(gateway_cross_step) -> None:
    store, _approval, _slice, binding_set, request = gateway_cross_step
    expires_at = min(binding.binding_expires_at for binding in binding_set.bindings)
    _assert_error(
        "EXECUTION_BINDING_EXPIRED",
        GatewayAuthorizationService(store),
        replace(request, issued_at=expires_at),
    )


def test_valid_grant_uses_exact_slice_authority_and_minimum_binding_expiry(
    gateway_cross_step,
) -> None:
    store, approval, execution_slice, binding_set, request = gateway_cross_step
    grant = GatewayAuthorizationService(store).issue_execution_grant(request)
    expected_operations = tuple(
        sorted({unit.canonical_operation for unit in execution_slice.execution_units})
    )
    expected_expiry = min(binding.binding_expires_at for binding in binding_set.bindings)
    assert grant.approval_id == approval.approval_id
    assert grant.approval_hash == approval.approval_hash
    assert grant.changeset_hash == execution_slice.changeset_hash
    assert grant.approved_scope_hash == execution_slice.approved_scope_ref.scope_hash
    assert grant.execution_slice_id == execution_slice.execution_slice_id
    assert grant.execution_slice_hash == execution_slice.execution_slice_hash
    assert grant.binding_set_hash == binding_set.binding_set_hash
    assert grant.host_instance_id == execution_slice.host_runtime_ref.host_instance_id
    assert grant.allowed_operations == expected_operations
    assert grant.expires_at == expected_expiry
    assert grant.grant_id == f"EG-{grant.grant_hash[:12]}"
    assert grant.grant_hash == compute_grant_hash(
        approval_hash=grant.approval_hash,
        changeset_hash=grant.changeset_hash,
        approved_scope_hash=grant.approved_scope_hash,
        execution_slice_hash=grant.execution_slice_hash,
        binding_set_hash=grant.binding_set_hash,
        host_instance_id=grant.host_instance_id,
        allowed_operations=grant.allowed_operations,
        issued_at=grant.issued_at,
        expires_at=grant.expires_at,
    )
