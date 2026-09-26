from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import psycopg
import pytest
from design_approval_scope import ApprovalScopePlanner, InMemoryApprovalScopeStore
from design_changeset import ChangeSetBuilder, InMemoryChangeSetStore
from design_convergence import CrossHostConvergenceVerifier
from design_execution_coordination import (
    CrossHostReadinessBarrier,
    MaterializedExecutionSagaCoordinator,
    project_execution_recovery,
)
from design_execution_planning import InMemoryExecutionPlanV2Store
from design_execution_reconciliation import ExecutionReconciliationServiceV2
from design_execution_reconciliation.postgres import (
    apply_execution_saga_migrations,
    connect_postgres,
)
from design_execution_reconciliation.postgres_dispatch_intent import (
    PostgresHostDispatchIntentStore,
)
from design_execution_reconciliation.postgres_saga_store_v2 import (
    PostgresExecutionSagaStoreV2,
)
from design_gateway_authorization import (
    GatewayAuthorizationServiceV2,
    InMemoryGatewayAuthorizationStoreV2,
)
from design_impact import ImpactAnalyzer, InMemoryImpactAnalysisStore
from design_materialization_planning import InMemoryMaterializationPlanStore, MaterializationPlanner
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
from design_product_runtime import (
    ProductTaskRequest,
    RevitWallThicknessProviderExecutionSnapshotBoundary,
    RevitWallThicknessSemanticBoundary,
    RevitWallThicknessVerificationEvidencePort,
    WallThicknessProductFlow,
    create_postgres_product_task_request_store,
)
from design_provider_binding import (
    InMemoryProviderBindingSetV2Store,
    compute_candidate_fingerprint,
    compute_provider_snapshot_hash_v2,
)
from dsp_core_semantic_provider import DSP_CORE_PROVIDER
from enterprise_mapping_provider import ENTERPRISE_MAPPING_PROVIDER
from ifc43_semantic_provider import IFC43_PROVIDER
from revit_sidecar import (
    RevitContextReadPort,
    RevitWallThicknessExecutionPort,
    RevitWallThicknessReadinessPort,
    RevitWallThicknessSnapshotReadPort,
)
from revit_sidecar.design_fact_adapter import DesignFactAdapter
from semantic_runtime import (
    DirtyMap,
    FreshnessResolver,
    HostBinding,
    IdentityRegistry,
    InMemorySnapshotRegistry,
    RevisionBarrier,
)
from semantic_service import (
    ProviderRef,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
)

from tests.orchestrator.test_real_owner_workflow_end_to_end import (
    _ApprovalAdmissionBoundary,
    _ExecutionClock,
    _GatewayClock,
    _MaterializationRoutingBoundary,
    _PreviewBoundary,
    _ProviderExecutionSnapshotBoundary,
    _topology,
    _WallCapabilityProfile,
)

_DOCUMENT_REF = "DOC-TASK9"
_HOST_INSTANCE_ID = "REVIT-TASK9"
_SESSION_REF = "revit-session-product-e2e"
_PROJECT_ID = "project-task9"
_SEMANTIC_WALL_ID = "WALL-001"
_WALL_UNIQUE_ID = "REVIT-UNIQUE-ID-TASK9"
_WALL_TYPE_UNIQUE_ID = "REVIT-WALLTYPE-TASK9"
_INITIAL_REVISION = 42
_INITIAL_THICKNESS_MM = 275.0


@pytest.fixture
def product_task_postgres_dsn() -> str:
    """只在显式 PostgreSQL 17 lane 中运行真实 ProductTask / workflow / Saga acceptance。"""

    import os

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


