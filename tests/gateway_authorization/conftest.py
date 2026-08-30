"""Shared Step32 Gateway authorization fixtures."""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest
from design_approval_scope import bind_changeset
from design_changeset import ChangeSetBuilder
from design_execution_planning import (
    ExecutionPlanner,
    ExecutionPlanningRequest,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
    compute_routing_snapshot_hash,
)
from design_gateway_authorization import (
    ApprovalAdmission,
    ApprovalConsumptionRequest,
    ExecutionGrantRequest,
    GatewayAuthorizationService,
    InMemoryGatewayAuthorizationStore,
    compute_admission_fingerprint,
)
from design_provider_binding import (
    ProviderBindingAdapterRegistry,
    ProviderResolver,
)


def _load_fixture_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    return fixtures


def _step29_request():
    fixture_path = Path(__file__).parents[1] / "changeset" / "test_step29_derived_builder.py"
    return _load_fixture_module(fixture_path, "_step32_step29_fixture")._request()


def _provider_fixtures():
    fixture_path = Path(__file__).parents[1] / "provider_binding" / "conftest.py"
    return _load_fixture_module(fixture_path, "_step32_provider_fixture")


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


def build_real_execution_slice(valid_approval_request: ApprovalConsumptionRequest):
    changeset = valid_approval_request.canonical_changeset
    boundary = valid_approval_request.approval_scope_boundary
    runtime = HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    routes = [RuntimeEntityRoute(target, runtime) for target in changeset.root_operation.targets]
    for operation in changeset.derived_operations:
        routes.extend(RuntimeEntityRoute(target, runtime) for target in operation.targets)
    route_tuple = tuple(routes)
    routing = RuntimeRoutingEvidence(
        "RRS-32",
        route_tuple,
        compute_routing_snapshot_hash(route_tuple),
    )
    plan = ExecutionPlanner().plan(
        ExecutionPlanningRequest(changeset, boundary, routing)
    )
    assert len(plan.execution_slices) == 1
    return plan.execution_slices[0]


def build_real_binding_set(execution_slice, *, valid_until="2026-08-30T08:30:00Z"):
    fixtures = _provider_fixtures()
    candidate = fixtures.make_candidate()
    snapshot = fixtures.make_snapshot(
        execution_slice,
        provider_candidates=(candidate,),
        valid_until=valid_until,
    )
    adapter = fixtures.FakeBindingAdapter()
    registry = ProviderBindingAdapterRegistry()
    registry.register(candidate.provider_server, adapter)
    request = fixtures.make_request(
        execution_slice,
        snapshot=snapshot,
        admission_time="2026-08-30T07:35:00Z",
    )
    return ProviderResolver(registry).resolve(request)


@pytest.fixture
def real_binding_set_builder():
    return build_real_binding_set


@pytest.fixture
def gateway_cross_step(valid_approval_request):
    store = InMemoryGatewayAuthorizationStore()
    approval = GatewayAuthorizationService(store).consume_approval(valid_approval_request)
    execution_slice = build_real_execution_slice(valid_approval_request)
    binding_set = build_real_binding_set(execution_slice)
    request = ExecutionGrantRequest(
        approval_id=approval.approval_id,
        execution_slice=execution_slice,
        provider_binding_set=binding_set,
        issued_at="2026-08-30T07:40:00Z",
    )
    return store, approval, execution_slice, binding_set, request