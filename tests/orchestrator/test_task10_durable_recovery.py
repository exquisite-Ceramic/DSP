"""Task 10：真实 PostgreSQL Saga/dispatch 的 fresh-runtime durable recovery acceptance。

本模块只复用 Task 9 已冻结的 real-owner 上游 stores 与显式环境边界；Execution Saga、
Host dispatch intent、Workflow checkpoint/artifact 都使用真实 PostgreSQL persistence。
进程丢失 wrapper 只在真实 ``begin_execution()`` 返回后抛异常，不写任何 owner state。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from design_approval_scope import ApprovalScopePlanner
from design_changeset import ChangeSetBuilder
from design_convergence import CrossHostConvergenceVerifier
from design_execution_coordination import (
    CrossHostReadinessBarrier,
    MaterializedExecutionSagaCoordinator,
    project_execution_recovery,
)
from design_execution_reconciliation import ExecutionReconciliationServiceV2
from design_gateway_authorization import GatewayAuthorizationServiceV2
from design_impact import ImpactAnalyzer
from design_materialization_planning import MaterializationPlanner
from design_materialization_topology import MaterializationTopologyRegistry
from design_orchestrator.artifact_postgres import create_postgres_artifact_store
from design_orchestrator.canonical_operations import (
    MVP_CANONICAL_OPERATIONS,
    SET_WALL_THICKNESS_V1,
)
from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.default_workflow_services import DefaultWorkflowServices
from design_orchestrator.langgraph_runtime import LangGraphWorkflowRuntime
from design_orchestrator.operation_resolver import OperationResolver
from design_orchestrator.parameter_binder import MVP_BINDING_RECIPES, ParameterBinder
from design_orchestrator.workflow_contracts import WorkflowPhase, WorkflowResumeCommand
from design_orchestrator.workflow_services import WorkflowStateError
from semantic_runtime import DirtyMap, FreshnessResolver, RevisionBarrier

from tests.orchestrator import test_real_owner_workflow_end_to_end as real_owner


class _SimulatedProcessLoss(RuntimeError):
    """只表示测试注入的进程丢失，不承担任何恢复或持久化语义。"""


class _ProcessLossAfterTerminalBegin:
    """委托真实 services，并在真实 begin_execution 已返回 durable saga_id 后中断 graph。"""

    def __init__(self, delegate, saga_store) -> None:
        self._delegate = delegate
        self._saga_store = saga_store
        self.saga_id: str | None = None

    def __getattr__(self, name: str):
        """除 begin_execution 外全部原样委托，避免复制 WorkflowServices 业务逻辑。"""

        return getattr(self._delegate, name)

    def begin_execution(self, execution_plan_ref, grant_ref):
        """先执行真实 owner，再在 LangGraph state update 前模拟进程丢失。"""

        result = self._delegate.begin_execution(execution_plan_ref, grant_ref)
        if not isinstance(result, str):
            raise AssertionError("baseline E requires terminal begin_execution result")
        stored = self._saga_store.get_saga(result)
        if stored is None:
            raise AssertionError("terminal begin_execution must resolve durable Saga truth")
        status = getattr(stored.status, "value", stored.status)
        if status != "SUCCEEDED":
            raise AssertionError("baseline E process loss must occur after terminal SUCCEEDED")
        self.saga_id = result
        raise _SimulatedProcessLoss(result)


def _close_store(store: object) -> None:
    """显式关闭测试持有的 owner connection；重复 close 由具体 store 自身保持幂等。"""

    close = getattr(store, "close", None)
    if callable(close):
        close()


def _build_execution_services(
    seed,
    *,
    artifact_store,
    saga_store,
    dispatch_store,
    host_port,
):
    """用共享上游 owner truth + fresh execution persistence 重建 reference composition。"""

    host_revision = real_owner._HostRevisionObservation()
    reconciliation = ExecutionReconciliationServiceV2(store=saga_store)
    convergence = CrossHostConvergenceVerifier()
    coordinator = MaterializedExecutionSagaCoordinator(
        readiness_barrier=CrossHostReadinessBarrier(real_owner._ReadinessRegistry()),
        reconciliation=reconciliation,
        host_registry=real_owner._HostRegistry(host_port),
        dispatch_intents=dispatch_store,
        evidence_port=real_owner._EvidenceBoundary(),
        convergence_verifier=convergence,
        clock=real_owner._ExecutionClock(),
    )
    topology_registry = MaterializationTopologyRegistry()
    topology_registry.register(real_owner._topology())
    gateway = GatewayAuthorizationServiceV2(seed.gateway_store)
    adapter = CanonicalWorkflowOwnerPorts(
        snapshot_registry=seed.snapshot_registry,
        freshness_resolver=FreshnessResolver(DirtyMap()),
        workflow_artifact_store=artifact_store,
        host_revision_observation=host_revision,
        canonical_operations=MVP_CANONICAL_OPERATIONS,
        impact_analyzer=ImpactAnalyzer(),
        impact_store=seed.impact_store,
        approval_scope_planner=ApprovalScopePlanner(),
        approval_scope_store=seed.scope_store,
        changeset_builder=ChangeSetBuilder(),
        changeset_store=seed.changeset_store,
        materialization_planner=MaterializationPlanner(),
        materialization_plan_store=seed.materialization_store,
        topology_registry=topology_registry,
        topology_environment_id="TOPOLOGY-TASK9",
        topology_revision=1,
        execution_plan_store=seed.execution_store,
        revision_barrier=RevisionBarrier(host_revision),
        gateway_authorization=gateway,
        gateway_authorization_store=seed.gateway_store,
        coordination_clock=real_owner._GatewayClock(),
        provider_binding_store=seed.provider_store,
        dispatch_intent_store=dispatch_store,
        execution_recovery_projection=project_execution_recovery,
        saga_store=saga_store,
        execution_coordinator=coordinator,
        reconciliation_service=reconciliation,
        convergence_verifier=convergence,
        semantic_reconstruction=seed.semantic_boundary,
        preview_port=real_owner._PreviewBoundary(),
        approval_admission=real_owner._ApprovalAdmissionBoundary(
            seed.changeset_store,
            seed.scope_store,
        ),
        materialization_routing=real_owner._MaterializationRoutingBoundary(),
        provider_execution_snapshot=real_owner._ProviderExecutionSnapshotBoundary(),
    )
    return DefaultWorkflowServices(
        operation_resolver=OperationResolver((SET_WALL_THICKNESS_V1,)),
        parameter_binder=ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES),
        artifact_store=artifact_store,
        external_owners=adapter,
    )


def _fresh_runtime(
    seed,
    *,
    saga_store,
    dispatch_store,
    host_port,
    services_wrapper=None,
):
    """为同一 workflow thread 创建 fresh checkpoint/artifact connections 与 fresh adapter。"""

    artifact_store = create_postgres_artifact_store(real_owner._dsn())
    checkpointer = create_postgres_checkpointer(real_owner._dsn())
    services = _build_execution_services(
        seed,
        artifact_store=artifact_store,
        saga_store=saga_store,
        dispatch_store=dispatch_store,
        host_port=host_port,
    )
    if services_wrapper is not None:
        services = services_wrapper(services)
    runtime = LangGraphWorkflowRuntime(services=services, checkpointer=checkpointer)
    return SimpleNamespace(
        runtime=runtime,
        artifact_store=artifact_store,
        checkpointer=checkpointer,
        services=services,
    )


@real_owner.requires_postgres
def test_terminal_process_loss_replays_durable_saga_without_second_host_execution(
    task10_postgres_execution_owner_factory,
) -> None:
    """E：terminal owner truth 已 durable、graph update 丢失后 fresh runtime 不得二次执行 Host。"""

    task_id = "task10-terminal-process-loss-e"
    seed = real_owner._build_real_owner_case(task_id)
    host_port = seed.host_port

    # seed 只提供 Task 9 已验证的上游 owner stores/boundaries；Task 10 的 runtime A/B
    # 必须各自持有 fresh workflow/execution PostgreSQL connections。
    real_owner._close_case(seed)

    saga_a, dispatch_a = task10_postgres_execution_owner_factory()
    process_loss = None

    def wrap_runtime_a(services):
        nonlocal process_loss
        process_loss = _ProcessLossAfterTerminalBegin(services, saga_a)
        return process_loss

    runtime_a = _fresh_runtime(
        seed,
        saga_store=saga_a,
        dispatch_store=dispatch_a,
        host_port=host_port,
        services_wrapper=wrap_runtime_a,
    )
    try:
        proposal_wait = runtime_a.runtime.start(real_owner._request(task_id))
        assert proposal_wait.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert proposal_wait.pending_interaction is not None

        freshness_wait = runtime_a.runtime.resume(
            task_id,
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                pause_id=proposal_wait.pending_interaction.pause_id,
            ),
        )
        assert freshness_wait.phase is WorkflowPhase.ENSURE_OPERATION_FRESHNESS

        seed.semantic_boundary.operation_ready = True
        with pytest.raises(WorkflowStateError) as exc_info:
            runtime_a.runtime.resume(
                task_id,
                WorkflowResumeCommand(
                    resume_kind="ASYNC_OPERATION_COMPLETED",
                    payload={"operation_id": "task9-reconstruction"},
                ),
            )
        assert exc_info.value.code == "WORKFLOW_SERVICE_FAILURE"
        assert isinstance(exc_info.value.__cause__, _SimulatedProcessLoss)
        assert process_loss is not None
        assert process_loss.saga_id is not None
        durable_saga_id = process_loss.saga_id

        stored_a = saga_a.get_saga(durable_saga_id)
        assert stored_a is not None
        assert getattr(stored_a.status, "value", stored_a.status) == "SUCCEEDED"
        assert len(host_port.calls) == 1

        after_loss = runtime_a.runtime.get_checkpoint(task_id)
        assert after_loss is not None
        assert after_loss.phase is WorkflowPhase.APPLY_WAIT
        assert after_loss.execution_plan_ref is not None
        assert after_loss.grant_ref is not None
        assert after_loss.saga_id is None
    finally:
        runtime_a.artifact_store.close()
        runtime_a.checkpointer.close()
        _close_store(dispatch_a)
        _close_store(saga_a)

    # runtime B 必须用新的 checkpoint/artifact/Saga/dispatch connections；唯一共享的是
    # 上游 authoritative in-memory owner truth 与可计数的外部 Host boundary。
    saga_b, dispatch_b = task10_postgres_execution_owner_factory()
    runtime_b = _fresh_runtime(
        seed,
        saga_store=saga_b,
        dispatch_store=dispatch_b,
        host_port=host_port,
    )
    try:
        completed = runtime_b.runtime.resume(task_id)
        assert completed.phase is WorkflowPhase.COMPLETED
        assert completed.saga_id == durable_saga_id
        assert len(host_port.calls) == 1

        stored_b = saga_b.get_saga(durable_saga_id)
        assert stored_b is not None
        assert getattr(stored_b.status, "value", stored_b.status) == "SUCCEEDED"
    finally:
        runtime_b.artifact_store.close()
        runtime_b.checkpointer.close()
        _close_store(dispatch_b)
        _close_store(saga_b)
