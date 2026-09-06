"""Phase I 在 readiness、binding、scope lineage 上的离线 fail-closed 证明。"""

from __future__ import annotations

from dataclasses import fields, replace

import pytest
from design_approval_scope import ExecutionSliceScopeRule
from design_execution_coordination import (
    CoordinationError,
    MaterializedCoordinationStatus,
    ReadinessStatus,
)
from design_execution_planning import ExecutionPlanningError, ExecutionPlanningRequestV2
from design_execution_planning.v2 import _resolve_exact_execution_slice_scope
from design_materialization_planning import MaterializationPlanningRequest

from tests.execution_coordination.test_phase_i_materialized_success import (
    _execute,
    _materialized_fixture,
)


def _execute_with(fixture, *, boundary=None, binding_sets=None, authorities=None):
    ctx = fixture.ctx
    return fixture.coordinator.execute(
        ctx.case.changeset,
        ctx.case.boundary_v2 if boundary is None else boundary,
        ctx.materialization_plan,
        ctx.execution_plan,
        ctx.binding_sets if binding_sets is None else binding_sets,
        ctx.authorities if authorities is None else authorities,
        ctx.case.profile,
    )


def _assert_no_host_mutation(fixture) -> None:
    assert fixture.reconciliation.create_calls == 0
    assert all(port.calls == [] for port in fixture.host_registry.ports.values())
    assert fixture.evidence_port.bundle_calls == []
    assert fixture.evidence_port.evidence_calls == []
    assert fixture.convergence_verifier.calls == []


def test_missing_revit_readiness_blocks_first_commit_without_shrinking_required_set() -> None:
    fixture = _materialized_fixture(
        readiness_statuses={
            "autocad": ReadinessStatus.READY,
            "revit": ReadinessStatus.NOT_READY,
        }
    )
    ctx = fixture.ctx
    required_ids = tuple(
        intent.materialization_id for intent in ctx.materialization_plan.intents
    )
    required_hash = ctx.materialization_plan.required_set_hash

    result = _execute(fixture)

    assert result.status is MaterializedCoordinationStatus.READINESS_FAILED
    assert result.saga_id == "NOT_CREATED"
    assert result.convergence_result_hash is None
    assert all(len(port.calls) == 1 for port in fixture.readiness_ports.values())
    _assert_no_host_mutation(fixture)
    assert tuple(
        intent.materialization_id for intent in ctx.materialization_plan.intents
    ) == required_ids
    assert ctx.materialization_plan.required_set_hash == required_hash
    assert "availability" not in {
        item.name for item in fields(MaterializationPlanningRequest)
    }
    assert "availability" not in {
        item.name for item in fields(ExecutionPlanningRequestV2)
    }


@pytest.mark.parametrize("mode", ("missing", "duplicate"))
def test_missing_or_conflicting_host_binding_fails_before_readiness_and_commit(mode: str) -> None:
    fixture = _materialized_fixture()
    bindings = fixture.ctx.binding_sets[:1]
    if mode == "duplicate":
        bindings = (*fixture.ctx.binding_sets, fixture.ctx.binding_sets[0])

    with pytest.raises(CoordinationError) as exc:
        _execute_with(fixture, binding_sets=bindings)

    assert exc.value.code == "MATERIALIZATION_BINDING_MISMATCH"
    assert all(port.calls == [] for port in fixture.readiness_ports.values())
    _assert_no_host_mutation(fixture)


def test_topology_substitution_is_rejected_before_readiness_and_commit() -> None:
    fixture = _materialized_fixture()
    substituted_boundary = replace(
        fixture.ctx.case.boundary_v2,
        topology_snapshot_hash="f" * 64,
    )

    with pytest.raises(CoordinationError) as exc:
        _execute_with(fixture, boundary=substituted_boundary)

    assert exc.value.code == "MATERIALIZATION_PLAN_HASH_MISMATCH"
    assert all(port.calls == [] for port in fixture.readiness_ports.values())
    _assert_no_host_mutation(fixture)


def test_binding_substitution_after_grant_is_rejected_before_readiness_and_commit() -> None:
    fixture = _materialized_fixture()
    substituted = replace(
        fixture.ctx.authorities[1],
        binding_set_hash=fixture.ctx.binding_sets[0].binding_set_hash,
    )

    with pytest.raises(CoordinationError) as exc:
        _execute_with(
            fixture,
            authorities=(fixture.ctx.authorities[0], substituted),
        )

    assert exc.value.code == "MATERIALIZATION_AUTHORITY_MISMATCH"
    assert all(port.calls == [] for port in fixture.readiness_ports.values())
    _assert_no_host_mutation(fixture)


def test_step30_never_falls_back_to_wider_or_wrong_document_scope() -> None:
    fixture = _materialized_fixture()
    case = fixture.ctx.case
    operation = case.changeset.root_operation
    required = operation.scope_rule_ids
    wider = ExecutionSliceScopeRule(
        "WIDER-AUTOCAD",
        "DOC-AUTOCAD",
        existing_rule_ids=(*required, "ER-EXTRA"),
    )
    wrong_document = ExecutionSliceScopeRule(
        "EXACT-OTHER",
        "DOC-OTHER",
        existing_rule_ids=required,
    )

    for candidate in (wider, wrong_document):
        boundary = replace(
            case.boundary_v2,
            execution_slice_scopes=(candidate,),
        )
        with pytest.raises(ExecutionPlanningError) as exc:
            _resolve_exact_execution_slice_scope(
                operation,
                "DOC-AUTOCAD",
                boundary,
            )
        assert exc.value.code == "EXECUTION_SCOPE_UNCOVERED"
