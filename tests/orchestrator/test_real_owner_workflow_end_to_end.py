"""Task 9：真实 owner LangGraph E2E acceptance。

本模块只保留真正的环境/IO/presentation boundary doubles。Impact、Approval Scope、
ChangeSet、Materialization、Execution Planning、Gateway V2、Provider Binding V2、
Execution Saga V2、Reconciliation V2 与 convergence 均使用仓库 public production owner。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from design_approval_scope import ApprovalScopePlanner, CanonicalAspect, InMemoryApprovalScopeStore
from design_changeset import ChangeSetBuilder, InMemoryChangeSetStore, canonical_hash
from design_convergence import (
    CrossHostConvergenceVerifier,
    build_materialization_canonical_evidence,
)
from design_execution_coordination import (
    CrossHostReadinessBarrier,
    HostCommitted,
    HostReadinessReceipt,
    MaterializedExecutionSagaCoordinator,
    ReadinessStatus,
    compute_readiness_receipt_hash,
    project_execution_recovery,
)
from design_execution_planning import (
    HostRuntimeRef,
    InMemoryExecutionPlanV2Store,
    MaterializationRoutingEvidence,
    MaterializationRuntimeRoute,
    compute_materialization_routing_hash,
)
from design_execution_reconciliation import (
    ActualChange,
    ActualChangeKind,
    ActualDelta,
    ExecutionReconciliationServiceV2,
    InMemoryExecutionSagaStoreV2,
    InMemoryHostDispatchIntentStore,
    VerificationContractEvidence,
    VerificationEvidenceBundle,
    VerificationSubjectEvidence,
    compute_actual_change_hash,
    compute_actual_delta_hash,
    compute_verification_evidence_bundle_hash,
)
from design_gateway_authorization import (
    ApprovalAdmission,
    GatewayAuthorizationServiceV2,
    InMemoryGatewayAuthorizationStoreV2,
    compute_admission_fingerprint,
)
from design_impact import ImpactAnalyzer, InMemoryImpactAnalysisStore
from design_materialization_planning import InMemoryMaterializationPlanStore, MaterializationPlanner
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
from design_orchestrator.canonical_owner_ports import (
    CanonicalWorkflowOwnerPorts,
    ContextFreshnessInputs,
)
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    OperationResolutionInputs,
    ParameterBindingInputs,
)
from design_orchestrator.langgraph_runtime import LangGraphWorkflowRuntime
from design_orchestrator.operation_resolver import (
    ClassificationGuarantee,
    OperationResolver,
    ResolutionContext,
    SemanticEligibilityContext,
    SemanticEligibilityEntity,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowPhase,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)
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
from semantic_runtime import (
    ContractType,
    Coverage,
    DirtyMap,
    FreshnessResolver,
    InMemorySnapshotRegistry,
    ReconstructionResult,
    RevisionBarrier,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotKind,
)

_DSN = os.getenv("DSP_TEST_POSTGRES_DSN")
_DOCUMENT_REF = "DOC-TASK9"
_ENVIRONMENT = SemanticEnvironmentRef("semantic-env-task9", "e" * 64)
_PROJECTION = SemanticProjectionRef(
    "projection-task9",
    "f" * 64,
    "semantic-model-v1",
    "provider-set-task9",
    "mapping-set-task9",
)

requires_postgres = pytest.mark.skipif(
    not _DSN,
    reason="DSP_TEST_POSTGRES_DSN is required",
)


@dataclass(frozen=True, slots=True)
class _WallCapabilityProfile:
    """OperationResolver 所需的 provider capability 环境事实。"""

    provider_server: str = "revit.task9"
    provider_tool: str = "set_wall_thickness"
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
    verification_contract: dict[str, Any] = None  # type: ignore[assignment]
    input_schema: dict[str, Any] = None  # type: ignore[assignment]
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
                    "native_ids": {"type": "array", "items": {"type": "string"}},
                    "canonical_arguments": {"type": "object"},
                },
                "required": ["native_ids", "canonical_arguments"],
                "additionalProperties": False,
            },
        )


class _SemanticBoundary:
    """只提供 Host/semantic reconstruction 输入；freshness 规则由真实 owner 执行。"""

    def __init__(self) -> None:
        self.operation_ready = False
        self.reconstruction_calls: list[tuple[str, str]] = []

    def resolve_host_context(self, task_id: str) -> StableRef:
        return StableRef(f"context-request:{task_id}", "c" * 64)

    def load_context_inputs(self, context_ref: StableRef) -> ContextFreshnessInputs:
        del context_ref
        return ContextFreshnessInputs(
            task_id="task9-real-owner",
            project_id="project-task9",
            document_ref=_DOCUMENT_REF,
            root_entities=("WALL-001",),
        )

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs:
        return OperationResolutionInputs(
            profiles=(_WallCapabilityProfile(),),
            context=ResolutionContext(
                host_provider_servers=frozenset({"revit.task9"}),
                semantic_context=SemanticEligibilityContext(
                    context_snapshot_id=snapshot_ref.ref_id,
                    context_snapshot_hash=snapshot_ref.content_hash or "",
                    document_ref=_DOCUMENT_REF,
                    semantic_environment_ref=_ENVIRONMENT.environment_id,
                    entities=(
                        SemanticEligibilityEntity(
                            semantic_id="WALL-001",
                            canonical_classifications=("ifc:IfcWall",),
                            classification_guarantee=ClassificationGuarantee(True),
                        ),
                    ),
                ),
            ),
        )

    def load_parameter_binding_inputs(
        self,
        task_id: str,
        operation_space_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> ParameterBindingInputs:
        """直接消费 graph 持久化的 exact ContextSnapshot ref，不从 operation-space 反推。"""

        del operation_space_ref
        return ParameterBindingInputs(
            proposal=OperationProposal(
                "set_wall_thickness.v1",
                {"thickness": {"value": 300, "unit": "mm"}},
            ),
            context=ParameterBindingContext(
                context_snapshot_id=context_snapshot_ref.ref_id,
                context_snapshot_hash=context_snapshot_ref.content_hash or "",
                document_ref=_DOCUMENT_REF,
                semantic_environment_ref=_ENVIRONMENT.environment_id,
                selection=("WALL-001",),
            ),
        )

    def reconstruct(self, contract, expected_host_revision: str):
        self.reconstruction_calls.append((contract.contract_type.value, expected_host_revision))
        if contract.contract_type is ContractType.OPERATION and not self.operation_ready:
            return AsyncOperationRef(
                kind=AsyncOperationKind.RECONSTRUCTION_JOB,
                owner="semantic-runtime",
                operation_id="task9-reconstruction",
            )
        return ReconstructionResult(
            document_ref=contract.coverage.document_ref,
            host_revision=expected_host_revision,
            coverage=contract.coverage,
            guarantees=contract.requirements,
            projection_ref=_PROJECTION,
            semantic_environment_ref=_ENVIRONMENT,
        )


class _HostRevisionObservation:
    """Host revision 是环境观测，不在测试边界复制 revision-barrier 规则。"""

    def current_revision(self, document_ref: str) -> str:
        assert document_ref == _DOCUMENT_REF
        return "42"


class _PreviewBoundary:
    """Preview 只返回 presentation ref，不复制 ChangeSet truth。"""

    def preview(self, changeset_ref: StableRef) -> StableRef:
        return StableRef(f"preview:{changeset_ref.ref_id}", "b" * 64)


class _GatewayClock:
    def now(self) -> datetime:
        return datetime.fromisoformat("2026-09-24T10:00:00+00:00")


class _ExecutionClock:
    def now(self) -> str:
        return "2026-09-24T10:00:00Z"


class _ApprovalAdmissionBoundary:
    """Human/policy 边界只组装 admission input；授权真相仍由 Gateway V2 生成。"""

    def __init__(self, changeset_store, scope_store) -> None:
        self._changeset_store = changeset_store
        self._scope_store = scope_store

    def request_approval(self, changeset_ref: StableRef) -> ApprovalAdmission:
        changeset = self._changeset_store.get(changeset_ref.ref_id)
        boundary = self._scope_store.get_boundary(f"SCOPE-{changeset.changeset_id}")
        draft = ApprovalAdmission(
            admission_id=f"ADM-{changeset.changeset_id}",
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
            semantic_environment_ref=changeset.semantic_environment_ref,
            approver="user:task9-approver",
            policy_snapshot_hash="a" * 64,
            policy_allowed_operations=(changeset.root_operation.canonical_operation,),
            approved_at="2026-09-24T09:00:00Z",
            expires_at="2026-09-24T17:00:00Z",
            admission_fingerprint="0" * 64,
        )
        return replace(
            draft,
            admission_fingerprint=compute_admission_fingerprint(draft),
        )


class _MaterializationRoutingBoundary:
    """只提供 Host runtime routing evidence，不实现 planning 规则。"""

    def routing_evidence(self, materialization_plan, topology_snapshot):
        slot_by_id = {
            slot.materialization_slot_id: slot
            for slot in topology_snapshot.slots
        }
        routes = tuple(
            MaterializationRuntimeRoute(
                materialization_id=intent.materialization_id,
                host_runtime_ref=HostRuntimeRef(
                    host_type=intent.required_host_type,
                    host_instance_id="REVIT-TASK9",
                    document_ref=slot_by_id[intent.materialization_slot_id].document_ref,
                ),
            )
            for intent in materialization_plan.intents
        )
        return MaterializationRoutingEvidence(
            routing_snapshot_id="MRS-TASK9",
            routes=routes,
            routing_snapshot_hash=compute_materialization_routing_hash(routes),
        )


class _ProviderExecutionSnapshotBoundary:
    """只发布 runtime/provider evidence；选择规则由 Provider Binding V2 执行。"""

    def __call__(self, execution_slice):
        unit = execution_slice.execution_units[0]
        target_draft = NativeTargetBindingEvidence(
            semantic_id=unit.targets[0],
            host_type=execution_slice.host_runtime_ref.host_type,
            document_ref=execution_slice.host_runtime_ref.document_ref,
            native_id="REVIT-UNIQUE-ID-TASK9",
            native_kind="Wall",
            host_binding_fingerprint="0" * 64,
        )
        target = replace(
            target_draft,
            host_binding_fingerprint=compute_host_binding_fingerprint(target_draft),
        )
        candidate_draft = ProviderExecutionCandidate(
            provider_server="provider.revit.wall",
            provider_tool="set_wall_thickness",
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
                    "native_ids": {"type": "array", "items": {"type": "string"}},
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
            native_binding_metadata={"identity_source": "task9-runtime-boundary"},
        )
        snapshot_draft = ProviderExecutionSnapshotV2(
            snapshot_id="PESV2-TASK9",
            materialization_id=execution_slice.materialization_id,
            materialization_plan_hash=execution_slice.materialization_plan_hash,
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            host_runtime_ref=execution_slice.host_runtime_ref,
            native_target_bindings=(target,),
            provider_candidates=(candidate,),
            candidate_binding_materials={candidate.candidate_fingerprint: material},
            valid_until="2026-09-24T17:00:00Z",
            snapshot_hash="0" * 64,
        )
        return replace(
            snapshot_draft,
            snapshot_hash=compute_provider_snapshot_hash_v2(snapshot_draft),
        )


class _ReadinessPort:
    def check(self, execution_slice, authority, binding_set):
        draft = HostReadinessReceipt(
            materialization_id=execution_slice.materialization_id,
            materialization_plan_hash=execution_slice.materialization_plan_hash,
            execution_slice_hash=execution_slice.execution_slice_hash,
            binding_set_hash=binding_set.binding_set_hash,
            grant_hash=authority.grant_hash,
            host_runtime_ref=execution_slice.host_runtime_ref,
            observed_revision=42,
            status=ReadinessStatus.READY,
            failure_code=None,
            receipt_hash="0" * 64,
        )
        return replace(draft, receipt_hash=compute_readiness_receipt_hash(draft))


class _ReadinessRegistry:
    def __init__(self) -> None:
        self._port = _ReadinessPort()

    def resolve(self, runtime_ref):
        assert runtime_ref.host_type == "revit"
        return self._port


class _CountingHostPort:
    """唯一外部 mutation boundary；实际 reconciliation 数据仍使用 owner public contracts。"""

    def __init__(self) -> None:
        self.calls: list[tuple[object, object, object, object]] = []

    def execute(self, execution_slice, authority, binding_set, dispatch_context):
        self.calls.append((execution_slice, authority, binding_set, dispatch_context))
        unit = execution_slice.execution_units[0]
        change_draft = ActualChange(
            change_kind=ActualChangeKind.MODIFY,
            semantic_id=unit.targets[0],
            canonical_kind="ifc:IfcWall",
            changed_aspects=(CanonicalAspect.PROPERTIES,),
            source_execution_unit_hash=unit.execution_unit_hash,
            actual_change_hash="0" * 64,
        )
        change = replace(
            change_draft,
            actual_change_hash=compute_actual_change_hash(change_draft),
        )
        delta_draft = ActualDelta(
            actual_delta_id=f"AD-TASK9-{len(self.calls)}",
            grant_hash=authority.grant_hash,
            binding_set_hash=authority.binding_set_hash,
            execution_slice_hash=execution_slice.execution_slice_hash,
            changeset_hash=authority.changeset_hash,
            approved_scope_hash=authority.approved_scope_hash,
            host_instance_id=authority.host_instance_id,
            document_ref=execution_slice.host_runtime_ref.document_ref,
            revision_before=42,
            revision_after=43,
            changes=(change,),
            actual_delta_hash="0" * 64,
        )
        delta = replace(
            delta_draft,
            actual_delta_hash=compute_actual_delta_hash(delta_draft),
        )
        return HostCommitted(actual_delta=delta, committed_at="2026-09-24T10:01:00Z")


class _HostRegistry:
    def __init__(self, port: _CountingHostPort) -> None:
        self._port = port

    def resolve(self, runtime_ref):
        assert runtime_ref.host_type == "revit"
        return self._port


class _EvidenceBoundary:
    """发布 post-execution measurement evidence；验证/收敛判断由真实 owners 完成。"""

    def build_bundle(
        self,
        *,
        execution_slice,
        authority,
        binding_set,
        actual_delta,
        canonical_changeset,
        approval_scope_boundary,
    ):
        assert authority.execution_slice_hash == execution_slice.execution_slice_hash
        assert authority.binding_set_hash == binding_set.binding_set_hash
        del approval_scope_boundary
        projection = SemanticProjectionRef(
            "projection-post-task9",
            canonical_hash({"task9": "projection"}),
            "ifc43+task9",
            canonical_hash({"task9": "providers"}),
            canonical_hash({"task9": "mappings"}),
            canonical_hash({"task9": "facts"}),
        )
        snapshot = SemanticSnapshot(
            snapshot_id="PS-TASK9-POST",
            kind=SnapshotKind.PLANNING,
            project_id=canonical_changeset.project_id,
            freshness_contract_id="FC-TASK9-POST",
            freshness_contract_hash=canonical_hash({"task9": "freshness"}),
            document_ref=actual_delta.document_ref,
            base_host_revision=str(actual_delta.revision_after),
            coverage=Coverage(actual_delta.document_ref, ("WALL-001",)),
            projection_ref=projection,
            semantic_environment_ref=_ENVIRONMENT,
            aspect_guarantees=(),
            hash=canonical_hash({"task9": actual_delta.actual_delta_hash}),
        )
        subject = VerificationSubjectEvidence(
            semantic_id="WALL-001",
            canonical_kind="ifc:IfcWall",
            properties={"dsp:WallThickness": {"value": 300.0, "unit": "mm"}},
            placement=None,
            geometry_evidence=None,
            relationships=(),
            constraints=(),
            classification=("ifc:IfcWall",),
            evidence_aspects=(CanonicalAspect.PROPERTIES,),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.hash,
            projection_ref=projection,
        )
        contract = SET_WALL_THICKNESS_V1.verification_contract
        draft = VerificationEvidenceBundle(
            evidence_bundle_id="VEB-TASK9",
            changeset_hash=canonical_changeset.changeset_hash,
            execution_slice_hash=execution_slice.execution_slice_hash,
            actual_delta_hash=actual_delta.actual_delta_hash,
            semantic_environment_ref=_ENVIRONMENT,
            post_execution_snapshot_ref=snapshot,
            post_execution_projection_ref=projection,
            base_host_revision=str(actual_delta.revision_after),
            baseline_snapshot_ref=None,
            baseline_projection_ref=None,
            contract_evidence=(
                VerificationContractEvidence(
                    contract_ref=canonical_hash(contract),
                    contract_body=contract,
                ),
            ),
            subject_evidence=(subject,),
            baseline_subject_evidence=(),
            evidence_bundle_hash="0" * 64,
        )
        return replace(
            draft,
            evidence_bundle_hash=compute_verification_evidence_bundle_hash(draft),
        )

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
        return build_materialization_canonical_evidence(
            materialization_id=materialization_id,
            execution_slice=execution_slice,
            actual_delta=actual_delta,
            verification_result=verification_result,
            verification_evidence_bundle=verification_bundle,
            convergence_profile=convergence_profile,
        )


def _topology() -> MaterializationTopologySnapshot:
    draft = MaterializationTopologySnapshot(
        topology_environment_id="TOPOLOGY-TASK9",
        topology_revision=1,
        slots=(
            MaterializationSlot(
                materialization_slot_id="SLOT-TASK9",
                semantic_target_ref="WALL-001",
                required_host_type="revit",
                document_ref=_DOCUMENT_REF,
                requirement=MaterializationRequirement.REQUIRED,
            ),
        ),
        topology_snapshot_hash="0" * 64,
    )
    return replace(draft, topology_snapshot_hash=compute_topology_snapshot_hash(draft))


def _dsn() -> str:
    assert _DSN is not None
    return _DSN


def _request(task_id: str) -> WorkflowStartRequest:
    return WorkflowStartRequest(
        task_id=task_id,
        request_data={"intent": "set selected wall thickness to 300 mm"},
        initial_host_ref=StableRef("host-task9", "9" * 64),
    )


def _build_real_owner_case(task_id: str):
    artifact_store = create_postgres_artifact_store(_dsn())
    checkpointer = create_postgres_checkpointer(_dsn())
    semantic_boundary = _SemanticBoundary()
    host_revision = _HostRevisionObservation()
    snapshot_registry = InMemorySnapshotRegistry()
    impact_store = InMemoryImpactAnalysisStore()
    scope_store = InMemoryApprovalScopeStore()
    changeset_store = InMemoryChangeSetStore()
    materialization_store = InMemoryMaterializationPlanStore()
    execution_store = InMemoryExecutionPlanV2Store()
    gateway_store = InMemoryGatewayAuthorizationStoreV2()
    gateway = GatewayAuthorizationServiceV2(gateway_store)
    provider_store = InMemoryProviderBindingSetV2Store()
    saga_store = InMemoryExecutionSagaStoreV2()
    dispatch_store = InMemoryHostDispatchIntentStore()
    reconciliation = ExecutionReconciliationServiceV2(store=saga_store)
    convergence = CrossHostConvergenceVerifier()
    host_port = _CountingHostPort()
    coordinator = MaterializedExecutionSagaCoordinator(
        readiness_barrier=CrossHostReadinessBarrier(_ReadinessRegistry()),
        reconciliation=reconciliation,
        host_registry=_HostRegistry(host_port),
        dispatch_intents=dispatch_store,
        evidence_port=_EvidenceBoundary(),
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
        provider_execution_snapshot=_ProviderExecutionSnapshotBoundary(),
    )
    services = DefaultWorkflowServices(
        operation_resolver=OperationResolver((SET_WALL_THICKNESS_V1,)),
        parameter_binder=ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES),
        artifact_store=artifact_store,
        external_owners=adapter,
    )
    runtime = LangGraphWorkflowRuntime(services=services, checkpointer=checkpointer)
    return SimpleNamespace(
        task_id=task_id,
        runtime=runtime,
        checkpointer=checkpointer,
        artifact_store=artifact_store,
        semantic_boundary=semantic_boundary,
        snapshot_registry=snapshot_registry,
        impact_store=impact_store,
        scope_store=scope_store,
        changeset_store=changeset_store,
        materialization_store=materialization_store,
        execution_store=execution_store,
        gateway_store=gateway_store,
        provider_store=provider_store,
        saga_store=saga_store,
        dispatch_store=dispatch_store,
        host_port=host_port,
    )


def _close_case(case) -> None:
    case.artifact_store.close()
    case.checkpointer.close()


@requires_postgres
def test_real_owner_happy_path_reaches_completed_and_resolves_final_refs() -> None:
    """A：真实 owner composition 必须经过 HITL/async wait 并以真实 Saga success 收口。"""

    case = _build_real_owner_case("task9-real-owner-happy-a93b6651")
    try:
        proposal_wait = case.runtime.start(_request(case.task_id))
        assert proposal_wait.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert proposal_wait.pending_interaction is not None

        freshness_wait = case.runtime.resume(
            case.task_id,
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                pause_id=proposal_wait.pending_interaction.pause_id,
            ),
        )
        assert freshness_wait.phase is WorkflowPhase.ENSURE_OPERATION_FRESHNESS
        assert freshness_wait.async_operation_ref == AsyncOperationRef(
            kind=AsyncOperationKind.RECONSTRUCTION_JOB,
            owner="semantic-runtime",
            operation_id="task9-reconstruction",
        )

        case.semantic_boundary.operation_ready = True
        completed = case.runtime.resume(
            case.task_id,
            WorkflowResumeCommand(
                resume_kind="ASYNC_OPERATION_COMPLETED",
                payload={"operation_id": "task9-reconstruction"},
            ),
        )
        assert completed.phase is WorkflowPhase.COMPLETED
        assert completed.operation_ref is not None
        assert completed.changeset_ref is not None
        assert completed.approval_ref is not None
        assert completed.execution_plan_ref is not None
        assert completed.saga_id is not None

        assert case.artifact_store.get(completed.operation_ref) is not None
        assert case.changeset_store.get(completed.changeset_ref.ref_id) is not None
        assert case.gateway_store.get_approval(completed.approval_ref.ref_id) is not None
        assert case.execution_store.get(completed.execution_plan_ref.ref_id) is not None
        assert case.saga_store.get_saga(completed.saga_id) is not None
        assert len(case.host_port.calls) == 1
    finally:
        _close_case(case)