class StatefulRevitTransport:
    """只模拟外部 Revit Host transport；所有平台 owner 与 sidecar adapter 使用 production。"""

    def __init__(self) -> None:
        self.current_revision = _INITIAL_REVISION
        self.current_thickness_mm = _INITIAL_THICKNESS_MM
        self.commands: list[object] = []
        self.command_revisions: list[int] = []
        self.execute_count = 0

    def request(self, command):
        """按真实 HostCommand operation 返回严格 Host evidence，并记录调用时 revision。"""

        self.commands.append(command)
        self.command_revisions.append(self.current_revision)
        operation = command.operation
        if operation == "context.current_selection":
            return {
                "status": "OK",
                "revision_after": self.current_revision,
                "payload": {
                    "document_id": _DOCUMENT_REF,
                    "document_title": "Product E2E Fixture",
                    "host_instance_id": _HOST_INSTANCE_ID,
                    "selected_elements": [
                        {"unique_id": _WALL_UNIQUE_ID, "native_kind": "Wall"}
                    ],
                },
            }
        if operation == "read_wall_thickness_snapshot":
            return {
                "status": "OK",
                "revision_after": self.current_revision,
                "payload": {
                    "document_id": command.document_id,
                    "host_instance_id": _HOST_INSTANCE_ID,
                    "wall_unique_id": command.target_native_refs[0].native_id,
                    "wall_type_unique_id": _WALL_TYPE_UNIQUE_ID,
                    "native_kind": "Wall",
                    "builtin_category": "OST_Walls",
                    "wall_thickness_mm": self.current_thickness_mm,
                    "location_signature": "Line|0|0|0|10|0|0",
                    "relationship_signature": "isolated",
                    "revision_before": self.current_revision,
                    "revision_after": self.current_revision,
                },
            }
        if operation == "check_wall_thickness_readiness":
            return {
                "status": "OK",
                "revision_after": self.current_revision,
                "payload": {
                    "document_id": _DOCUMENT_REF,
                    "wall_unique_id": _WALL_UNIQUE_ID,
                    "current_width": {
                        "value": self.current_thickness_mm,
                        "unit": "mm",
                    },
                    "isolation_ready": True,
                    "plan_ready": True,
                },
            }
        if operation == "set_wall_thickness":
            return self._execute_wall_thickness(command)
        raise AssertionError(f"unexpected Revit Host operation: {operation}")

    def _execute_wall_thickness(self, command):
        """执行唯一允许的 mutation；exact revision 不匹配时明确 BEFORE_COMMIT。"""

        self.execute_count += 1
        expected_revision = command.preconditions[0]["revision"]
        if expected_revision != self.current_revision:
            return {
                "command_id": command.command_id,
                "status": "ERROR",
                "revision_after": self.current_revision,
                "error": {
                    "code": "REVIT_REVISION_CONFLICT",
                    "commit_state": "BEFORE_COMMIT",
                },
            }
        requested_mm = float(command.arguments["thickness"]["value"])
        revision_before = self.current_revision
        revision_after = revision_before + 1
        self.current_thickness_mm = requested_mm
        self.current_revision = revision_after
        return {
            "command_id": command.command_id,
            "status": "OK",
            "revision_after": revision_after,
            "payload": {
                "wall_unique_id": _WALL_UNIQUE_ID,
                "wall_type_unique_id": _WALL_TYPE_UNIQUE_ID,
                "editable_layer_index": 1,
                "width_before_internal": 0.5,
                "width_after_internal": requested_mm / 304.8,
                "width_after_mm": requested_mm,
                "requested_width_mm": requested_mm,
                "transaction_attempt_count": 1,
            },
            "verification": {
                "identity_invariant_proven": True,
                "location_invariant_proven": True,
                "relationship_invariant_proven": True,
                "document_change_observed": True,
                "revision_before": revision_before,
                "revision_after": revision_after,
                "location_signature_before": "Line|0|0|0|10|0|0",
                "location_signature_after": "Line|0|0|0|10|0|0",
                "relationship_signature_before": "isolated",
                "relationship_signature_after": "isolated",
            },
            "replayed": False,
        }

    def command_operations(self) -> tuple[str, ...]:
        """按实际 I/O 顺序暴露 operation，测试据此断言调用次数与先后。"""

        return tuple(command.operation for command in self.commands)


class _HostRevisionObservation:
    """RevisionBarrier 只读取 stateful Host 当前 revision，不复制 barrier 规则。"""

    def __init__(self, host: StatefulRevitTransport) -> None:
        self._host = host

    def current_revision(self, document_ref: str) -> str:
        assert document_ref == _DOCUMENT_REF
        return str(self._host.current_revision)


class _ReadinessRegistry:
    """把 Revit runtime 解析到 production readiness adapter。"""

    def __init__(self, port) -> None:
        self._port = port

    def resolve(self, runtime_ref):
        assert runtime_ref.host_type == "revit"
        return self._port


class _HostRegistry:
    """把 Revit runtime 解析到 production execution adapter。"""

    def __init__(self, port) -> None:
        self._port = port

    def resolve(self, runtime_ref):
        assert runtime_ref.host_type == "revit"
        return self._port


