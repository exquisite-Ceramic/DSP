"""Step33 authoritative provider-neutral ActualDelta contract tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_approval_scope import CanonicalAspect
from design_execution_reconciliation import (
    ActualChange,
    ActualChangeKind,
    ActualDelta,
    ReconciliationError,
    compute_actual_change_hash,
    compute_actual_delta_hash,
    validate_actual_delta_integrity,
)
from host_contracts import HostEntityRef


D = "a" * 64


def _signed_change(**changes) -> ActualChange:
    draft = ActualChange(actual_change_hash="0" * 64, **changes)
    return replace(draft, actual_change_hash=compute_actual_change_hash(draft))


def _signed_delta(*changes: ActualChange, **overrides) -> ActualDelta:
    values = {
        "actual_delta_id": "AD-TEST",
        "grant_hash": "1" * 64,
        "binding_set_hash": "2" * 64,
        "execution_slice_hash": "3" * 64,
        "changeset_hash": "4" * 64,
        "approved_scope_hash": "5" * 64,
        "host_instance_id": "HOST-1",
        "document_ref": "DOC-1",
        "revision_before": 10,
        "revision_after": 11,
        "changes": tuple(changes),
        "actual_delta_hash": "0" * 64,
    }
    values.update(overrides)
    draft = ActualDelta(**values)
    return replace(draft, actual_delta_hash=compute_actual_delta_hash(draft))


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ReconciliationError) as exc:
        operation()
    assert exc.value.code == code


def test_actual_change_kind_is_frozen() -> None:
    assert tuple(item.value for item in ActualChangeKind) == (
        "CREATE",
        "MODIFY",
        "DELETE",
    )


def test_modify_requires_semantic_id_and_changed_aspect() -> None:
    with pytest.raises(ValueError):
        ActualChange(
            ActualChangeKind.MODIFY,
            changed_aspects=(CanonicalAspect.PROPERTIES,),
            actual_change_hash=D,
        )
    with pytest.raises(ValueError):
        ActualChange(
            ActualChangeKind.MODIFY,
            semantic_id="WALL-1",
            actual_change_hash=D,
        )


def test_delete_requires_semantic_id() -> None:
    with pytest.raises(ValueError):
        ActualChange(ActualChangeKind.DELETE, actual_change_hash=D)


def test_create_requires_operation_and_stable_instance_discriminator() -> None:
    with pytest.raises(ValueError):
        ActualChange(
            ActualChangeKind.CREATE,
            semantic_id="NEW-1",
            actual_change_hash=D,
        )
    with pytest.raises(ValueError):
        ActualChange(
            ActualChangeKind.CREATE,
            canonical_operation="copy.v1",
            actual_change_hash=D,
        )


def test_create_accepts_provider_neutral_source_evidence() -> None:
    change = _signed_change(
        change_kind=ActualChangeKind.CREATE,
        semantic_id="NEW-1",
        canonical_kind="ifc:IfcWall",
        canonical_operation="copy.v1",
        source_execution_unit_hash="6" * 64,
        source_semantic_id="WALL-1",
        source_canonical_kind="ifc:IfcWall",
        derivation_rule="RULE-COPY",
    )
    assert change.source_semantic_id == "WALL-1"
    assert change.source_canonical_kind == "ifc:IfcWall"
    assert change.derivation_rule == "RULE-COPY"


def test_host_native_type_does_not_change_actual_change_identity() -> None:
    line = _signed_change(
        change_kind=ActualChangeKind.CREATE,
        canonical_operation="copy.v1",
        host_entity_ref=HostEntityRef("DOC-1", "42", "LINE"),
    )
    arc = _signed_change(
        change_kind=ActualChangeKind.CREATE,
        canonical_operation="copy.v1",
        host_entity_ref=HostEntityRef("DOC-1", "42", "ARC"),
    )
    assert line.actual_change_hash == arc.actual_change_hash


def test_semantic_identity_makes_native_provenance_non_authoritative() -> None:
    first = _signed_change(
        change_kind=ActualChangeKind.CREATE,
        semantic_id="NEW-1",
        canonical_operation="copy.v1",
        host_entity_ref=HostEntityRef("DOC-1", "42", "LINE"),
    )
    second = _signed_change(
        change_kind=ActualChangeKind.CREATE,
        semantic_id="NEW-1",
        canonical_operation="copy.v1",
        host_entity_ref=HostEntityRef("DOC-1", "99", "ARC"),
    )
    assert first.actual_change_hash == second.actual_change_hash


def test_changed_aspect_order_does_not_change_identity() -> None:
    forward = _signed_change(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id="WALL-1",
        changed_aspects=(CanonicalAspect.PROPERTIES, CanonicalAspect.GEOMETRY),
    )
    reverse = _signed_change(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id="WALL-1",
        changed_aspects=(CanonicalAspect.GEOMETRY, CanonicalAspect.PROPERTIES),
    )
    assert forward.actual_change_hash == reverse.actual_change_hash
    assert forward.changed_aspects == reverse.changed_aspects


def test_revision_regression_fails_closed() -> None:
    _assert_code(
        "RECONCILIATION_REVISION_INVALID",
        lambda: ActualDelta(
            actual_delta_id="AD-BAD",
            grant_hash="1" * 64,
            binding_set_hash="2" * 64,
            execution_slice_hash="3" * 64,
            changeset_hash="4" * 64,
            approved_scope_hash="5" * 64,
            host_instance_id="HOST-1",
            document_ref="DOC-1",
            revision_before=12,
            revision_after=11,
            changes=(),
            actual_delta_hash="0" * 64,
        ),
    )


def test_host_identity_document_must_match_delta_document() -> None:
    change = _signed_change(
        change_kind=ActualChangeKind.CREATE,
        canonical_operation="copy.v1",
        host_entity_ref=HostEntityRef("DOC-OTHER", "42", "LINE"),
    )
    delta = _signed_delta(change)
    _assert_code(
        "ACTUAL_DELTA_INPUT_INVALID",
        lambda: validate_actual_delta_integrity(delta),
    )


def test_same_committed_revision_and_effects_rehash_identically() -> None:
    change = _signed_change(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id="WALL-1",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    first = _signed_delta(change, actual_delta_id="AD-FIRST")
    replay = _signed_delta(change, actual_delta_id="AD-REPLAY")
    assert first.actual_delta_hash == replay.actual_delta_hash


def test_actual_delta_change_input_order_is_semantically_stable() -> None:
    wall = _signed_change(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id="WALL-1",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    door = _signed_change(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id="DOOR-1",
        changed_aspects=(CanonicalAspect.PLACEMENT,),
    )
    assert _signed_delta(wall, door).actual_delta_hash == _signed_delta(
        door, wall
    ).actual_delta_hash


def test_tampered_change_hash_fails_integrity() -> None:
    change = _signed_change(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id="WALL-1",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    delta = _signed_delta(replace(change, actual_change_hash="f" * 64))
    _assert_code(
        "ACTUAL_DELTA_INTEGRITY_INVALID",
        lambda: validate_actual_delta_integrity(delta),
    )


def test_tampered_delta_hash_fails_integrity() -> None:
    change = _signed_change(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id="WALL-1",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    delta = replace(_signed_delta(change), actual_delta_hash="f" * 64)
    _assert_code(
        "ACTUAL_DELTA_INTEGRITY_INVALID",
        lambda: validate_actual_delta_integrity(delta),
    )
