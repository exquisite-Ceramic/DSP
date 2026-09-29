"""Revit 墙厚产品 vertical 的 production/reference composition。

本模块只负责把现有 authoritative owners、Revit sidecar adapters 与环境 evidence seam
组合成一个 exact-session runtime。它不持有第二份业务真相，也不把 in-memory
SnapshotRegistry 伪装成跨进程 durable owner。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from design_approval_scope import ApprovalScopePlanner, InMemoryApprovalScopeStore
from design_changeset import ChangeSetBuilder, InMemoryChangeSetStore, canonical_hash
from design_convergence import CrossHostConvergenceVerifier
from design_execution_coordination import (
    CrossHostReadinessBarrier,
    MaterializedExecutionSagaCoordinator,
    project_execution_recovery,
)
from design_execution_planning import (
    HostRuntimeRef,
    InMemoryExecutionPlanV2Store,
    MaterializationRoutingEvidence,
    MaterializationRuntimeRoute,
    compute_materialization_routing_hash,
)
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
from design_materialization_planning import (
    InMemoryMaterializationPlanStore,
    MaterializationPlanner,
)
from design_materialization_topology import (
    MaterializationRequirement,
    MaterializationSlot,
    MaterializationTopologyRegistry,
    MaterializationTopologySnapshot,
    compute_topology_snapshot_hash,
)
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
from design_orchestrator.workflow_contracts import StableRef
from design_provider_binding import (
    EligibilityState,
    InMemoryProviderBindingSetV2Store,
    NativeConstraint,
    NativeConstraintOperator,
    NativeTargetBindingEvidence,
    ProviderBindingMaterial,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshotV2,
    compute_candidate_fingerprint,
    compute_host_binding_fingerprint,
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

from .postgres_request_store import (
    PostgresProductTaskRequestStore,
    create_postgres_product_task_request_store,
)
from .postgres_start_gate import PostgresProductTaskStartGate
from .revit_evidence import RevitWallThicknessVerificationEvidencePort
from .revit_execution import RevitWallThicknessProviderExecutionSnapshotBoundary
from .revit_operation_resolution import RevitWallThicknessSemanticBoundary
from .wall_thickness_flow import WallThicknessProductFlow

_TOPOLOGY_ENVIRONMENT_ID = "REVIT-WALL-THICKNESS-REFERENCE"
_TOPOLOGY_REVISION = 1


def _required_text(value: object, field_name: str) -> str:
    """规范化 exact-session composition 的不可空字符串输入。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class RevitWallThicknessCompositionConfig:
    """一个 exact session 的 production/reference composition 输入。"""

    dsn: str
    session_ref: str
    document_id: str
    host_instance_id: str
    semantic_target_id: str
    native_target_unique_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "dsn",
            "session_ref",
            "document_id",
            "host_instance_id",
            "semantic_target_id",
            "native_target_unique_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class _ReferenceWallCapabilityProfile:
    """reference vertical 已配置的单一 Revit 墙厚 capability environment。"""

    provider_server: str = "provider.revit.wall"
    provider_tool: str = "revit.set_wall_thickness"
    canonical_operation: str = "set_wall_thickness.v1"
    category: str = "MODEL_OPERATION"
    entity_constraints: tuple[str, ...] = ("Wall",)
    execution_freshness: tuple[dict[str, Any], ...] = (
        {"aspect": "PROPERTIES", "required_state": "FRESH"},
    )
    effects: tuple[str, ...] = ("PROPERTIES",)
    risk: str | None = "LOW"
    preview_supported: bool = True
    rollback_supported: bool = False
    verification_contract: dict[str, Any] = field(default_factory=dict)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "verification_contract",
            dict(SET_WALL_THICKNESS_V1.verification_contract),
        )
        object.__setattr__(
            self,
            "input_schema",
            {
                "type": "object",
                "properties": {
                    "native_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "canonical_arguments": {"type": "object"},
                },
                "required": ["native_ids", "canonical_arguments"],
                "additionalProperties": False,
            },
        )