def _real_semantic_environment():
    """注册真实 semantic providers，并 pin 本 vertical 使用的 environment。"""

    providers = (IFC43_PROVIDER, DSP_CORE_PROVIDER, ENTERPRISE_MAPPING_PROVIDER)
    registry = SemanticProviderRegistry()
    for provider in providers:
        registry.register(provider)
    environments = SemanticEnvironmentStore()
    environment = environments.pin(
        tuple(
            ProviderRef(provider.manifest.provider_id, provider.manifest.version)
            for provider in providers
        ),
        registry,
    )
    return SemanticService(registry, environments), environment


def _identity_registry() -> IdentityRegistry:
    """只注册既有 semantic↔Revit identity；产品边界不得临时发明 identity。"""

    registry = IdentityRegistry()
    registry.ensure_identity(_SEMANTIC_WALL_ID)
    registry.bind_host(
        HostBinding(
            semantic_id=_SEMANTIC_WALL_ID,
            host_type="revit",
            document_id=_DOCUMENT_REF,
            native_id=_WALL_UNIQUE_ID,
            native_kind="Wall",
        )
    )
    return registry


def _provider_snapshot(execution_slice):
    """复用既有 runtime evidence，只把 provider tool 收敛到真实 Revit namespace。"""

    base = _ProviderExecutionSnapshotBoundary()(execution_slice)
    old_candidate = base.provider_candidates[0]
    unsigned_candidate = replace(
        old_candidate,
        provider_tool="revit.set_wall_thickness",
        candidate_fingerprint="0" * 64,
    )
    candidate = replace(
        unsigned_candidate,
        candidate_fingerprint=compute_candidate_fingerprint(unsigned_candidate),
    )
    material = base.candidate_binding_materials[old_candidate.candidate_fingerprint]
    unsigned_snapshot = replace(
        base,
        provider_candidates=(candidate,),
        candidate_binding_materials={candidate.candidate_fingerprint: material},
        snapshot_hash="0" * 64,
    )
    return replace(
        unsigned_snapshot,
        snapshot_hash=compute_provider_snapshot_hash_v2(unsigned_snapshot),
    )


def _reset_product_acceptance_schemas(dsn: str) -> None:
    """每个 acceptance case 从 fresh ProductTask/Orchestrator/Saga owner schemas 开始。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        for schema in (
            "product_task",
            "orchestrator_checkpoint",
            "orchestrator_artifact",
            "execution_saga",
        ):
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    conn = connect_postgres(dsn)
    try:
        apply_execution_saga_migrations(conn)
    finally:
        conn.close()


def _request(task_id: str, *, thickness_mm: float = 300.0) -> ProductTaskRequest:
    """构造只携带用户 INTENT 的 immutable ProductTask request。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id=_PROJECT_ID,
        host_kind="REVIT",
        session_ref=_SESSION_REF,
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": thickness_mm, "unit": "mm"}},
    )


