"""Step30 complete ExecutionPlan integrity reconstruction tests for Step33 handoff."""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_planning import (
    ExecutionPlanner,
    ExecutionPlanningError,
    ExecutionPlanningRequest,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
    compute_routing_snapshot_hash,
    validate_execution_plan_integrity,
)


def _plan(transaction, *, split_hosts: bool = False):
    changeset, boundary = transaction
    root_ref = HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    derived_ref = (
        HostRuntimeRef("REVIT", "RVT-02", "DOC-1")
        if split_hosts
        else root_ref
    )
    routes = [
        RuntimeEntityRoute(target, root_ref)
        for target in changeset.root_operation.targets
    ]
    for operation in changeset.derived_operations:
        routes.extend(
            RuntimeEntityRoute(target, derived_ref)
            for target in operation.targets
        )
    route_tuple = tuple(routes)
    routing = RuntimeRoutingEvidence(
        "RRS-PLAN-INTEGRITY",
        route_tuple,
        compute_routing_snapshot_hash(route_tuple),
    )
    return ExecutionPlanner().plan(
        ExecutionPlanningRequest(changeset, boundary, routing)
    )


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ExecutionPlanningError) as exc:
        operation()
    assert exc.value.code == code


def test_single_slice_execution_plan_passes_integrity(step30_transaction) -> None:
    validate_execution_plan_integrity(_plan(step30_transaction))


def test_cross_slice_execution_plan_passes_integrity(step30_transaction) -> None:
    plan = _plan(step30_transaction, split_hosts=True)
    assert len(plan.execution_slices) == 2
    validate_execution_plan_integrity(plan)


def test_tampered_slice_fails_through_slice_integrity(step30_transaction) -> None:
    plan = _plan(step30_transaction)
    execution_slice = plan.execution_slices[0]
    tampered_slice = replace(
        execution_slice,
        host_runtime_ref=replace(
            execution_slice.host_runtime_ref,
            host_instance_id="RVT-TAMPERED",
        ),
    )
    tampered = replace(plan, execution_slices=(tampered_slice,))

    _assert_code(
        "EXECUTION_SLICE_INTEGRITY_INVALID",
        lambda: validate_execution_plan_integrity(tampered),
    )


def test_dependency_endpoint_must_belong_to_plan(step30_transaction) -> None:
    plan = _plan(step30_transaction, split_hosts=True)
    dependency = plan.execution_dependencies[0]
    tampered = replace(
        plan,
        execution_dependencies=(
            replace(
                dependency,
                predecessor_execution_unit_id="EU-UNKNOWN-ENDPOINT",
            ),
        ),
    )

    _assert_code(
        "EXECUTION_PLAN_INTEGRITY_INVALID",
        lambda: validate_execution_plan_integrity(tampered),
    )


def test_duplicate_execution_unit_id_across_slices_fails(step30_transaction) -> None:
    plan = _plan(step30_transaction)
    duplicate_slice = plan.execution_slices[0]
    tampered = replace(
        plan,
        execution_slices=(duplicate_slice, duplicate_slice),
    )

    _assert_code(
        "EXECUTION_PLAN_INTEGRITY_INVALID",
        lambda: validate_execution_plan_integrity(tampered),
    )


def test_dependency_reason_tamper_fails_plan_hash(step30_transaction) -> None:
    plan = _plan(step30_transaction, split_hosts=True)
    dependency = plan.execution_dependencies[0]
    tampered = replace(
        plan,
        execution_dependencies=(
            replace(dependency, reason_ref="tampered-reason"),
        ),
    )

    _assert_code(
        "EXECUTION_PLAN_INTEGRITY_INVALID",
        lambda: validate_execution_plan_integrity(tampered),
    )


def test_routing_snapshot_hash_tamper_fails_plan_hash(step30_transaction) -> None:
    plan = _plan(step30_transaction)
    tampered = replace(plan, routing_snapshot_hash="f" * 64)

    _assert_code(
        "EXECUTION_PLAN_INTEGRITY_INVALID",
        lambda: validate_execution_plan_integrity(tampered),
    )


def test_semantically_equivalent_slice_order_is_accepted(step30_transaction) -> None:
    plan = _plan(step30_transaction, split_hosts=True)
    reordered = replace(
        plan,
        execution_slices=tuple(reversed(plan.execution_slices)),
    )

    validate_execution_plan_integrity(reordered)


def test_execution_plan_id_must_match_hash_prefix(step30_transaction) -> None:
    plan = _plan(step30_transaction)
    tampered = replace(plan, execution_plan_id="XP-not-the-hash")

    _assert_code(
        "EXECUTION_PLAN_INTEGRITY_INVALID",
        lambda: validate_execution_plan_integrity(tampered),
    )