class _HostRevisionObservation:
    """每次 revision 检查都 fresh-read 当前 Revit context，不缓存 locator 事实。"""

    def __init__(self, *, context_reader: RevitContextReadPort, config) -> None:
        self._context_reader = context_reader
        self._config = config

    def current_revision(self, document_ref: str) -> str:
        """读取 exact runtime/document 的当前 revision。"""

        normalized = _required_text(document_ref, "document_ref")
        if normalized != self._config.document_id:
            raise ValueError("reference composition document does not match exact session")
        material = f"{self._config.session_ref}\n{self._config.document_id}"
        suffix = sha256(material.encode("utf-8")).hexdigest()[:24]
        observation = self._context_reader.read(
            command_id=f"PRODUCT-REVISION-{suffix}",
            document_id=self._config.document_id,
            host_instance_id=self._config.host_instance_id,
        )
        return str(observation.revision)


class _SinglePortRegistry:
    """只为当前 exact Revit session 解析一个已注入 production adapter。"""

    def __init__(self, port: object) -> None:
        self._port = port

    def resolve(self, runtime_ref: object) -> object:
        if getattr(runtime_ref, "host_type", None) != "revit":
            raise ValueError("reference composition only resolves Revit runtime")
        return self._port


class _ReferencePreviewPort:
    """发布 presentation-only preview ref，不创建第二份 ChangeSet truth。"""

    def preview(self, changeset_ref: StableRef) -> StableRef:
        if not isinstance(changeset_ref, StableRef):
            raise TypeError("changeset_ref must be StableRef")
        content_hash = canonical_hash(
            {
                "kind": "revit-wall-thickness-preview",
                "changeset_id": changeset_ref.ref_id,
                "changeset_hash": changeset_ref.content_hash,
            }
        )
        return StableRef(f"preview:{changeset_ref.ref_id}", content_hash)


class _UtcCoordinationClock:
    """Gateway/coordination 使用 timezone-aware UTC datetime。"""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _UtcExecutionClock:
    """Saga/Host coordination 使用 canonical UTC Z 文本。"""

    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _ReferenceMaterializationRouting:
    """把已冻结 topology slot 映射到当前 exact Revit runtime identity。"""

    def __init__(self, config: RevitWallThicknessCompositionConfig) -> None:
        self._config = config

    def routing_evidence(
        self,
        materialization_plan: object,
        topology_snapshot: object,
    ) -> MaterializationRoutingEvidence:
        slot_by_id = {
            slot.materialization_slot_id: slot
            for slot in topology_snapshot.slots
        }
        routes = tuple(
            MaterializationRuntimeRoute(
                materialization_id=intent.materialization_id,
                host_runtime_ref=HostRuntimeRef(
                    host_type=intent.required_host_type,
                    host_instance_id=self._config.host_instance_id,
                    document_ref=slot_by_id[
                        intent.materialization_slot_id
                    ].document_ref,
                ),
            )
            for intent in materialization_plan.intents
        )
        return MaterializationRoutingEvidence(
            routing_snapshot_id=(
                f"MRS-{sha256(self._config.session_ref.encode()).hexdigest()[:24]}"
            ),
            routes=routes,
            routing_snapshot_hash=compute_materialization_routing_hash(routes),
        )


def _semantic_environment() -> tuple[SemanticService, object]:
    """注册 reference vertical 使用的真实 semantic providers，并 pin environment。"""

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


def _identity_registry(config: RevitWallThicknessCompositionConfig) -> IdentityRegistry:
    """把 frozen semantic/native target identity 注册到 Semantic Runtime owner。"""

    registry = IdentityRegistry()
    registry.ensure_identity(config.semantic_target_id)
    registry.bind_host(
        HostBinding(
            semantic_id=config.semantic_target_id,
            host_type="revit",
            document_id=config.document_id,
            native_id=config.native_target_unique_id,
            native_kind="Wall",
        )
    )
    return registry


