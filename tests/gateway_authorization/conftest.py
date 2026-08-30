"""Shared Step32 Gateway authorization fixtures."""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest
from design_approval_scope import bind_changeset
from design_changeset import ChangeSetBuilder
from design_gateway_authorization import (
    ApprovalAdmission,
    ApprovalConsumptionRequest,
    compute_admission_fingerprint,
)


def _step29_request():
    fixture_path = Path(__file__).parents[1] / "changeset" / "test_step29_derived_builder.py"
    spec = importlib.util.spec_from_file_location("_step32_step29_fixture", fixture_path)
    assert spec is not None and spec.loader is not None
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    return fixtures._request()


def resign_admission(admission: ApprovalAdmission, **changes) -> ApprovalAdmission:
    draft = replace(admission, admission_fingerprint="0" * 64, **changes)
    return replace(
        draft,
        admission_fingerprint=compute_admission_fingerprint(draft),
    )


class SpyApprovalStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def consume_admission_once(self, admission_id, admission_fingerprint, approval_record):
        self.calls.append((admission_id, admission_fingerprint, approval_record))
        return approval_record


@pytest.fixture
def spy_store() -> SpyApprovalStore:
    return SpyApprovalStore()


@pytest.fixture
def valid_approval_request() -> ApprovalConsumptionRequest:
    build_request = _step29_request()
    changeset = ChangeSetBuilder().build(build_request)
    boundary = bind_changeset(
        build_request.approval_scope_definition,
        changeset.changeset_hash,
        "SCOPE-32-APPROVAL",
    )
    draft = ApprovalAdmission(
        admission_id="ADM-32",
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        semantic_environment_ref=changeset.semantic_environment_ref,
        approver="user:approver-32",
        policy_snapshot_hash="a" * 64,
        policy_allowed_operations=("copy.v1", "move.v1"),
        approved_at="2026-08-30T07:00:00Z",
        expires_at="2026-08-30T08:00:00Z",
        admission_fingerprint="0" * 64,
    )
    admission = replace(
        draft,
        admission_fingerprint=compute_admission_fingerprint(draft),
    )
    return ApprovalConsumptionRequest(
        admission=admission,
        canonical_changeset=changeset,
        approval_scope_boundary=boundary,
        consumed_at="2026-08-30T07:30:00Z",
    )
