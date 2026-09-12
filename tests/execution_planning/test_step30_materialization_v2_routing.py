from __future__ import annotations

from dataclasses import fields, replace

import pytest
from design_execution_planning import (
    ExecutionPlanningError,
    HostRuntimeRef,
    MaterializationRoutingEvidence,
    MaterializationRuntimeRoute,
    compute_materialization_routing_hash,
    plan_materialized_execution,
)

from tests.execution_planning._support import build_phase_i_execution_inputs


def _with_routes(request, routes):
    routing = MaterializationRoutingEvidence(
        routing_snapshot_id="MRS-OVERRIDE",
        routes=tuple(routes),
        routing_snapshot_hash=compute_materialization_routing_hash(tuple(routes)),
    )
    return replace(request, runtime_routing_evidence=routing)


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ExecutionPlanningError) as exc:
        operation()
    assert exc.value.code == code


def test_routing_is_keyed_by_materialization_id_not_semantic_id() -> None:
    assert {field.name for field in fields(MaterializationRuntimeRoute)} == {
        "materialization_id",
        "host_runtime_ref",
    }


def test_missing_required_materialization_route_fails_closed() -> None:
    _, _, routing, request = build_phase_i_execution_inputs()
    _assert_code(
        "MATERIALIZATION_ROUTE_UNRESOLVED",
        lambda: plan_materialized_execution(
            _with_routes(request, routing.routes[:1])
        ),
    )


def test_extraneous_materialization_route_fails_closed() -> None:
    _, _, routing, request = build_phase_i_execution_inputs()
    extra = MaterializationRuntimeRoute(
        materialization_id="MAT-EXTRA",
        host_runtime_ref=HostRuntimeRef("autocad", "AUTOCAD-X", "DOC-AUTOCAD"),
    )
    _assert_code(
        "MATERIALIZATION_ROUTE_EXTRANEOUS",
        lambda: plan_materialized_execution(
            _with_routes(request, (*routing.routes, extra))
        ),
    )


def test_conflicting_duplicate_materialization_route_fails_closed() -> None:
    _, _, routing, request = build_phase_i_execution_inputs()
    duplicate = replace(
        routing.routes[0],
        host_runtime_ref=HostRuntimeRef(
            routing.routes[0].host_runtime_ref.host_type,
            "AUTOCAD-CONFLICT",
            routing.routes[0].host_runtime_ref.document_ref,
        ),
    )
    _assert_code(
        "MATERIALIZATION_ROUTE_CONFLICT",
        lambda: plan_materialized_execution(
            _with_routes(request, (routing.routes[0], duplicate, routing.routes[1]))
        ),
    )


def test_host_or_document_substitution_fails_materialization_route_match() -> None:
    _, _, routing, request = build_phase_i_execution_inputs()
    wrong = replace(
        routing.routes[1],
        host_runtime_ref=HostRuntimeRef(
            "autocad",
            routing.routes[1].host_runtime_ref.host_instance_id,
            routing.routes[1].host_runtime_ref.document_ref,
        ),
    )
    _assert_code(
        "MATERIALIZATION_ROUTE_MISMATCH",
        lambda: plan_materialized_execution(
            _with_routes(request, (routing.routes[0], wrong))
        ),
    )