def _topology(config: RevitWallThicknessCompositionConfig) -> MaterializationTopologySnapshot:
    """为 exact document/semantic target 构造单 Revit required topology snapshot。"""

    draft = MaterializationTopologySnapshot(
        topology_environment_id=_TOPOLOGY_ENVIRONMENT_ID,
        topology_revision=_TOPOLOGY_REVISION,
        slots=(
            MaterializationSlot(
                materialization_slot_id="SLOT-REVIT-WALL-THICKNESS",
                semantic_target_ref=config.semantic_target_id,
                required_host_type="revit",
                document_ref=config.document_id,
                requirement=MaterializationRequirement.REQUIRED,
            ),
        ),
        topology_snapshot_hash="0" * 64,
    )
    return replace(
        draft,
        topology_snapshot_hash=compute_topology_snapshot_hash(draft),
    )


def _provider_snapshot_factory(
    config: RevitWallThicknessCompositionConfig,
) -> Callable[[object], ProviderExecutionSnapshotV2]:
    """返回只发布当前 exact Revit target/provider evidence 的 factory。"""

    def build(execution_slice: object) -> ProviderExecutionSnapshotV2:
        unit = execution_slice.execution_units[0]
        target_draft = NativeTargetBindingEvidence(
            semantic_id=unit.targets[0],
            host_type=execution_slice.host_runtime_ref.host_type,
            document_ref=execution_slice.host_runtime_ref.document_ref,
            native_id=config.native_target_unique_id,
            native_kind="Wall",
            host_binding_fingerprint="0" * 64,
        )
        target = replace(
            target_draft,
            host_binding_fingerprint=compute_host_binding_fingerprint(target_draft),
        )
        candidate_draft = ProviderExecutionCandidate(
            provider_server="provider.revit.wall",
            provider_tool="revit.set_wall_thickness",
            provider_version="1.0.0",
            canonical_operation=unit.canonical_operation,
            compatible_operation_versions=(unit.canonical_operation_version,),
            input_adapter_version="1.0.0",
            provider_native_constraints=(
                NativeConstraint(
                    "native_kind",
                    NativeConstraintOperator.EQ,
                    ("Wall",),
                ),
            ),
            provider_input_schema={
                "type": "object",
                "properties": {
                    "native_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "canonical_arguments": {"type": "object"},
                },
                "required": ["native_ids", "canonical_arguments"],
                "additionalProperties": False,
            },
            verification_contract={"read_back": "required"},
            rollback_contract={"mode": "compensating_changeset"},
            trust_state=EligibilityState.SATISFIED,
            compatibility_state=EligibilityState.SATISFIED,
            health_state=EligibilityState.SATISFIED,
            license_state=EligibilityState.SATISFIED,
            certification_state=EligibilityState.SATISFIED,
            policy_priority=10,
            candidate_fingerprint="0" * 64,
        )
        candidate = replace(
            candidate_draft,
            candidate_fingerprint=compute_candidate_fingerprint(candidate_draft),
        )
        material = ProviderBindingMaterial(
            native_targets=(target,),
            provider_arguments={
                "native_ids": [target.native_id],
                "canonical_arguments": dict(unit.arguments),
            },
            provider_preconditions=(),
            native_binding_metadata={
                "identity_source": "revit-reference-composition",
            },
        )
        draft = ProviderExecutionSnapshotV2(
            snapshot_id=(
                f"PESV2-{sha256(execution_slice.execution_slice_hash.encode()).hexdigest()[:24]}"
            ),
            materialization_id=execution_slice.materialization_id,
            materialization_plan_hash=execution_slice.materialization_plan_hash,
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            host_runtime_ref=execution_slice.host_runtime_ref,
            native_target_bindings=(target,),
            provider_candidates=(candidate,),
            candidate_binding_materials={candidate.candidate_fingerprint: material},
            valid_until="2099-01-01T00:00:00Z",
            snapshot_hash="0" * 64,
        )
        return replace(
            draft,
            snapshot_hash=compute_provider_snapshot_hash_v2(draft),
        )

    return build


