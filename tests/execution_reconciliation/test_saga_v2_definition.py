from __future__ import annotations

from dataclasses import fields

from design_execution_coordination import ReadinessBarrierStatus
from design_execution_reconciliation import (
    ExecutionSagaDefinitionV2,
    ExecutionSagaStatusV2,
    SagaConvergenceOutcome,
)

from tests.execution_reconciliation._support import definition


def test_v2_status_and_convergence_enums_are_exact() -> None:
    assert tuple(item.value for item in ExecutionSagaStatusV2) == (
        "READY",
        "EXECUTING",
        "PARTIALLY_COMMITTED",
        "CONVERGENCE_PENDING",
        "SUCCEEDED",
        "DIVERGED",
        "FAILED",
    )
    assert tuple(item.value for item in SagaConvergenceOutcome) == (
        "CONVERGED",
        "DIVERGED",
    )
    assert ReadinessBarrierStatus.READY.value == "READY"


def test_v2_definition_has_exact_materialization_lineage_fields() -> None:
    expected = {
        "saga_id",
        "changeset_hash",
        "approved_scope_hash",
        "semantic_environment_ref",
        "materialization_plan_hash",
        "required_set_hash",
        "execution_plan_hash",
        "ordered_slice_hashes",
        "slice_dependencies",
        "slice_validation_assignments",
        "saga_definition_hash",
    }
    assert {field.name for field in fields(ExecutionSagaDefinitionV2)} == expected


def test_phase_i_definition_preserves_frozen_host_order_and_required_set() -> None:
    ctx, saga_definition = definition()
    expected_slices = tuple(
        item.execution_slice_hash for item in ctx.execution_plan.execution_slices
    )

    assert saga_definition.changeset_hash == ctx.case.changeset.changeset_hash
    assert saga_definition.approved_scope_hash == ctx.case.boundary_v2.scope_hash
    assert (
        saga_definition.materialization_plan_hash
        == ctx.materialization_plan.materialization_plan_hash
    )
    assert saga_definition.required_set_hash == ctx.materialization_plan.required_set_hash
    assert saga_definition.execution_plan_hash == ctx.execution_plan.execution_plan_hash
    assert saga_definition.ordered_slice_hashes == expected_slices
    assert tuple(
        item.host_runtime_ref.host_type
        for item in ctx.execution_plan.execution_slices
    ) == ("autocad", "revit")


def test_each_required_materialization_receives_its_local_validation_assignment() -> None:
    ctx, saga_definition = definition()
    expected_task_ids = tuple(
        sorted(task.validation_task_id for task in ctx.case.changeset.validation_tasks)
    )
    assignments = {
        item.execution_slice_hash: item.validation_task_ids
        for item in saga_definition.slice_validation_assignments
    }

    assert set(assignments) == set(saga_definition.ordered_slice_hashes)
    assert all(
        assignments[slice_hash] == expected_task_ids
        for slice_hash in saga_definition.ordered_slice_hashes
    )


def test_phase_i_definition_encodes_sequential_materialization_dependency() -> None:
    _, saga_definition = definition()
    assert len(saga_definition.slice_dependencies) == 1
    dependency = saga_definition.slice_dependencies[0]
    assert dependency.predecessor_slice_hash == saga_definition.ordered_slice_hashes[0]
    assert dependency.successor_slice_hash == saga_definition.ordered_slice_hashes[1]
    assert dependency.reason_refs == ("MATERIALIZATION_ORDER",)
