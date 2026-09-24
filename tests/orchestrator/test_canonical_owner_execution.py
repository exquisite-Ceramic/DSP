"""Task 8.3/8.4：canonical workflow 对真实 execution-owner truth 的路由与接线契约。"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from design_convergence import CrossHostConvergenceVerifier
from design_execution_coordination import (
    HostFailed,
    HostFailurePhase,
    MaterializedExecutionSagaCoordinator,
    ReadinessStatus,
    project_execution_recovery,
)
from design_execution_reconciliation import (
    ExecutionReconciliationServiceV2,
    ExecutionSagaStatusV2,
    HostDispatchStatus,
    InMemoryExecutionSagaStoreV2,
    InMemoryHostDispatchIntentStore,
)
from design_execution_planning import InMemoryExecutionPlanV2Store
from design_gateway_authorization import InMemoryGatewayAuthorizationStoreV2
from design_materialization_planning import (
    InMemoryMaterializationPlanStore,
    MaterializationPlanner,
)
from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
from design_orchestrator.recovery import decide_apply_resume
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    WorkflowCheckpointView,
    WorkflowPhase,
)
from design_orchestrator.workflow_services import (
    ExecutionOwnerView,
    ExecutionSagaView,
    HostDispatchRecoveryState,
)
from design_provider_binding import InMemoryProviderBindingSetV2Store
from semantic_runtime import RevisionBarrier

from tests.execution_coordination._materialized_support import (
    ConvergenceEvidencePort,
    FixedClock,
    MaterializedHostRegistry,
)
from tests.execution_coordination._support import barrier
from tests.execution_coordination.test_task8_execution_recovery_projection import (
    build_reconciled_nonterminal_case,
)
from tests.orchestrator.test_canonical_owner_ports import (
    _MutableHostRevisionObservation,
    _task6_real_impact_case,
    _Task7ApprovalAdmission,
    _Task7Clock,
)
from tests.orchestrator.test_task7_planning import (
    _approval_admission,
    _Task7MaterializationRouting,
)
from tests.orchestrator.test_task7_provider_grant import (
    _CountingGatewayV2,
    _ProviderExecutionSnapshotBoundary,
)


class _ExactBindingStore:
    """只在测试中切换 exact-hash lookup 可见性；所有 binding 规则仍委托真实 owner store。"""

    def __init__(self) -> None:
        self._delegate = InMemoryProviderBindingSetV2Store()
        self.allow_hash_lookup = True

    def put(self, binding_set):
        """保存 binding truth 时完全委托真实 store。"""
        return self._delegate.put(binding_set)

    def get(self, binding_set_id: str):
        """Task 7 的 StableRef lookup 保持真实 owner 行为。"""
        return self._delegate.get(binding_set_id)

    def get_by_hash(self, binding_set_hash: str):
        """Task 8 可显式模拟 exact full-hash owner truth 缺失。"""
        if not self.allow_hash_lookup:
            return None
        return self._delegate.get_by_hash(binding_set_hash)


class _BindableHostRegistry:
    """在 Task 7 lineage 冻结后才绑定 Host 环境，不拥有 Host execution 语义。"""

    def __init__(self, *, host_failure=None) -> None:
        self._host_failure = host_failure
        self._delegate = None

    def bind(self, ctx) -> None:
        """把真实 plan/authority 交给既有 deterministic Host test boundary。"""
        failures = None
        if self._host_failure is not None:
            failures = {"revit": self._host_failure}
        self._delegate = MaterializedHostRegistry(ctx, failures)

    def resolve(self, runtime_ref):
        """按 production registry surface 解析绑定后的 Host port。"""
        if self._delegate is None:
            raise AssertionError("Host registry must be bound before execution")
        return self._delegate.resolve(runtime_ref)

    @property
    def execute_count(self) -> int:
        """只统计外部 Host mutation 次数，不暴露 owner 内部状态。"""
        if self._delegate is None:
            return 0
        return sum(len(port.calls) for port in self._delegate.ports.values())


class _BindableEvidencePort:
    """在 owner lineage 冻结后绑定既有 production-backed verification evidence boundary。"""

    def __init__(self, *, insufficient_convergence: bool = False) -> None:
        self._delegate = None
        self._insufficient_convergence = insufficient_convergence

    def bind(self, ctx) -> None:
        """创建只消费当前一-Slice owner truth 的 evidence boundary。"""
        self._delegate = ConvergenceEvidencePort(ctx)

    def build_bundle(self, **kwargs):
        """Step33 verification evidence 继续使用既有 production-compatible builder。"""
        if self._delegate is None:
            raise AssertionError("evidence port must be bound before execution")
        return self._delegate.build_bundle(**kwargs)

    def build_evidence(self, **kwargs):
        """可仅通过 evidence IO 删除 required field，驱动真实 verifier 的不足证据终态。"""
        if self._delegate is None:
            raise AssertionError("evidence port must be bound before execution")
        evidence = self._delegate.build_evidence(**kwargs)
        if not self._insufficient_convergence:
            return evidence

        # 单 materialization 无法产生 cross-host value divergence；这里不伪造第二个 Host，
        # 而是通过合法 evidence IO 缺少 required field 驱动 real verifier 的
        # EVIDENCE_INSUFFICIENT，coordinator 按冻结规则把 Saga 收口为 DIVERGED。
        from dataclasses import replace
        from design_convergence import compute_materialization_canonical_evidence_hash

        draft = replace(evidence, verified_fields=(), evidence_hash="0" * 64)
        return replace(
            draft,
            evidence_hash=compute_materialization_canonical_evidence_hash(draft),
        )


def _task8_execution_case(
    *,
    host_failure=None,
    insufficient_convergence: bool = False,
):
    """组合 Task 6/7 真实 owner lineage 与 Task 8 execution owner composition。"""
    revision = _MutableHostRevisionObservation("42")
    gateway_store = InMemoryGatewayAuthorizationStoreV2()
    gateway = _CountingGatewayV2(gateway_store)
    admission_port = _Task7ApprovalAdmission()
    materialization_store = InMemoryMaterializationPlanStore()
    execution_store = InMemoryExecutionPlanV2Store()
    provider_store = _ExactBindingStore()
    provider_snapshot = _ProviderExecutionSnapshotBoundary()

    saga_store = InMemoryExecutionSagaStoreV2()
    reconciliation = ExecutionReconciliationServiceV2(store=saga_store)
    dispatch_store = InMemoryHostDispatchIntentStore()
    host_registry = _BindableHostRegistry(host_failure=host_failure)
    evidence_port = _BindableEvidencePort(
        insufficient_convergence=insufficient_convergence
    )
    readiness_barrier, _readiness_registry, _readiness_ports = barrier(
        {"revit": ReadinessStatus.READY}
    )
    convergence_verifier = CrossHostConvergenceVerifier()
    coordinator = MaterializedExecutionSagaCoordinator(
        readiness_barrier=readiness_barrier,
        reconciliation=reconciliation,
        host_registry=host_registry,
        dispatch_intents=dispatch_store,
        evidence_port=evidence_port,
        convergence_verifier=convergence_verifier,
        clock=FixedClock(),
    )

    overrides = {
        "host_revision_observation": revision,
        "revision_barrier": RevisionBarrier(revision),
        "materialization_planner": MaterializationPlanner(),
        "materialization_plan_store": materialization_store,
        "execution_plan_store": execution_store,
        "gateway_authorization": gateway,
        "gateway_authorization_store": gateway_store,
        "coordination_clock": _Task7Clock(),
        "approval_admission": admission_port,
        "materialization_routing": _Task7MaterializationRouting(),
        "provider_binding_store": provider_store,
        "provider_execution_snapshot": provider_snapshot,
        "saga_store": saga_store,
        "execution_coordinator": coordinator,
        "reconciliation_service": reconciliation,
        "convergence_verifier": convergence_verifier,
    }
    constructor_parameters = inspect.signature(CanonicalWorkflowOwnerPorts).parameters
    if "dispatch_intent_store" in constructor_parameters:
        overrides["dispatch_intent_store"] = dispatch_store
    if "execution_recovery_projection" in constructor_parameters:
        overrides["execution_recovery_projection"] = project_execution_recovery

    (
        adapter,
        bound_ref,
        impact_ref,
        _,
        _,
        approval_scope_store,
        changeset_store,
        _,
    ) = _task6_real_impact_case(overrides=overrides)

    changeset_ref = adapter.build_changeset("task-6", bound_ref, impact_ref)
    changeset = changeset_store.get(changeset_ref.ref_id)
    boundary = approval_scope_store.get_boundary(f"SCOPE-{changeset.changeset_id}")
    admission_port.admission = _approval_admission(changeset, boundary)
    approval_ref = adapter.request_approval(changeset_ref)
    execution_plan_ref = adapter.plan_execution(changeset_ref, approval_ref)
    adapter.check_revision_barrier(execution_plan_ref)
    binding_ref = adapter.bind_providers(execution_plan_ref)
    grant_ref = adapter.issue_execution_grant(
        execution_plan_ref,
        approval_ref,
        binding_ref,
    )

    execution_plan = execution_store.get(execution_plan_ref.ref_id)
    authority = gateway.admitted_authorities[-1]
    ctx = SimpleNamespace(
        execution_plan=execution_plan,
        authorities=(authority,),
        case=SimpleNamespace(changeset=changeset),
    )
    host_registry.bind(ctx)
    evidence_port.bind(ctx)
    return SimpleNamespace(
        adapter=adapter,
        execution_plan_ref=execution_plan_ref,
        grant_ref=grant_ref,
        execution_plan=execution_plan,
        saga_store=saga_store,
        dispatch_store=dispatch_store,
        provider_store=provider_store,
        coordinator=coordinator,
        host_registry=host_registry,
    )


def test_canonical_execution_constructor_requires_explicit_recovery_dependencies() -> None:
    """reference composition 必须显式注入 dispatch owner 与只读 recovery projection。"""
    signature = inspect.signature(CanonicalWorkflowOwnerPorts)

    assert "dispatch_intent_store" in signature.parameters
    assert "execution_recovery_projection" in signature.parameters


def test_reference_composition_shares_one_dispatch_store_with_real_coordinator() -> None:
    """coordinator 与 adapter 必须观察同一个 logical durable dispatch owner。"""
    case = _task8_execution_case()

    assert case.coordinator._dispatch_intents is case.dispatch_store
    assert case.adapter._dispatch_intent_store is case.dispatch_store


def test_real_execution_success_returns_durable_saga_and_no_active_recovery() -> None:
    """real Step33/37 success 必须由 durable Saga/intent truth 驱动 owner view。"""
    case = _task8_execution_case()

    saga_id = case.adapter.begin_execution(case.execution_plan_ref, case.grant_ref)

    assert isinstance(saga_id, str)
    stored = case.saga_store.get_saga(saga_id)
    assert stored is not None
    assert stored.status is ExecutionSagaStatusV2.SUCCEEDED
    view = case.adapter.get_execution_owner_state(saga_id)
    assert view.saga.status == ExecutionSagaStatusV2.SUCCEEDED.value
    assert view.active_dispatch_recovery is None
    assert case.host_registry.execute_count == 1

    slice_hash = case.execution_plan.execution_slices[0].execution_slice_hash
    intent = case.dispatch_store.get_for_saga_slice(saga_id, slice_hash)
    assert intent is not None
    assert intent.status is HostDispatchStatus.HOST_COMMITTED


def test_real_execution_unknown_outcome_waits_and_replay_never_redispatches() -> None:
    """COMMIT_STATE_UNKNOWN 必须持久化为 OUTCOME_UNKNOWN，并阻止同 lineage 第二次 Host mutation。"""
    case = _task8_execution_case(
        host_failure=HostFailed(
            phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
            failure_ref="transport:response-lost",
            failed_at="2026-09-06T14:01:00Z",
        )
    )

    pending = case.adapter.begin_execution(case.execution_plan_ref, case.grant_ref)
    assert isinstance(pending, AsyncOperationRef)
    assert pending.kind is AsyncOperationKind.EXECUTION_JOB
    assert pending.owner == "execution"

    saga_id = pending.operation_id
    stored = case.saga_store.get_saga(saga_id)
    assert stored is not None
    slice_hash = case.execution_plan.execution_slices[0].execution_slice_hash
    intent = case.dispatch_store.get_for_saga_slice(saga_id, slice_hash)
    assert intent is not None
    assert intent.status is HostDispatchStatus.OUTCOME_UNKNOWN

    view = case.adapter.get_execution_owner_state(saga_id)
    assert view.active_dispatch_recovery is not None
    assert view.active_dispatch_recovery.state is HostDispatchRecoveryState.OUTCOME_UNKNOWN
    assert case.host_registry.execute_count == 1

    replay = case.adapter.begin_execution(case.execution_plan_ref, case.grant_ref)
    assert replay == pending
    assert case.host_registry.execute_count == 1


def test_real_execution_insufficient_convergence_closes_saga_diverged_without_compensation() -> None:
    """evidence 不足必须由 real convergence verifier 收口 Saga DIVERGED，adapter 不补偿。"""
    case = _task8_execution_case(insufficient_convergence=True)

    saga_id = case.adapter.begin_execution(case.execution_plan_ref, case.grant_ref)

    assert isinstance(saga_id, str)
    stored = case.saga_store.get_saga(saga_id)
    assert stored is not None
    assert stored.status is ExecutionSagaStatusV2.DIVERGED
    view = case.adapter.get_execution_owner_state(saga_id)
    assert view.active_dispatch_recovery is None
    assert case.host_registry.execute_count == 1


def test_begin_execution_requires_exact_binding_hash_before_host_mutation() -> None:
    """grant 指向的 full binding hash 无法解析时必须在 coordinator/Host 之前 fail closed。"""
    case = _task8_execution_case()
    case.provider_store.allow_hash_lookup = False

    with pytest.raises((ValueError, RuntimeError), match="[Bb]inding|PROVIDER_BINDING"):
        case.adapter.begin_execution(case.execution_plan_ref, case.grant_ref)

    assert case.host_registry.execute_count == 0
    assert case.saga_store.get_saga(case.grant_ref.ref_id) is None


def test_reconciled_nonterminal_saga_routes_to_recover_or_wait_not_redispatch() -> None:
    """无 active Host recovery 不等于 Saga 完成；CONVERGENCE_PENDING 必须继续等待 owner。"""
    stored, reconciled = build_reconciled_nonterminal_case()
    slice_hash = stored.definition.ordered_slice_hashes[0]
    projection = project_execution_recovery(stored, slice_hash, reconciled)
    assert projection.disposition is None

    owner_view = ExecutionOwnerView(
        saga=ExecutionSagaView(
            saga_id=stored.definition.saga_id,
            saga_revision=stored.saga_revision,
            status=stored.status.value,
            active_slice_hash=None,
        ),
        active_dispatch_recovery=None,
    )
    checkpoint = WorkflowCheckpointView(
        task_id="task-task8-reconciled-nonterminal",
        phase=WorkflowPhase.APPLY_WAIT,
        saga_id=stored.definition.saga_id,
    )

    decision = decide_apply_resume(checkpoint=checkpoint, execution=owner_view)

    assert decision.route == "RECOVER_OR_WAIT"
    assert decision.route != "MAY_DISPATCH"
    assert decision.route != "TERMINAL_EXECUTION_STATE"
    # decide_apply_resume 是纯 owner-read 分类器，没有 begin_execution/Host mutation 依赖；
    # 只要 route 不是 MAY_DISPATCH，现有 graph refresh 分支就不会进入 apply_or_recover。
    assert decision.refreshed_saga_revision == stored.saga_revision