def _apply_saga_migrations(dsn: str) -> None:
    """在 composition bootstrap 边界显式应用 execution-saga owner migrations。"""

    connection = connect_postgres(dsn)
    try:
        apply_execution_saga_migrations(connection)
    finally:
        connection.close()


def _close_many(values: tuple[object, ...]) -> None:
    """按逆序关闭本 composition 独占的可关闭资源。"""

    for value in reversed(values):
        close = getattr(value, "close", None)
        if callable(close):
            close()


@dataclass(slots=True)
class RevitWallThicknessRuntimeComposition:
    """一个 exact session 的 runtime handles；业务真相仍位于各 authoritative owner。"""

    flow: WallThicknessProductFlow
    runtime: LangGraphWorkflowRuntime
    request_store: PostgresProductTaskRequestStore
    start_gate: PostgresProductTaskStartGate
    snapshot_registry: object
    saga_store: object
    _closeables: tuple[object, ...] = field(repr=False)

    def close(self) -> None:
        """显式关闭 composition 独占的 PostgreSQL/checkpointer resources。"""

        _close_many(self._closeables)


def build_revit_wall_thickness_reference_composition(
    *,
    config: RevitWallThicknessCompositionConfig,
    transport: object,
    approval_admission_factory: object,
) -> RevitWallThicknessRuntimeComposition:
    """组合一个 exact-session Revit product runtime，构建阶段不触发 Host I/O。"""

    if not isinstance(config, RevitWallThicknessCompositionConfig):
        raise TypeError("config must be RevitWallThicknessCompositionConfig")
    if transport is None or not callable(getattr(transport, "request", None)):
        raise TypeError("transport must provide request")
    build_admission = getattr(approval_admission_factory, "build", None)
    if not callable(build_admission):
        raise TypeError("approval_admission_factory must provide build")

    closeables: list[object] = []
    try:
        _apply_saga_migrations(config.dsn)
        request_store = create_postgres_product_task_request_store(config.dsn)
        closeables.append(request_store)
        start_gate = PostgresProductTaskStartGate(config.dsn)
        closeables.append(start_gate)
        artifact_store = create_postgres_artifact_store(config.dsn)
        closeables.append(artifact_store)
        checkpointer = create_postgres_checkpointer(config.dsn)
        closeables.append(checkpointer)
        saga_store = PostgresExecutionSagaStoreV2(config.dsn)
        closeables.append(saga_store)
        dispatch_store = PostgresHostDispatchIntentStore(config.dsn)
        closeables.append(dispatch_store)

        snapshot_reader = RevitWallThicknessSnapshotReadPort(transport)
        snapshot_registry = InMemorySnapshotRegistry()
        semantic_service, semantic_environment = _semantic_environment()
        context_reader = RevitContextReadPort(transport)
        semantic_boundary = RevitWallThicknessSemanticBoundary(
            request_store=request_store,
            context_reader=context_reader,
            identity_registry=_identity_registry(config),
            session_ref=config.session_ref,
            document_id=config.document_id,
            host_instance_id=config.host_instance_id,
            snapshot_reader=snapshot_reader,
            design_fact_adapter=DesignFactAdapter(),
            semantic_service=semantic_service,
            semantic_environment=semantic_environment,
            snapshot_registry=snapshot_registry,
            capability_profiles=(_ReferenceWallCapabilityProfile(),),
        )
        host_revision = _HostRevisionObservation(
            context_reader=context_reader,
            config=config,
        )

        impact_store = InMemoryImpactAnalysisStore()
        approval_scope_store = InMemoryApprovalScopeStore()
        changeset_store = InMemoryChangeSetStore()
        materialization_store = InMemoryMaterializationPlanStore()
        execution_store = InMemoryExecutionPlanV2Store()
        gateway_store = InMemoryGatewayAuthorizationStoreV2()
        gateway = GatewayAuthorizationServiceV2(gateway_store)
        provider_store = InMemoryProviderBindingSetV2Store()
        reconciliation = ExecutionReconciliationServiceV2(store=saga_store)
        convergence = CrossHostConvergenceVerifier()
        execution_clock = _UtcExecutionClock()
        coordinator = MaterializedExecutionSagaCoordinator(
            readiness_barrier=CrossHostReadinessBarrier(
                _SinglePortRegistry(RevitWallThicknessReadinessPort(transport))
            ),
            reconciliation=reconciliation,
            host_registry=_SinglePortRegistry(
                RevitWallThicknessExecutionPort(
                    transport,
                    clock=execution_clock.now,
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
            clock=execution_clock,
        )
        topology_registry = MaterializationTopologyRegistry()
        topology_registry.register(_topology(config))

        approval_admission = build_admission(
            changeset_store,
            approval_scope_store,
        )
        owner_ports = CanonicalWorkflowOwnerPorts(
            snapshot_registry=snapshot_registry,
            freshness_resolver=FreshnessResolver(DirtyMap()),
            workflow_artifact_store=artifact_store,
            host_revision_observation=host_revision,
            canonical_operations=MVP_CANONICAL_OPERATIONS,
            impact_analyzer=ImpactAnalyzer(),
            impact_store=impact_store,
            approval_scope_planner=ApprovalScopePlanner(),
            approval_scope_store=approval_scope_store,
            changeset_builder=ChangeSetBuilder(),
            changeset_store=changeset_store,
            materialization_planner=MaterializationPlanner(),
            materialization_plan_store=materialization_store,
            topology_registry=topology_registry,
            topology_environment_id=_TOPOLOGY_ENVIRONMENT_ID,
            topology_revision=_TOPOLOGY_REVISION,
            execution_plan_store=execution_store,
            revision_barrier=RevisionBarrier(host_revision),
            gateway_authorization=gateway,
            gateway_authorization_store=gateway_store,
            coordination_clock=_UtcCoordinationClock(),
            provider_binding_store=provider_store,
            dispatch_intent_store=dispatch_store,
            execution_recovery_projection=project_execution_recovery,
            saga_store=saga_store,
            execution_coordinator=coordinator,
            reconciliation_service=reconciliation,
            convergence_verifier=convergence,
            semantic_reconstruction=semantic_boundary,
            preview_port=_ReferencePreviewPort(),
            approval_admission=approval_admission,
            materialization_routing=_ReferenceMaterializationRouting(config),
            provider_execution_snapshot=(
                RevitWallThicknessProviderExecutionSnapshotBoundary(
                    changeset_store=changeset_store,
                    snapshot_registry=snapshot_registry,
                    provider_snapshot_factory=_provider_snapshot_factory(config),
                )
            ),
        )
        services = DefaultWorkflowServices(
            operation_resolver=OperationResolver((SET_WALL_THICKNESS_V1,)),
            parameter_binder=ParameterBinder(
                MVP_CANONICAL_OPERATIONS,
                MVP_BINDING_RECIPES,
            ),
            artifact_store=artifact_store,
            external_owners=owner_ports,
        )
        runtime = LangGraphWorkflowRuntime(
            services=services,
            checkpointer=checkpointer,
        )
        flow = WallThicknessProductFlow(
            request_store=request_store,
            workflow_runtime=runtime,
            saga_store=saga_store,
            start_gate=start_gate,
        )
        return RevitWallThicknessRuntimeComposition(
            flow=flow,
            runtime=runtime,
            request_store=request_store,
            start_gate=start_gate,
            snapshot_registry=snapshot_registry,
            saga_store=saga_store,
            _closeables=tuple(closeables),
        )
    except Exception:
        _close_many(tuple(closeables))
        raise


__all__ = [
    "RevitWallThicknessCompositionConfig",
    "RevitWallThicknessRuntimeComposition",
    "build_revit_wall_thickness_reference_composition",
]
