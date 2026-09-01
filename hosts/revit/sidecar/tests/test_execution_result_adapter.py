from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from design_approval_scope import CanonicalAspect
from design_execution_coordination import (
    HostCommitted,
    HostFailed,
    HostFailurePhase,
)
from design_execution_reconciliation import (
    ActualChange,
    ActualChangeKind,
    compute_actual_change_hash,
    compute_actual_delta_hash,
)
from design_gateway_authorization import AdmittedExecutionAuthority
from revit_sidecar.execution_result_adapter import (
    CommittedEffectUnnormalizableError,
    RevitExecutionResultAdapter,
)


def _authority() -> AdmittedExecutionAuthority:
    return AdmittedExecutionAuthority(
        approval_hash="a" * 64,
        grant_hash="b" * 64,
        changeset_hash="c" * 64,
        approved_scope_hash="d" * 64,
        execution_slice_hash="e" * 64,
        binding_set_hash="f" * 64,
        host_instance_id="HOST-REVIT-A",
        admitted_at="2026-09-01T00:00:00Z",
    )


def _success_result() -> dict:
    return {
        "command_id": "CMD-REVIT-001",
        "status": "OK",
        "revision_after": 11,
        "payload": {
            "wall_unique_id": "wall-unique-id",
            "wall_type_unique_id": "wall-type-unique-id",
            "editable_layer_index": 1,
            "width_before_internal": 0.5,
            "width_after_internal": 0.984251968503937,
            "width_after_mm": 300.0,
            "requested_width_mm": 300.0,
            "transaction_attempt_count": 1,
        },
        "verification": {
            "identity_invariant_proven": True,
            "location_invariant_proven": True,
            "relationship_invariant_proven": True,
            "document_change_observed": True,
            "revision_before": 10,
            "revision_after": 11,
            "location_signature_before": "Line|0|0|0|10|0|0",
            "location_signature_after": "Line|0|0|0|10|0|0",
            "relationship_signature_before": "isolated",
            "relationship_signature_after": "isolated",
        },
        "replayed": False,
    }


def _adapt(host_result: dict):
    return RevitExecutionResultAdapter.adapt(
        admitted_authority=_authority(),
        document_ref="DOC-REVIT",
        approved_semantic_wall_id="WALL-001",
        host_result=host_result,
        occurred_at="2026-09-01T00:00:00Z",
    )


def test_success_projects_one_signed_properties_change_with_exact_lineage() -> None:
    result = _adapt(_success_result())

    assert isinstance(result, HostCommitted)
    delta = result.actual_delta
    assert delta.grant_hash == "b" * 64
    assert delta.binding_set_hash == "f" * 64
    assert delta.execution_slice_hash == "e" * 64
    assert delta.changeset_hash == "c" * 64
    assert delta.approved_scope_hash == "d" * 64
    assert delta.host_instance_id == "HOST-REVIT-A"
    assert delta.document_ref == "DOC-REVIT"
    assert delta.revision_before == 10
    assert delta.revision_after == 11
    assert len(delta.changes) == 1

    change = delta.changes[0]
    assert change.change_kind is ActualChangeKind.MODIFY
    assert change.semantic_id == "WALL-001"
    assert change.canonical_kind == "ifc:IfcWall"
    assert change.changed_aspects == (CanonicalAspect.PROPERTIES,)
    assert change.host_entity_ref is None

    unsigned_change = replace(change, actual_change_hash="0" * 64)
    assert change.actual_change_hash == compute_actual_change_hash(unsigned_change)
    unsigned_delta = replace(delta, actual_delta_hash="0" * 64)
    assert delta.actual_delta_hash == compute_actual_delta_hash(unsigned_delta)

    material = repr(delta)
    for forbidden in (
        "WallType",
        "CompoundStructure",
        "ElementId",
        "Revit API",
        "layer index",
    ):
        assert forbidden not in material


def test_native_regeneration_does_not_invent_geometry_change() -> None:
    host_result = _success_result()
    host_result["payload"]["native_regeneration_observed"] = True
    host_result["payload"]["solid_changed"] = True

    result = _adapt(host_result)

    assert isinstance(result, HostCommitted)
    assert tuple(
        aspect
        for change in result.actual_delta.changes
        for aspect in change.changed_aspects
    ) == (CanonicalAspect.PROPERTIES,)


def test_truthfully_normalized_wider_effects_are_retained() -> None:
    host_result = _success_result()
    host_result["verification"]["normalized_wider_effects"] = [
        {
            "semantic_id": "WALL-001",
            "canonical_kind": "ifc:IfcWall",
            "changed_aspects": ["PLACEMENT"],
        },
        {
            "semantic_id": "DOOR-001",
            "canonical_kind": "ifc:IfcDoor",
            "changed_aspects": ["RELATIONSHIPS"],
        },
    ]

    result = _adapt(host_result)

    assert isinstance(result, HostCommitted)
    observed = {
        (change.semantic_id, change.canonical_kind, change.changed_aspects)
        for change in result.actual_delta.changes
    }
    assert observed == {
        ("WALL-001", "ifc:IfcWall", (CanonicalAspect.PROPERTIES,)),
        ("WALL-001", "ifc:IfcWall", (CanonicalAspect.PLACEMENT,)),
        ("DOOR-001", "ifc:IfcDoor", (CanonicalAspect.RELATIONSHIPS,)),
    }
    for change in result.actual_delta.changes:
        unsigned = replace(change, actual_change_hash="0" * 64)
        assert change.actual_change_hash == compute_actual_change_hash(unsigned)


def test_precommit_failure_maps_only_to_before_commit() -> None:
    host_result = {
        "command_id": "CMD-REVIT-001",
        "status": "ERROR",
        "error": {
            "code": "WALL_JOIN_OUTSIDE_MVP",
            "commit_state": "BEFORE_COMMIT",
        },
        "revision_after": 10,
        "replayed": False,
    }

    result = _adapt(host_result)

    assert result == HostFailed(
        phase=HostFailurePhase.BEFORE_COMMIT,
        failure_ref="WALL_JOIN_OUTSIDE_MVP",
        failed_at="2026-09-01T00:00:00Z",
    )


def test_uncertain_commit_maps_only_to_commit_state_unknown() -> None:
    host_result = {
        "command_id": "CMD-REVIT-001",
        "status": "ERROR",
        "error": {
            "code": "REVIT_COMMIT_STATE_UNKNOWN",
            "commit_state": "COMMIT_STATE_UNKNOWN",
        },
        "revision_after": 10,
        "replayed": False,
    }

    result = _adapt(host_result)

    assert result == HostFailed(
        phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
        failure_ref="REVIT_COMMIT_STATE_UNKNOWN",
        failed_at="2026-09-01T00:00:00Z",
    )


def test_known_committed_unnormalizable_effect_is_a_design_stop() -> None:
    host_result = {
        "command_id": "CMD-REVIT-001",
        "status": "ERROR",
        "error": {
            "code": "COMMITTED_EFFECT_UNNORMALIZABLE",
            "commit_state": "KNOWN_COMMITTED",
        },
        "revision_after": 11,
        "replayed": False,
    }

    with pytest.raises(CommittedEffectUnnormalizableError) as exc_info:
        _adapt(deepcopy(host_result))

    assert exc_info.value.code == "COMMITTED_EFFECT_UNNORMALIZABLE"
