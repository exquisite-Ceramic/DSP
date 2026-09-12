"""Phase I provider-neutral 物化流水线的离线正向集成证明。"""

from __future__ import annotations

from design_approval_scope import validate_approval_scope_boundary_v2
from design_changeset import validate_changeset_integrity_v2
from design_execution_coordination import MaterializedCoordinationStatus
from design_execution_planning import validate_execution_plan_v2
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    SagaConvergenceOutcome,
    SliceReconciliationStatusV2,
)
from design_materialization_planning import (
    compute_materialization_intent_hash,
    compute_materialization_plan_hash,
    compute_required_set_hash,
)
from design_materialization_topology import validate_materialization_topology_snapshot
from design_provider_binding import (
    validate_cross_materialization_identity,
    validate_provider_binding_set_v2,
)

from tests.execution_coordination.test_phase_i_materialized_success import (
    _execute,
    _materialized_fixture,
)


def test_phase_i_offline_materialization_pipeline_converges_end_to_end() -> None:
    fixture = _materialized_fixture()
    ctx = fixture.ctx

    validate_materialization_topology_snapshot(ctx.case.topology)
    validate_approval_scope_boundary_v2(ctx.case.boundary_v2)
    validate_changeset_integrity_v2(ctx.case.changeset, ctx.case.boundary_v2)
    validate_execution_plan_v2(
        ctx.execution_plan,
        ctx.case.topology,
        ctx.case.boundary_v2,
    )
    validate_cross_materialization_identity(
        ctx.materialization_plan,
        ctx.binding_sets,
    )
    for execution_slice, binding_set in zip(
        ctx.execution_plan.execution_slices,
        ctx.binding_sets,
        strict=True,
    ):
        validate_provider_binding_set_v2(binding_set, execution_slice)

    assert tuple(
        intent.required_host_type for intent in ctx.materialization_plan.intents
    ) == ("autocad", "revit")
    assert len(ctx.materialization_plan.intents) == 2
    assert all(
        intent.intent_hash == compute_materialization_intent_hash(intent)
        for intent in ctx.materialization_plan.intents
    )
    assert ctx.materialization_plan.required_set_hash == compute_required_set_hash(
        ctx.materialization_plan.intents
    )
    assert ctx.materialization_plan.materialization_plan_hash == compute_materialization_plan_hash(
        changeset_hash=ctx.materialization_plan.changeset_hash,
        approved_scope_hash=ctx.materialization_plan.approved_scope_hash,
        topology_snapshot_hash=ctx.materialization_plan.topology_snapshot_hash,
        intents=ctx.materialization_plan.intents,
        required_set_hash=ctx.materialization_plan.required_set_hash,
        convergence_profile_hash=ctx.materialization_plan.convergence_profile_hash,
    )
    assert (
        ctx.materialization_plan.topology_snapshot_hash
        == ctx.case.topology.topology_snapshot_hash
    )
    assert (
        ctx.materialization_plan.convergence_profile_hash
        == ctx.case.profile.profile_hash
    )

    scope_rules = {
        rule.document_ref: rule.slice_scope_rule_id
        for rule in ctx.case.boundary_v2.execution_slice_scopes
    }
    assert set(scope_rules) == {"DOC-AUTOCAD", "DOC-REVIT"}
    assert len(set(scope_rules.values())) == 2
    assert {
        execution_slice.host_runtime_ref.document_ref:
        execution_slice.approved_scope_ref.execution_slice_scope_rule_id
        for execution_slice in ctx.execution_plan.execution_slices
    } == scope_rules

    assert ctx.execution_plan.materialization_plan_hash == (
        ctx.materialization_plan.materialization_plan_hash
    )
    assert ctx.execution_plan.required_set_hash == ctx.materialization_plan.required_set_hash
    assert ctx.execution_plan.topology_snapshot_hash == ctx.case.topology.topology_snapshot_hash
    assert ctx.execution_plan.convergence_profile_hash == ctx.case.profile.profile_hash

    for execution_slice, binding_set, authority in zip(
        ctx.execution_plan.execution_slices,
        ctx.binding_sets,
        ctx.authorities,
        strict=True,
    ):
        assert binding_set.materialization_id == execution_slice.materialization_id
        assert binding_set.execution_slice_hash == execution_slice.execution_slice_hash
        assert binding_set.materialization_plan_hash == (
            ctx.materialization_plan.materialization_plan_hash
        )
        assert authority.materialization_id == execution_slice.materialization_id
        assert authority.execution_slice_hash == execution_slice.execution_slice_hash
        assert authority.binding_set_hash == binding_set.binding_set_hash
        assert authority.materialization_plan_hash == (
            ctx.materialization_plan.materialization_plan_hash
        )

    result = _execute(fixture)

    assert result.status is MaterializedCoordinationStatus.SUCCEEDED
    assert result.failure_ref is None
    assert result.convergence_result_hash is not None
    assert tuple(item.host_type for item in fixture.host_registry.resolutions) == (
        "autocad",
        "revit",
    )
    assert all(len(port.calls) == 1 for port in fixture.readiness_ports.values())
    assert all(len(port.calls) == 1 for port in fixture.host_registry.ports.values())
    assert tuple(fixture.evidence_port.evidence_calls) == tuple(
        item.materialization_id for item in ctx.execution_plan.execution_slices
    )
    assert len(fixture.convergence_verifier.calls) == 1

    stored = fixture.reconciliation.get_saga(result.saga_id)
    assert stored is not None
    assert stored.status is ExecutionSagaStatusV2.SUCCEEDED
    assert stored.convergence_outcome is SagaConvergenceOutcome.CONVERGED
    assert stored.convergence_result_hash == result.convergence_result_hash
    assert tuple(item.status for item in stored.slice_states) == (
        SliceReconciliationStatusV2.SUCCEEDED,
        SliceReconciliationStatusV2.SUCCEEDED,
    )