def _build_case(dsn: str, task_id: str):
    """组合 Task 9 真实 owners；唯一行为 double 是 Revit transport 与 human/presentation。"""

    _reset_product_acceptance_schemas(dsn)
    request_store = create_postgres_product_task_request_store(dsn)
    artifact_store = create_postgres_artifact_store(dsn)
    checkpointer = create_postgres_checkpointer(dsn)
    saga_store = PostgresExecutionSagaStoreV2(dsn)
    dispatch_store = PostgresHostDispatchIntentStore(dsn)

    host = StatefulRevitTransport()
    snapshot_reader = RevitWallThicknessSnapshotReadPort(host)
    snapshot_registry = InMemorySnapshotRegistry()
    semantic_service, semantic_environment = _real_semantic_environment()
    semantic_boundary = RevitWallThicknessSemanticBoundary(
        request_store=request_store,
        context_reader=RevitContextReadPort(host),
        identity_registry=_identity_registry(),
        session_ref=_SESSION_REF,
        document_id=_DOCUMENT_REF,
        host_instance_id=_HOST_INSTANCE_ID,
        snapshot_reader=snapshot_reader,
        design_fact_adapter=DesignFactAdapter(),
        semantic_service=semantic_service,
        semantic_environment=semantic_environment,
        snapshot_registry=snapshot_registry,
        capability_profiles=(_WallCapabilityProfile(),),
    )
    host_revision = _HostRevisionObservation(host)
    impact_store = InMemoryImpactAnalysisStore()
    scope_store = InMemoryApprovalScopeStore()
    changeset_store = InMemoryChangeSetStore()
    materialization_store = InMemoryMaterializationPlanStore()
    execution_store = InMemoryExecutionPlanV2Store()
    gateway_store = InMemoryGatewayAuthorizationStoreV2()
    gateway = GatewayAuthorizationServiceV2(gateway_store)
    provider_store = InMemoryProviderBindingSetV2Store()
    reconciliation = ExecutionReconciliationServiceV2(store=saga_store)
    convergence = CrossHostConvergenceVerifier()
    coordinator = MaterializedExecutionSagaCoordinator(
        readiness_barrier=CrossHostReadinessBarrier(
            _ReadinessRegistry(RevitWallThicknessReadinessPort(host))
        ),
        reconciliation=reconciliation,
        host_registry=_HostRegistry(
            RevitWallThicknessExecutionPort(
                host,
                clock=lambda: "2026-09-24T10:01:00Z",
            )
        ),
        dispatch_intents=dispatch_store,
        evidence_port=RevitWallThicknessVerificationEvidencePort(
            snapshot_reader=snapshot_reader,
            design_fact_adapter=DesignFactAdapter(),
            semantic_service=semantic_service,
            semantic_environment=semantic_environment,
        ),
        convergence_verifier=convergence,
        clock=_ExecutionClock(),
    )
    topology_registry = MaterializationTopologyRegistry()
    topology_registry.register(_topology())
    adapter = CanonicalWorkflowOwnerPorts(
        snapshot_registry=snapshot_registry,
        freshness_resolver=FreshnessResolver(DirtyMap()),
        workflow_artifact_store=artifact_store,
        host_revision_observation=host_revision,
        canonical_operations=MVP_CANONICAL_OPERATIONS,
        impact_analyzer=ImpactAnalyzer(),
        impact_store=impact_store,
        approval_scope_planner=ApprovalScopePlanner(),
        approval_scope_store=scope_store,
        changeset_builder=ChangeSetBuilder(),
        changeset_store=changeset_store,
        materialization_planner=MaterializationPlanner(),
        materialization_plan_store=materialization_store,
        topology_registry=topology_registry,
        topology_environment_id="TOPOLOGY-TASK9",
        topology_revision=1,
        execution_plan_store=execution_store,
        revision_barrier=RevisionBarrier(host_revision),
        gateway_authorization=gateway,
        gateway_authorization_store=gateway_store,
        coordination_clock=_GatewayClock(),
        provider_binding_store=provider_store,
        dispatch_intent_store=dispatch_store,
        execution_recovery_projection=project_execution_recovery,
        saga_store=saga_store,
        execution_coordinator=coordinator,
        reconciliation_service=reconciliation,
        convergence_verifier=convergence,
        semantic_reconstruction=semantic_boundary,
        preview_port=_PreviewBoundary(),
        approval_admission=_ApprovalAdmissionBoundary(changeset_store, scope_store),
        materialization_routing=_MaterializationRoutingBoundary(),
        provider_execution_snapshot=RevitWallThicknessProviderExecutionSnapshotBoundary(
            changeset_store=changeset_store,
            snapshot_registry=snapshot_registry,
            provider_snapshot_factory=_provider_snapshot,
        ),
    )
    services = DefaultWorkflowServices(
        operation_resolver=OperationResolver((SET_WALL_THICKNESS_V1,)),
        parameter_binder=ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES),
        artifact_store=artifact_store,
        external_owners=adapter,
    )
    runtime = LangGraphWorkflowRuntime(services=services, checkpointer=checkpointer)
    flow = WallThicknessProductFlow(
        request_store=request_store,
        workflow_runtime=runtime,
        saga_store=saga_store,
    )
    return SimpleNamespace(
        task_id=task_id,
        request=_request(task_id),
        flow=flow,
        runtime=runtime,
        host=host,
        request_store=request_store,
        artifact_store=artifact_store,
        checkpointer=checkpointer,
        saga_store=saga_store,
        dispatch_store=dispatch_store,
        snapshot_registry=snapshot_registry,
        changeset_store=changeset_store,
        gateway_store=gateway_store,
        execution_store=execution_store,
    )


def _close_case(case) -> None:
    """按 owner 生命周期显式关闭所有 PostgreSQL 连接。"""

    for owner in (
        case.dispatch_store,
        case.saga_store,
        case.request_store,
        case.artifact_store,
        case.checkpointer,
    ):
        close = getattr(owner, "close", None)
        if callable(close):
            close()


@pytest.fixture
def revit_wall_thickness_product_case(product_task_postgres_dsn: str):
    """返回 fresh Task 9 composition factory，并在用例结束后释放 owner 连接。"""

    cases = []

    def build(task_id: str):
        case = _build_case(product_task_postgres_dsn, task_id)
        cases.append(case)
        return case

    yield build

    for case in reversed(cases):
        _close_case(case)
