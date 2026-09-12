from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest
from design_approval_scope import (
    ApprovalScopeError,
    bind_changeset,
    bind_changeset_v2,
    bind_topology_snapshot_v2,
)
from design_changeset import (
    ChangeSetBuilder,
    ChangeSetError,
    validate_changeset_integrity,
    validate_changeset_integrity_v2,
)


def _load_builder_fixture():
    fixture_path = Path(__file__).with_name("test_step29_builder.py")
    spec = importlib.util.spec_from_file_location("_step29_materialization_v2_fixture", fixture_path)
    assert spec is not None and spec.loader is not None
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    return fixture


def _v2_transaction():
    fixture = _load_builder_fixture()
    request = fixture._request()
    scope_v2 = bind_topology_snapshot_v2(
        request.approval_scope_definition,
        topology_snapshot_hash="a" * 64,
    )
    changeset = ChangeSetBuilder().build(
        replace(request, approval_scope_definition=scope_v2)
    )
    boundary_v2 = bind_changeset_v2(
        scope_v2,
        changeset.changeset_hash,
        "SCOPE-29-V2",
    )
    return changeset, boundary_v2


def test_v2_integrity_reconstructs_existing_changeset_semantic_body():
    changeset, boundary_v2 = _v2_transaction()
    assert changeset.approval_scope_definition_ref.scope_body_hash == boundary_v2.scope_body_hash
    validate_changeset_integrity_v2(changeset, boundary_v2)


def test_v1_validator_rejects_v2_boundary_by_type():
    changeset, boundary_v2 = _v2_transaction()
    with pytest.raises(TypeError):
        validate_changeset_integrity(changeset, boundary_v2)


def test_v2_validator_rejects_v1_boundary_by_type():
    fixture = _load_builder_fixture()
    request = fixture._request()
    changeset = ChangeSetBuilder().build(request)
    boundary_v1 = bind_changeset(
        request.approval_scope_definition,
        changeset.changeset_hash,
        "SCOPE-29-V1",
    )
    with pytest.raises(TypeError):
        validate_changeset_integrity_v2(changeset, boundary_v1)


def test_v2_integrity_rejects_changeset_scope_body_tamper():
    changeset, boundary_v2 = _v2_transaction()
    tampered_ref = replace(
        changeset.approval_scope_definition_ref,
        scope_body_hash="f" * 64,
    )
    with pytest.raises(ChangeSetError) as exc:
        validate_changeset_integrity_v2(
            replace(changeset, approval_scope_definition_ref=tampered_ref),
            boundary_v2,
        )
    assert exc.value.code == "CHANGESET_INTEGRITY_INVALID"


def test_v2_integrity_rejects_topology_substitution_at_step28_owner_boundary():
    changeset, boundary_v2 = _v2_transaction()
    with pytest.raises(ApprovalScopeError) as exc:
        validate_changeset_integrity_v2(
            changeset,
            replace(boundary_v2, topology_snapshot_hash="b" * 64),
        )
    assert exc.value.code == "SCOPE_INTEGRITY_INVALID"
