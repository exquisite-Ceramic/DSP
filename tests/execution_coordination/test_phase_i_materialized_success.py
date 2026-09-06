from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from design_convergence import (
    CrossHostConvergenceVerifier,
    build_materialization_canonical_evidence,
    compute_materialization_canonical_evidence_hash,
)
from design_execution_coordination import (
    HostCommitted,
    MaterializedCoordinationStatus,
    MaterializedExecutionSagaCoordinator,
)
from design_execution_reconciliation import (
    ExecutionReconciliationServiceV2,
    ExecutionSagaStatusV2,
    InMemoryExecutionSagaStoreV2,
    SagaConvergenceOutcome,
    SliceReconciliationStatusV2,
)

from tests.execution_coordination.test_phase_i_readiness_barrier import (
    _barrier,
    _phase_i_readiness_inputs,
)
from tests.execution_reconciliation.test_step33_v2_local_reconciliation import (
    _signed_bundle,
    _signed_delta,
)


class _FixedClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> str:
        self.calls += 1
        return "2026-09-06T14:00:00Z"


class _TrackingReconciliation:
    def __init__(self) -> None:
        self.service = ExecutionReconciliationServiceV2(
            store=InMemoryExecutionSagaStoreV2()
        )
        self.create_calls = 0

    def create_saga(self, *args, **kwargs):
        self.create_calls += 1
        return self.service.create_saga(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.service, name)


class _MaterializedHostPort:
    def __init__(self, ctx, host_type: str, failure=None) -> None:
        self.ctx = ctx
        self.host_type = host_type
        self.failure = failure
        self.calls = []

    def execute(self, execution_slice, authority, binding_set):
        self.calls.append((execution_slice, authority, binding_set))
        assert execution_slice.host_runtime_ref.host_type == self.host_type
        assert binding_set.materialization_id == execution_slice.materialization_id
        assert authority.binding_set_hash == binding_set.binding_set_hash
        if self.failure is not None:
            return self.failure
        index = next(
            index
            for index, item in enumerate(self.ctx.execution_plan.execution_slices)
            if item.execution_slice_hash == execution_slice.execution_slice_hash
        )
        return HostCommitted(
            actual_delta=_signed_delta(self.ctx, index),
            committed_at=f"2026-09-06T14:0{index + 1}:00Z",
        )


class _MaterializedHostRegistry:
    def __init__(self, ctx, failures=None) -> None:
        failures = dict(failures or {})
        self.ports = {
            host_type: _MaterializedHostPort(ctx, host_type, failures.get(host_type))
            for host_type in ("autocad", "revit")
        }
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        return self.ports[runtime_ref.host_type]


class _ConvergenceEvidencePort:
    def __init__(self, ctx, *, divergent_host: str | None = None) -> None:
        self.ctx = ctx
        self.divergent_host = divergent_host
        self.bundle_calls = []
        self.evidence_calls = []

    def _index(self, execution_slice) -> int:
        return next(
            index
            for index, item in enumerate(self.ctx.execution_plan.execution_slices)
            if item.execution_slice_hash == execution_slice.execution_slice_hash
        )

    def build_bundle(
        self,
        *,
        execution_slice,
        actual_delta,
        canonical_changeset,
        approval_scope_boundary,
    ):
        self.bundle_calls.append(execution_slice.execution_slice_hash)
        assert canonical_changeset.changeset_hash == actual_delta.changeset_hash
        assert approval_scope_boundary.scope_hash == actual_delta.approved_scope_hash
        return _signed_bundle(self.ctx, actual_delta, self._index(execution_slice))

    def build_evidence(
        self,
        *,
        materialization_id,
        execution_slice,
        actual_delta,
        verification_result,
        verification_bundle,
        convergence_profile,
    ):
        self.evidence_calls.append(materialization_id)
        evidence = build_materialization_canonical_evidence(
            materialization_id=materialization_id,
            execution_slice=execution_slice,
            actual_delta=actual_delta,
            verification_result=verification_result,
            verification_evidence_bundle=verification_bundle,
            convergence_profile=convergence_profile,
        )
        if execution_slice.host_runtime_ref.host_type != self.divergent_host:
            return evidence
        changed_field = replace(evidence.verified_fields[0], value=305.0)
        draft = replace(
            evidence,
            verified_fields=(changed_field,),
            evidence_hash="0" * 64,
        )
        return replace(
            draft,
            evidence_hash=compute_materialization_canonical_evidence_hash(draft),
        )


class _TrackingConvergenceVerifier:
    def __init__(self) -> None:
        self.delegate = CrossHostConvergenceVerifier()
        self.calls = []

    def verify(self, plan, profile, evidence_set):
        self.calls.append((plan, profile, evidence_set))
        return self.delegate.verify(plan, profile, evidence_set)


def _materialized_fixture(
    *,
    readiness_statuses=None,
    host_failures=None,
    divergent_host: str | None = None,
):
    ctx = _phase_i_readiness_inputs()
    readiness_barrier, readiness_registry, readiness_ports = _barrier(readiness_statuses)
    reconciliation = _TrackingReconciliation()
    host_registry = _MaterializedHostRegistry(ctx, host_failures)
    evidence_port = _ConvergenceEvidencePort(ctx, divergent_host=divergent_host)
    convergence_verifier = _TrackingConvergenceVerifier()
    clock = _FixedClock()
    coordinator = MaterializedExecutionSagaCoordinator(
        readiness_barrier=readiness_barrier,
        reconciliation=reconciliation,
        host_registry=host_registry,
        evidence_port=evidence_port,
        convergence_verifier=convergence_verifier,
        clock=clock,
    )
    return SimpleNamespace(
        ctx=ctx,
        coordinator=coordinator,
        readiness_registry=readiness_registry,
        readiness_ports=readiness_ports,
        reconciliation=reconciliation,
        host_registry=host_registry,
        evidence_port=evidence_port,
        convergence_verifier=convergence_verifier,
        clock=clock,
    )


def _execute(fixture):
    ctx = fixture.ctx
    return fixture.coordinator.execute(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
        ctx.binding_sets,
        ctx.authorities,
        ctx.case.profile,
    )


def test_materialized_success_runs_hosts_once_in_frozen_order_then_converges() -> None:
    fixture = _materialized_fixture()

    result = _execute(fixture)

    assert result.status is MaterializedCoordinationStatus.SUCCEEDED
    assert result.failure_ref is None
    assert result.active_slice_hash is None
    assert result.convergence_result_hash is not None
    assert fixture.reconciliation.create_calls == 1
    assert tuple(
        item.host_type for item in fixture.host_registry.resolutions
    ) == ("autocad", "revit")
    assert all(len(port.calls) == 1 for port in fixture.host_registry.ports.values())
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
    assert result.saga_revision == stored.saga_revision
