from __future__ import annotations

import inspect

from design_changeset import ChangePrecondition, PreconditionKind
from design_execution_planning import HostRuntimeRef, RuntimeEntityRoute


def _hashing():
    from design_execution_planning import hashing

    return hashing


def test_route_order_does_not_change_routing_hash() -> None:
    hashing = _hashing()
    first = RuntimeEntityRoute("A", HostRuntimeRef("REVIT", "RVT-1", "DOC"))
    second = RuntimeEntityRoute("B", HostRuntimeRef("REVIT", "RVT-1", "DOC"))

    assert hashing.compute_routing_snapshot_hash((first, second)) == hashing.compute_routing_snapshot_hash(
        (second, first)
    )


def test_identical_duplicate_route_does_not_change_routing_hash() -> None:
    hashing = _hashing()
    route = RuntimeEntityRoute("A", HostRuntimeRef("REVIT", "RVT-1", "DOC"))
    assert hashing.compute_routing_snapshot_hash((route,)) == hashing.compute_routing_snapshot_hash(
        (route, route)
    )


def test_execution_unit_hash_changes_with_semantic_material() -> None:
    hashing = _hashing()
    precondition = ChangePrecondition(
        PreconditionKind.OPERATION_FRESHNESS,
        "move.v1@1.0.0",
        "d" * 64,
    )
    common = {
        "changeset_hash": "a" * 64,
        "source_operation_hash": "b" * 64,
        "canonical_operation": "move.v1",
        "canonical_operation_version": "1.0.0",
        "canonical_definition_fingerprint": "c" * 64,
        "targets": ("WALL-001",),
        "preconditions": (precondition,),
        "expected_effects": ("PLACEMENT", "GEOMETRY"),
    }
    first = hashing.compute_execution_unit_hash(
        arguments={"targets": ["WALL-001"], "displacement": [100.0, 0.0, 0.0]},
        **common,
    )
    second = hashing.compute_execution_unit_hash(
        arguments={"targets": ["WALL-001"], "displacement": [101.0, 0.0, 0.0]},
        **common,
    )
    assert first != second


def test_slice_hash_is_unit_order_independent_and_host_sensitive() -> None:
    hashing = _hashing()
    common = {
        "changeset_hash": "a" * 64,
        "scope_hash": "b" * 64,
        "execution_slice_scope_rule_id": "SSR-1",
    }
    first = hashing.compute_execution_slice_hash(
        host_runtime_ref=HostRuntimeRef("REVIT", "RVT-1", "DOC"),
        execution_unit_hashes=("c" * 64, "d" * 64),
        **common,
    )
    reordered = hashing.compute_execution_slice_hash(
        host_runtime_ref=HostRuntimeRef("REVIT", "RVT-1", "DOC"),
        execution_unit_hashes=("d" * 64, "c" * 64),
        **common,
    )
    changed_host = hashing.compute_execution_slice_hash(
        host_runtime_ref=HostRuntimeRef("REVIT", "RVT-2", "DOC"),
        execution_unit_hashes=("c" * 64, "d" * 64),
        **common,
    )
    assert first == reordered
    assert first != changed_host


def test_plan_hash_binds_routing_slices_and_dependency_semantics() -> None:
    hashing = _hashing()
    common = {
        "changeset_hash": "a" * 64,
        "scope_hash": "b" * 64,
        "routing_snapshot_hash": "c" * 64,
        "execution_slice_hashes": ("d" * 64,),
    }
    first = hashing.compute_execution_plan_hash(
        execution_dependencies=(("EU-A", "EU-B", "reason-1"),),
        **common,
    )
    changed = hashing.compute_execution_plan_hash(
        execution_dependencies=(("EU-A", "EU-B", "reason-2"),),
        **common,
    )
    assert first != changed


def test_hash_helpers_do_not_accept_construction_ids() -> None:
    hashing = _hashing()
    for function_name in (
        "compute_execution_unit_hash",
        "compute_execution_slice_hash",
        "compute_execution_plan_hash",
    ):
        parameters = inspect.signature(getattr(hashing, function_name)).parameters
        assert "execution_unit_id" not in parameters
        assert "execution_slice_id" not in parameters
        assert "execution_plan_id" not in parameters
