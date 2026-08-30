"""Frozen Step32-only authorization hashing semantics."""

from __future__ import annotations

from inspect import signature

from design_gateway_authorization import (
    ApprovalAdmission,
    compute_admission_fingerprint,
    compute_approval_hash,
    compute_grant_hash,
)


def _admission(*, operations=("move.v1", "copy.v1"), approved_at="2026-08-30T07:00:00Z"):
    draft = ApprovalAdmission(
        admission_id="ADM-1",
        changeset_hash="a" * 64,
        approved_scope_hash="b" * 64,
        semantic_environment_ref="ENV-1",
        approver="user:42",
        policy_snapshot_hash="c" * 64,
        policy_allowed_operations=operations,
        approved_at=approved_at,
        expires_at="2026-08-30T08:00:00Z",
        admission_fingerprint="d" * 64,
    )
    return draft


def _approval_hash(*, approved_at="2026-08-30T07:00:00Z", operations=("move.v1", "copy.v1")):
    return compute_approval_hash(
        admission_fingerprint="1" * 64,
        changeset_hash="2" * 64,
        approved_scope_hash="3" * 64,
        semantic_environment_ref="ENV-1",
        approver="user:42",
        policy_snapshot_hash="4" * 64,
        allowed_operations=operations,
        approved_at=approved_at,
    )


def _grant_hash(*, issued_at="2026-08-30T07:10:00Z", operations=("move.v1", "copy.v1")):
    return compute_grant_hash(
        approval_hash="1" * 64,
        changeset_hash="2" * 64,
        approved_scope_hash="3" * 64,
        execution_slice_hash="4" * 64,
        binding_set_hash="5" * 64,
        host_instance_id="RVT-01",
        allowed_operations=operations,
        issued_at=issued_at,
        expires_at="2026-08-30T07:55:00Z",
    )


def test_admission_fingerprint_is_order_deterministic_and_ignores_admission_id() -> None:
    left = _admission(operations=("move.v1", "copy.v1"))
    right = ApprovalAdmission(
        admission_id="ADM-OTHER",
        changeset_hash=left.changeset_hash,
        approved_scope_hash=left.approved_scope_hash,
        semantic_environment_ref=left.semantic_environment_ref,
        approver=left.approver,
        policy_snapshot_hash=left.policy_snapshot_hash,
        policy_allowed_operations=("copy.v1", "move.v1"),
        approved_at=left.approved_at,
        expires_at=left.expires_at,
        admission_fingerprint="e" * 64,
    )
    assert compute_admission_fingerprint(left) == compute_admission_fingerprint(right)


def test_approval_hash_excludes_construction_consumption_and_lifecycle_fields() -> None:
    parameters = set(signature(compute_approval_hash).parameters)
    assert "approval_id" not in parameters
    assert "admission_id" not in parameters
    assert "consumed_at" not in parameters
    assert "state" not in parameters
    assert "revoked_at" not in parameters


def test_approval_hash_is_order_deterministic_but_approved_at_is_material() -> None:
    assert _approval_hash(operations=("move.v1", "copy.v1")) == _approval_hash(
        operations=("copy.v1", "move.v1")
    )
    assert _approval_hash() != _approval_hash(approved_at="2026-08-30T07:00:01Z")


def test_grant_hash_excludes_construction_and_lifecycle_fields() -> None:
    parameters = set(signature(compute_grant_hash).parameters)
    assert "grant_id" not in parameters
    assert "approval_id" not in parameters
    assert "execution_slice_id" not in parameters
    assert "state" not in parameters
    assert "admitted_at" not in parameters
    assert "revoked_at" not in parameters
    assert "superseded_by_grant_id" not in parameters


def test_grant_hash_is_order_deterministic_and_issued_at_is_material() -> None:
    assert _grant_hash(operations=("move.v1", "copy.v1")) == _grant_hash(
        operations=("copy.v1", "move.v1")
    )
    assert _grant_hash() != _grant_hash(issued_at="2026-08-30T07:10:01Z")
