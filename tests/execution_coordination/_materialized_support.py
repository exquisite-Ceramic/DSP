from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from design_convergence import (
    CrossHostConvergenceVerifier,
    build_materialization_canonical_evidence,
    compute_materialization_canonical_evidence_hash,
)
from design_execution_coordination import HostCommitted, MaterializedExecutionSagaCoordinator
from design_execution_reconciliation import (
    ExecutionReconciliationServiceV2,
    InMemoryExecutionSagaStoreV2,
)

from tests.execution_coordination._support import barrier, phase_i_readiness_inputs
from tests.execution_reconciliation._support import signed_bundle, signed_delta


class FixedClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> str:
        self.calls += 1
        return "2026-09-06T14:00:00Z"


class TrackingReconciliation:
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


class MaterializedHostPort:
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
            actual_delta=signed_delta(self.ctx, index),
            committed_at=f"2026-09-06T14:0{index + 1}:00Z",
        )


class MaterializedHostRegistry:
    def __init__(self, ctx, failures=None) -> None:
        failures = dict(failures or {})
        self.ports = {
            host_type: MaterializedHostPort(ctx, host_type, failures.get(host_type))
            for host_type in ("autocad", "revit")
        }
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        return self.ports[runtime_ref.host_type]


class ConvergenceEvidencePort:
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
        return signed_bundle(self.ctx, actual_delta, self._index(execution_slice))

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


class TrackingConvergenceVerifier:
    def __init__(self) -> None:
        self.delegate = CrossHostConvergenceVerifier()
        self.calls = []

    def verify(self, plan, profile, evidence_set):
        self.calls.append((plan, profile, evidence_set))
        return self.delegate.verify(plan, profile, evidence_set)


def materialized_fixture(
    *,
    readiness_statuses=None,
    host_failures=None,
    divergent_host: str | None = None,
):
    ctx = phase_i_readiness_inputs()
    readiness_barrier, readiness_registry, readiness_ports = barrier(readiness_statuses)
    reconciliation = TrackingReconciliation()
    host_registry = MaterializedHostRegistry(ctx, host_failures)
    evidence_port = ConvergenceEvidencePort(ctx, divergent_host=divergent_host)
    convergence_verifier = TrackingConvergenceVerifier()
    clock = FixedClock()
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


def execute(fixture):
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
