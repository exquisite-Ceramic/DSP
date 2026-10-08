"""Cross-Host Product Vertical 的 production/reference composition seams。

当前模块先提供 proposal subject builder；后续 reference flow resolver 继续在同一模块组合，
但任何业务 authority 仍由 ProductTask、Workflow Artifact 与 Host READ owners 持有。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
from threading import RLock
from types import MappingProxyType

from design_approval_scope import ApprovalScopePlanner, InMemoryApprovalScopeStore
from design_changeset import ChangeSetBuilder, InMemoryChangeSetStore
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
from design_execution_reconciliation.postgres_evidence import (
    PostgresReconciliationEvidenceStore,
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
    MaterializationTopologyRegistry,
    MaterializationTopologySnapshot,
)
from design_orchestrator.artifact_postgres import create_postgres_artifact_store
from design_orchestrator.canonical_operations import (
    MVP_CANONICAL_OPERATIONS,
    SET_WALL_THICKNESS_V1,
)
from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.default_workflow_services import DefaultWorkflowServices
from design_orchestrator.langgraph_checkpoint_reader import (
    LangGraphWorkflowCheckpointReader,
)
from design_orchestrator.langgraph_runtime import LangGraphWorkflowRuntime
from design_orchestrator.operation_resolver import OperationResolver
from design_orchestrator.parameter_binder import MVP_BINDING_RECIPES, ParameterBinder
from design_orchestrator.proposal_decision_postgres import (
    PostgresProposalDecisionStore,
)
from design_orchestrator.interaction_artifacts import CrossHostOperationProposalSubjectV2
from design_orchestrator.operation_resolver import ResolutionResult
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
from revit_sidecar import (
    RevitContextReadPort,
    RevitWallThicknessExecutionPort,
    RevitWallThicknessReadinessPort,
    RevitWallThicknessSnapshotReadPort,
)
from revit_sidecar.design_fact_adapter import DesignFactAdapter as RevitDesignFactAdapter
from semantic_runtime import (
    AspectGuarantee,
    AssuranceLevel,
    CoverageState,
    DirtyMap,
    FreshnessResolver,
    HostBinding,
    IdentityRegistry,
    InMemorySnapshotRegistry,
    ReconstructionResult,
    RevisionBarrier,
    SemanticDepth,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
)
from semantic_service import SemanticClaim

from .accepted_input import AcceptedProductTaskInputV2
from .autocad_evidence import AutoCadWallThicknessVerificationEvidencePort
from .autocad_execution import AutoCadWallThicknessProviderExecutionSnapshotBoundary
from .cross_host_flow import CrossHostProductFlow
from .cross_host_observation import (
    CrossHostPlanningRuntimePort,
    CrossHostWallThicknessObservationReader,
)
from .cross_host_planning import CrossHostOperationFreshnessBoundary
from .cross_host_reference_composition import (
    CrossHostRuntimePortBinding,
    CrossHostVerificationEvidenceRouter,
    ProposalDecisionContinuationAdapter,
    build_autocad_wall_thickness_runtime_binding,
    build_cross_host_planning_composition,
    build_cross_host_runtime_registries,
)
from .postgres_request_store import create_postgres_product_task_request_store
from .postgres_start_gate import (
    PostgresProductTaskResumeConsumeGate,
    PostgresProductTaskStartGate,
)
from .query import ProductTaskQueryService
from .revit_evidence import RevitWallThicknessVerificationEvidencePort
from .revit_execution import RevitWallThicknessProviderExecutionSnapshotBoundary
from .revit_operation_resolution import RevitWallThicknessSemanticBoundary
from .revit_reference_composition import (
    _ReferencePreviewPort,
    _ReferenceWallCapabilityProfile,
    _UtcCoordinationClock,
    _UtcExecutionClock,
    _close_many,
    _semantic_environment,
)


@dataclass(frozen=True, slots=True)
class _AcceptedBindingMember:
    """从 server-owned accepted binding body 投影出的 exact Host member read view。"""

    host_kind: str
    role: str
    configured_reference_id: str
    configured_reference_hash: str
    transport_locator: str
    host_instance_id: str
    document_id: str
    native_target_id: str
    host_binding_fingerprint: str


@dataclass(frozen=True, slots=True)
class _AcceptedBinding:
    """proposal builder 只读所需的 V2 binding 结构视图。"""

    session_ref: str
    project_id: str
    semantic_target_id: str
    semantic_environment_id: str
    semantic_environment_hash: str
    topology_environment_id: str
    topology_revision: int
    topology_snapshot_hash: str
    initiating_host_kind: str
    members: tuple[_AcceptedBindingMember, _AcceptedBindingMember]
    binding_hash: str

    def member(self, host_kind: str) -> _AcceptedBindingMember:
        """按 exact Host kind 返回 member；禁止 fuzzy/latest fallback。"""

        matches = tuple(item for item in self.members if item.host_kind == host_kind)
        if len(matches) != 1:
            raise ValueError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: exact Host member is unavailable"
            )
        return matches[0]


def _required_text(value: object, field_name: str) -> str:
    """规范化 accepted-input locator，并区分类型错误与空值错误。"""

    if not isinstance(value, str):
        raise TypeError(
            f"CROSS_HOST_PROPOSAL_LINEAGE_INVALID: {field_name} must be a string"
        )
    if not value.strip():
        raise ValueError(
            f"CROSS_HOST_PROPOSAL_LINEAGE_INVALID: {field_name} must be non-blank"
        )
    return value.strip()


def _binding_from_accepted(accepted: AcceptedProductTaskInputV2) -> _AcceptedBinding:
    """从 ProductTask owner 的 immutable JSON body 重建只读结构，不创建第二份 truth。"""

    payload = accepted.session_binding_payload
    raw_members = payload.get("members")
    if not isinstance(raw_members, list):
        raise TypeError(
            "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted binding members must be a list"
        )
    if len(raw_members) != 2:
        raise ValueError(
            "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted binding requires two members"
        )
    members = []
    for raw in raw_members:
        if not isinstance(raw, Mapping):
            raise TypeError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted member body must be a mapping"
            )
        members.append(
            _AcceptedBindingMember(
                host_kind=_required_text(raw.get("host_kind"), "member.host_kind"),
                role=_required_text(raw.get("role"), "member.role"),
                configured_reference_id=_required_text(
                    raw.get("configured_reference_id"),
                    "member.configured_reference_id",
                ),
                configured_reference_hash=_required_text(
                    raw.get("configured_reference_hash"),
                    "member.configured_reference_hash",
                ),
                transport_locator=_required_text(
                    raw.get("transport_locator"),
                    "member.transport_locator",
                ),
                host_instance_id=_required_text(
                    raw.get("host_instance_id"),
                    "member.host_instance_id",
                ),
                document_id=_required_text(raw.get("document_id"), "member.document_id"),
                native_target_id=_required_text(
                    raw.get("native_target_id"),
                    "member.native_target_id",
                ),
                host_binding_fingerprint=_required_text(
                    raw.get("host_binding_fingerprint"),
                    "member.host_binding_fingerprint",
                ),
            )
        )
    by_kind = {item.host_kind: item for item in members}
    if set(by_kind) != {"AUTOCAD", "REVIT"} or len(by_kind) != 2:
        raise ValueError(
            "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: required Host set is AUTOCAD + REVIT"
        )
    if by_kind["AUTOCAD"].role != "BOUND_REQUIRED" or by_kind["REVIT"].role != "INITIATOR":
        raise ValueError(
            "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted Host roles are invalid"
        )

    binding_hash = _required_text(payload.get("binding_hash"), "binding_hash")
    if binding_hash != accepted.session_binding_hash:
        raise ValueError(
            "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted binding hash mismatch"
        )
    return _AcceptedBinding(
        session_ref=_required_text(payload.get("session_ref"), "session_ref"),
        project_id=_required_text(payload.get("project_id"), "project_id"),
        semantic_target_id=_required_text(
            payload.get("semantic_target_id"),
            "semantic_target_id",
        ),
        semantic_environment_id=_required_text(
            payload.get("semantic_environment_id"),
            "semantic_environment_id",
        ),
        semantic_environment_hash=_required_text(
            payload.get("semantic_environment_hash"),
            "semantic_environment_hash",
        ),
        topology_environment_id=_required_text(
            payload.get("topology_environment_id"),
            "topology_environment_id",
        ),
        topology_revision=payload.get("topology_revision"),
        topology_snapshot_hash=_required_text(
            payload.get("topology_snapshot_hash"),
            "topology_snapshot_hash",
        ),
        initiating_host_kind=_required_text(
            payload.get("initiating_host_kind"),
            "initiating_host_kind",
        ),
        members=(by_kind["AUTOCAD"], by_kind["REVIT"]),
        binding_hash=binding_hash,
    )


class CrossHostOperationProposalBuilder:
    """从 accepted input + OperationResolver result + 两端 fresh READ 构造 immutable subject。"""

    def __init__(
        self,
        *,
        accepted_input_reader: object,
        workflow_artifact_store: object,
        observation_reader: object,
    ) -> None:
        """只保存既有 owner/read seams；构造阶段不访问 Host。"""

        if not callable(getattr(accepted_input_reader, "get_v2", None)):
            raise TypeError("accepted_input_reader must provide get_v2")
        if not callable(getattr(workflow_artifact_store, "get", None)):
            raise TypeError("workflow_artifact_store must provide get")
        if not callable(getattr(observation_reader, "read", None)):
            raise TypeError("observation_reader must provide read")
        self._accepted_input_reader = accepted_input_reader
        self._workflow_artifact_store = workflow_artifact_store
        self._observation_reader = observation_reader

    def build(
        self,
        task_id: str,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> CrossHostOperationProposalSubjectV2:
        """读取 exact accepted task/action-space，并展示两端当前 wall-thickness observation。"""

        normalized_task_id = _required_text(task_id, "task_id")
        if not isinstance(operation_ref, StableRef):
            raise TypeError("operation_ref must be StableRef")
        if not isinstance(context_snapshot_ref, StableRef):
            raise TypeError("context_snapshot_ref must be StableRef")

        accepted = self._accepted_input_reader.get_v2(normalized_task_id)
        if accepted is None:
            raise ValueError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: V2 accepted input is unavailable"
            )
        if not isinstance(accepted, AcceptedProductTaskInputV2):
            raise TypeError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: V2 accepted input has invalid type"
            )
        request = accepted.request
        if request.task_id != normalized_task_id:
            raise ValueError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted task identity mismatch"
            )
        binding = _binding_from_accepted(accepted)
        if (
            request.project_id != binding.project_id
            or request.session_ref != binding.session_ref
            or request.session_binding_hash != binding.binding_hash
            or binding.initiating_host_kind != "REVIT"
        ):
            raise ValueError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: request/binding authority mismatch"
            )

        resolution = self._workflow_artifact_store.get(operation_ref)
        if not isinstance(resolution, ResolutionResult):
            raise TypeError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: operation ref is not ResolutionResult"
            )
        supported = tuple(
            item
            for item in resolution.resolved_operations
            if item.canonical_operation == "set_wall_thickness.v1"
        )
        if len(supported) != 1 or len(resolution.resolved_operations) != 1:
            raise ValueError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: expected one supported wall operation"
            )

        thickness = request.intent_arguments.get("thickness")
        if not isinstance(thickness, Mapping):
            raise TypeError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: V2 thickness intent must be a mapping"
            )
        arguments = MappingProxyType(
            {
                "targets": (binding.semantic_target_id,),
                "thickness": MappingProxyType(
                    {
                        "unit": thickness.get("unit"),
                        "value": thickness.get("value"),
                    }
                ),
            }
        )

        observations = tuple(
            self._observation_reader.read(
                binding=binding,
                member=member,
                command_id=(
                    f"cross-host-proposal:{normalized_task_id}:{member.host_kind.lower()}"
                ),
            )
            for member in binding.members
        )
        return CrossHostOperationProposalSubjectV2(
            request_hash=request.request_hash,
            session_binding_hash=binding.binding_hash,
            topology_snapshot_hash=binding.topology_snapshot_hash,
            semantic_target_id=binding.semantic_target_id,
            semantic_environment_id=binding.semantic_environment_id,
            semantic_environment_hash=binding.semantic_environment_hash,
            canonical_operation=supported[0].canonical_operation,
            canonical_arguments=arguments,
            observations=observations,
        )


class CrossHostCanonicalWorkflowOwnerPorts(CanonicalWorkflowOwnerPorts):
    """只为 Cross-Host composition 增加 proposal builder，不扩张核心 owner contract。"""

    __slots__ = ("_cross_host_proposal_builder",)

    def __init__(
        self,
        *,
        cross_host_proposal_builder: object,
        **owner_dependencies: object,
    ) -> None:
        """先构造冻结的 canonical owner，再保存 composition-only proposal extension。"""

        if not callable(getattr(cross_host_proposal_builder, "build", None)):
            raise TypeError("cross_host_proposal_builder must provide build")
        super().__init__(**owner_dependencies)
        self._cross_host_proposal_builder = cross_host_proposal_builder

    def build_operation_proposal_subject(
        self,
        task_id: str,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> CrossHostOperationProposalSubjectV2:
        """把 V2 human subject 构造委托给显式 builder；不保存第二份 owner truth。"""

        return self._cross_host_proposal_builder.build(
            task_id,
            operation_ref,
            context_snapshot_ref,
        )


class CrossHostProductFlowResolver:
    """从 server accepted V2 input 解析 exact task 的可重建 workflow facade。

    缓存只持有进程内 composition handles 和输入指纹，不保存任何可修改的
    ProductTask request、binding、decision 或 checkpoint truth。进程重启后
    factory 必须再次从 authoritative accepted input 安全重建。
    """

    def __init__(
        self,
        flow_factory: Callable[[AcceptedProductTaskInputV2], object],
    ) -> None:
        """保存 lazy factory；构造时不触发 Host I/O 或读取客户端 SQLite。"""

        if not callable(flow_factory):
            raise TypeError("flow_factory must be callable")
        self._flow_factory = flow_factory
        self._lock = RLock()
        self._flows: dict[str, tuple[tuple[str, str, str], object]] = {}

    @staticmethod
    def _fingerprint(
        accepted: AcceptedProductTaskInputV2,
    ) -> tuple[str, str, str]:
        """把 accepted owner body 压缩成缓存校验标识，不创建新 authority。"""

        body = json.dumps(
            dict(accepted.session_binding_payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return (
            accepted.request.request_hash,
            accepted.session_binding_hash,
            sha256(body).hexdigest(),
        )

    def get_flow(self, accepted: AcceptedProductTaskInputV2):
        """same task/body 只构造一次；same task/body drift 必须 fail closed。"""

        if not isinstance(accepted, AcceptedProductTaskInputV2):
            raise TypeError("accepted must be AcceptedProductTaskInputV2")
        task_id = accepted.request.task_id
        fingerprint = self._fingerprint(accepted)

        with self._lock:
            cached = self._flows.get(task_id)
            if cached is not None:
                cached_fingerprint, cached_flow = cached
                if cached_fingerprint != fingerprint:
                    raise ValueError(
                        "CROSS_HOST_PRODUCT_FLOW_INPUT_CONFLICT: "
                        "task already owns a different immutable accepted input"
                    )
                return cached_flow

            flow = self._flow_factory(accepted)
            if not callable(getattr(flow, "start_accepted", None)):
                raise TypeError("flow_factory must return a V2 start_accepted facade")
            if not callable(getattr(flow, "resume", None)):
                raise TypeError("flow_factory must return a V2 resume facade")
            self._flows[task_id] = (fingerprint, flow)
            return flow


def _canonical_digest(value: object) -> str:
    """对 composition-only projection material 计算稳定 SHA-256。"""

    def thaw(item: object) -> object:
        """把 immutable mapping/tuple 归一成 canonical JSON body。"""

        if item is None or isinstance(item, (str, bool, int, float)):
            return item
        if isinstance(item, Mapping):
            return {
                str(key): thaw(item[key])
                for key in sorted(item, key=lambda current: str(current))
            }
        if isinstance(item, (tuple, list)):
            return [thaw(current) for current in item]
        return str(item)

    return sha256(
        json.dumps(
            thaw(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _claim_body(claim: SemanticClaim) -> dict[str, object]:
    """投影 SemanticService public claim fields，供 projection identity 哈希使用。"""

    return {
        "subject": claim.subject,
        "predicate": claim.predicate,
        "canonical_term_id": claim.canonical_term_id,
        "value": claim.value,
        "unit": claim.unit,
        "assurance": claim.assurance,
        "provenance": claim.provenance,
        "evidence": claim.evidence,
        "provider_id": claim.provider_id,
        "provider_version": claim.provider_version,
    }


class _AutoCadPlanningSemanticReconstruction:
    """用 exact AutoCAD facts + pinned SemanticService 构造独立 planning result。"""

    def __init__(self, *, fact_reader, semantic_service, semantic_environment) -> None:
        """保存只读 seams；构造阶段不访问 Host。"""

        self._fact_reader = fact_reader
        self._semantic_service = semantic_service
        self._semantic_environment = semantic_environment

    def reconstruct(
        self,
        *,
        task_id: str,
        contract,
        observation,
        semantic_environment_ref: SemanticEnvironmentRef,
    ) -> ReconstructionResult:
        """读取 exact revision，投影语义并发布满足该 operation contract 的 guarantees。"""

        del task_id
        if (
            semantic_environment_ref.environment_id
            != self._semantic_environment.environment_id
            or semantic_environment_ref.content_hash
            != self._semantic_environment.content_hash
        ):
            raise ValueError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID: semantic environment mismatch"
            )
        facts = self._fact_reader.read(
            host_instance_id=observation.host_instance_id,
            document_id=observation.document_id,
            native_id=observation.native_target_id,
            expected_revision=observation.host_revision,
        )
        claims = self._semantic_service.project_facts(
            facts,
            semantic_environment_ref.environment_id,
        )
        fact_body = facts.to_dict()
        claim_body = [_claim_body(item) for item in claims]
        fact_hash = _canonical_digest(fact_body)
        projection_hash = _canonical_digest(
            {
                "facts": fact_body,
                "claims": claim_body,
                "semantic_environment": semantic_environment_ref.payload(),
            }
        )
        mapping_hash = _canonical_digest(
            tuple(
                sorted(
                    (
                        item.provider_id or "",
                        item.provider_version or "",
                        item.predicate or "",
                        item.canonical_term_id or "",
                    )
                    for item in claims
                )
            )
        )
        return ReconstructionResult(
            document_ref=observation.document_id,
            host_revision=str(observation.host_revision),
            coverage=contract.coverage,
            guarantees=tuple(
                AspectGuarantee(
                    item.aspect,
                    coverage_state=CoverageState.RESOLVED,
                    semantic_depth=SemanticDepth.NORMALIZED,
                    assurance_level=AssuranceLevel.NATIVE_ASSERTED,
                )
                for item in contract.requirements
            ),
            projection_ref=SemanticProjectionRef(
                projection_id=f"autocad-projection:{projection_hash[:24]}",
                projection_hash=projection_hash,
                semantic_model_version="dsp.semantic.projection-facts.v1",
                provider_set_hash=semantic_environment_ref.content_hash,
                mapping_profile_set_hash=mapping_hash,
                normalized_fact_batch_hash=fact_hash,
            ),
            semantic_environment_ref=semantic_environment_ref,
        )


class _RevitPlanningSemanticReconstruction:
    """把 Cross-Host planning call 适配到既有 Revit semantic owner。"""

    def __init__(self, boundary: RevitWallThicknessSemanticBoundary) -> None:
        self._boundary = boundary

    def reconstruct(
        self,
        *,
        task_id: str,
        contract,
        observation,
        semantic_environment_ref: SemanticEnvironmentRef,
    ) -> ReconstructionResult:
        """按 fresh observation revision 委托真实 Revit reconstruction。"""

        del task_id
        result = self._boundary.reconstruct(contract, str(observation.host_revision))
        if result.semantic_environment_ref != semantic_environment_ref:
            raise ValueError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID: Revit environment mismatch"
            )
        return result


class _CrossHostMaterializationRouting:
    """把 frozen topology slots 路由到 accepted binding 的 exact runtimes。"""

    def __init__(
        self,
        topology: MaterializationTopologySnapshot,
        runtimes: tuple[HostRuntimeRef, HostRuntimeRef],
    ) -> None:
        self._topology = topology
        self._by_host = {item.host_type: item for item in runtimes}

    def routing_evidence(
        self,
        materialization_plan: object,
        topology_snapshot: object,
    ) -> MaterializationRoutingEvidence:
        """按 materialization required-host identity 生成 exact runtime route。"""

        if topology_snapshot != self._topology:
            raise ValueError(
                "CROSS_HOST_RUNTIME_SET_INVALID: topology differs from reference composition"
            )
        slots = {item.materialization_slot_id: item for item in topology_snapshot.slots}
        routes = []
        for intent in materialization_plan.intents:
            runtime = self._by_host.get(intent.required_host_type)
            if runtime is None:
                raise ValueError(
                    "PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED: required Host unavailable"
                )
            slot = slots[intent.materialization_slot_id]
            if runtime.document_ref != slot.document_ref:
                raise ValueError(
                    "PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED: runtime/document mismatch"
                )
            routes.append(
                MaterializationRuntimeRoute(
                    materialization_id=intent.materialization_id,
                    host_runtime_ref=runtime,
                )
            )
        values = tuple(routes)
        return MaterializationRoutingEvidence(
            routing_snapshot_id=f"MRS-CROSS-HOST-{_canonical_digest([x.materialization_id for x in values])[:24]}",
            routes=values,
            routing_snapshot_hash=compute_materialization_routing_hash(values),
        )


def _identity_registry(binding: _AcceptedBinding) -> IdentityRegistry:
    """注册 accepted Revit anchor identity，不从当前 Host reverse-resolve semantic id。"""

    registry = IdentityRegistry()
    registry.ensure_identity(binding.semantic_target_id)
    revit = binding.member("REVIT")
    registry.bind_host(
        HostBinding(
            semantic_id=binding.semantic_target_id,
            host_type="revit",
            document_id=revit.document_id,
            native_id=revit.native_target_id,
            native_kind="Wall",
        )
    )
    return registry


def _provider_snapshot_factory(binding: _AcceptedBinding):
    """构造 provider snapshot 基体；两个 Host 的 expected revision 由既有 boundary 注入。"""

    by_host = {
        "autocad": binding.member("AUTOCAD"),
        "revit": binding.member("REVIT"),
    }

    def build(execution_slice) -> ProviderExecutionSnapshotV2:
        """从 accepted member + exact Slice 生成 provider candidate/material。"""

        runtime = execution_slice.host_runtime_ref
        member = by_host.get(runtime.host_type)
        if member is None or (
            runtime.host_instance_id != member.host_instance_id
            or runtime.document_ref != member.document_id
        ):
            raise ValueError(
                "PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED: provider Slice runtime mismatch"
            )
        native_kind = "LWPOLYLINE" if runtime.host_type == "autocad" else "Wall"
        target_draft = NativeTargetBindingEvidence(
            semantic_id=execution_slice.execution_units[0].targets[0],
            host_type=runtime.host_type,
            document_ref=runtime.document_ref,
            native_id=member.native_target_id,
            native_kind=native_kind,
            host_binding_fingerprint="0" * 64,
        )
        target = replace(
            target_draft,
            host_binding_fingerprint=compute_host_binding_fingerprint(target_draft),
        )
        unit = execution_slice.execution_units[0]
        candidate_draft = ProviderExecutionCandidate(
            provider_server=f"provider.{runtime.host_type}.wall",
            provider_tool=(
                "set_wall_thickness"
                if runtime.host_type == "autocad"
                else "revit.set_wall_thickness"
            ),
            provider_version="1.0.0",
            canonical_operation=unit.canonical_operation,
            compatible_operation_versions=(unit.canonical_operation_version,),
            input_adapter_version="1.0.0",
            provider_native_constraints=(
                NativeConstraint(
                    "native_kind",
                    NativeConstraintOperator.EQ,
                    (native_kind,),
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
            native_binding_metadata={
                "identity_source": "cross-host-reference-composition",
            },
        )
        draft = ProviderExecutionSnapshotV2(
            snapshot_id=f"PESV2-{sha256(execution_slice.execution_slice_hash.encode()).hexdigest()[:24]}",
            materialization_id=execution_slice.materialization_id,
            materialization_plan_hash=execution_slice.materialization_plan_hash,
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            host_runtime_ref=runtime,
            native_target_bindings=(target,),
            provider_candidates=(candidate,),
            candidate_binding_materials={candidate.candidate_fingerprint: material},
            valid_until="2099-01-01T00:00:00Z",
            snapshot_hash="0" * 64,
        )
        return replace(draft, snapshot_hash=compute_provider_snapshot_hash_v2(draft))

    return build


class _ProviderSnapshotRouter:
    """按 exact Slice host 选择现有 AutoCAD/Revit provider snapshot boundary。"""

    def __init__(self, autocad: object, revit: object) -> None:
        self._values = {"autocad": autocad, "revit": revit}

    def __call__(self, execution_slice):
        boundary = self._values.get(execution_slice.host_runtime_ref.host_type)
        if boundary is None:
            raise ValueError(
                "PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED: provider boundary missing"
            )
        return boundary(execution_slice)


@dataclass(slots=True)
class CrossHostProductReferenceRuntime:
    """MCP server 直接注入 Front Door 的 shared durable/runtime handles。"""

    query_service: ProductTaskQueryService
    request_store: object
    proposal_decision_store: PostgresProposalDecisionStore
    decision_consume_gate: PostgresProductTaskResumeConsumeGate
    artifact_store: object
    observation_reader: CrossHostWallThicknessObservationReader
    flow_resolver: CrossHostProductFlowResolver
    _closeables: tuple[object, ...] = field(repr=False)

    def close(self) -> None:
        """按逆序关闭 reference runtime 独占的 durable resources。"""

        _close_many(self._closeables)


def build_cross_host_product_reference_runtime(
    *,
    dsn: str,
    topology_snapshot: MaterializationTopologySnapshot,
    autocad_dispatcher_factory,
    revit_transport_factory,
    approval_admission_factory: object,
) -> CrossHostProductReferenceRuntime:
    """组合 Cross-Host V2 workflow；构建阶段只装配 seams，不访问 Host。"""

    build_admission = getattr(approval_admission_factory, "build", None)
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("dsn must be a non-blank string")
    if not isinstance(topology_snapshot, MaterializationTopologySnapshot):
        raise TypeError("topology_snapshot must be MaterializationTopologySnapshot")
    if not callable(autocad_dispatcher_factory) or not callable(revit_transport_factory):
        raise TypeError("Host factories must be callable")
    if not callable(build_admission):
        raise TypeError("approval_admission_factory must provide build")

    dsn = dsn.strip()
    migration_connection = connect_postgres(dsn)
    try:
        apply_execution_saga_migrations(migration_connection)
    finally:
        migration_connection.close()

    closeables = []
    try:
        request_store = create_postgres_product_task_request_store(dsn)
        start_gate = PostgresProductTaskStartGate(dsn)
        consume_gate = PostgresProductTaskResumeConsumeGate(dsn)
        artifact_store = create_postgres_artifact_store(dsn)
        checkpointer = create_postgres_checkpointer(dsn)
        saga_store = PostgresExecutionSagaStoreV2(dsn)
        dispatch_store = PostgresHostDispatchIntentStore(dsn)
        evidence_store = PostgresReconciliationEvidenceStore(dsn)
        decisions = PostgresProposalDecisionStore(dsn)
        closeables.extend(
            (
                request_store,
                start_gate,
                consume_gate,
                artifact_store,
                checkpointer,
                saga_store,
                dispatch_store,
                evidence_store,
                decisions,
            )
        )

        observation_reader = CrossHostWallThicknessObservationReader(
            autocad_dispatcher_factory=autocad_dispatcher_factory,
            revit_transport_factory=revit_transport_factory,
        )
        query = ProductTaskQueryService(
            request_store=request_store,
            checkpoint_reader=LangGraphWorkflowCheckpointReader(
                checkpointer=checkpointer
            ),
            saga_store=saga_store,
            proposal_decision_reader=decisions,
            dispatch_intent_reader=dispatch_store,
            evidence_reader=evidence_store,
        )

        def flow_factory(accepted: AcceptedProductTaskInputV2):
            """从 server-owned accepted input 惰性构造 exact workflow facade。"""

            binding = _binding_from_accepted(accepted)
            if (
                binding.topology_environment_id
                != topology_snapshot.topology_environment_id
                or binding.topology_revision != topology_snapshot.topology_revision
                or binding.topology_snapshot_hash
                != topology_snapshot.topology_snapshot_hash
            ):
                raise ValueError(
                    "CROSS_HOST_RUNTIME_SET_INVALID: accepted topology differs from runtime"
                )

            auto = binding.member("AUTOCAD")
            revit = binding.member("REVIT")
            auto_runtime = HostRuntimeRef(
                "autocad", auto.host_instance_id, auto.document_id
            )
            revit_runtime = HostRuntimeRef(
                "revit", revit.host_instance_id, revit.document_id
            )
            dispatcher = autocad_dispatcher_factory(auto.transport_locator)
            transport = revit_transport_factory(revit.transport_locator)
            if dispatcher is None or transport is None:
                raise ValueError(
                    "PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED: exact Host locator unresolved"
                )

            semantic_service, environment = _semantic_environment()
            if (
                environment.environment_id != binding.semantic_environment_id
                or environment.content_hash != binding.semantic_environment_hash
            ):
                raise ValueError(
                    "CROSS_HOST_PLANNING_LINEAGE_INVALID: accepted semantic environment mismatch"
                )

            snapshots = InMemorySnapshotRegistry()
            revit_snapshot = RevitWallThicknessSnapshotReadPort(transport)
            semantic_boundary = RevitWallThicknessSemanticBoundary(
                request_store=request_store,
                context_reader=RevitContextReadPort(transport),
                identity_registry=_identity_registry(binding),
                session_ref=binding.session_ref,
                document_id=revit.document_id,
                host_instance_id=revit.host_instance_id,
                snapshot_reader=revit_snapshot,
                design_fact_adapter=RevitDesignFactAdapter(),
                semantic_service=semantic_service,
                semantic_environment=environment,
                snapshot_registry=snapshots,
                capability_profiles=(_ReferenceWallCapabilityProfile(),),
            )

            from autocad_sidecar.execution.wall_thickness_read import (
                AutoCadWallThicknessFactReadPort,
            )

            auto_fact_reader = AutoCadWallThicknessFactReadPort(dispatcher)
            planning = build_cross_host_planning_composition(
                (
                    (
                        auto_runtime,
                        CrossHostPlanningRuntimePort(
                            binding=binding,
                            member=auto,
                            observation_reader=observation_reader,
                            semantic_reconstruction=_AutoCadPlanningSemanticReconstruction(
                                fact_reader=auto_fact_reader,
                                semantic_service=semantic_service,
                                semantic_environment=environment,
                            ),
                        ),
                    ),
                    (
                        revit_runtime,
                        CrossHostPlanningRuntimePort(
                            binding=binding,
                            member=revit,
                            observation_reader=observation_reader,
                            semantic_reconstruction=_RevitPlanningSemanticReconstruction(
                                semantic_boundary
                            ),
                        ),
                    ),
                )
            )
            freshness = FreshnessResolver(DirtyMap())
            cross_host_freshness = CrossHostOperationFreshnessBoundary(
                snapshot_registry=snapshots,
                freshness_resolver=freshness,
                workflow_artifact_store=artifact_store,
                host_revision_observation=planning.revision_observation,
                member_reconstruction=planning.member_reconstruction,
                proposal_decisions=ProposalDecisionContinuationAdapter(decisions),
            )

            impact_store = InMemoryImpactAnalysisStore()
            scope_store = InMemoryApprovalScopeStore()
            changesets = InMemoryChangeSetStore()
            materializations = InMemoryMaterializationPlanStore()
            execution_plans = InMemoryExecutionPlanV2Store()
            gateway_store = InMemoryGatewayAuthorizationStoreV2()
            gateway = GatewayAuthorizationServiceV2(gateway_store)
            provider_store = InMemoryProviderBindingSetV2Store()
            convergence = CrossHostConvergenceVerifier()
            reconciliation = ExecutionReconciliationServiceV2(
                store=saga_store,
                evidence_store=evidence_store,
            )
            execution_clock = _UtcExecutionClock()

            auto_binding = build_autocad_wall_thickness_runtime_binding(
                auto_runtime,
                dispatcher,
                clock=execution_clock.now,
            )
            revit_binding = CrossHostRuntimePortBinding(
                runtime_ref=revit_runtime,
                readiness_port=RevitWallThicknessReadinessPort(transport),
                execution_port=RevitWallThicknessExecutionPort(
                    transport,
                    clock=execution_clock.now,
                ),
            )
            runtime_registries = build_cross_host_runtime_registries(
                (auto_binding, revit_binding)
            )
            evidence_router = CrossHostVerificationEvidenceRouter(
                (
                    (
                        auto_runtime,
                        AutoCadWallThicknessVerificationEvidencePort(
                            fact_reader=auto_fact_reader,
                            semantic_service=semantic_service,
                            semantic_environment=environment,
                        ),
                    ),
                    (
                        revit_runtime,
                        RevitWallThicknessVerificationEvidencePort(
                            snapshot_reader=revit_snapshot,
                            design_fact_adapter=RevitDesignFactAdapter(),
                            semantic_service=semantic_service,
                            semantic_environment=environment,
                        ),
                    ),
                )
            )
            coordinator = MaterializedExecutionSagaCoordinator(
                readiness_barrier=CrossHostReadinessBarrier(
                    runtime_registries.readiness
                ),
                reconciliation=reconciliation,
                host_registry=runtime_registries.execution,
                dispatch_intents=dispatch_store,
                evidence_port=evidence_router,
                convergence_verifier=convergence,
                clock=execution_clock,
            )

            topology_registry = MaterializationTopologyRegistry()
            topology_registry.register(topology_snapshot)
            base_provider_snapshot = _provider_snapshot_factory(binding)
            provider_snapshot = _ProviderSnapshotRouter(
                AutoCadWallThicknessProviderExecutionSnapshotBoundary(
                    changeset_store=changesets,
                    snapshot_registry=snapshots,
                    provider_snapshot_factory=base_provider_snapshot,
                ),
                RevitWallThicknessProviderExecutionSnapshotBoundary(
                    changeset_store=changesets,
                    snapshot_registry=snapshots,
                    provider_snapshot_factory=base_provider_snapshot,
                ),
            )
            proposal_builder = CrossHostOperationProposalBuilder(
                accepted_input_reader=request_store,
                workflow_artifact_store=artifact_store,
                observation_reader=observation_reader,
            )
            admission = build_admission(
                changeset_store=changesets,
                approval_scope_store=scope_store,
                accepted_input_reader=request_store,
            )
            owners = CrossHostCanonicalWorkflowOwnerPorts(
                snapshot_registry=snapshots,
                freshness_resolver=freshness,
                workflow_artifact_store=artifact_store,
                host_revision_observation=planning.revision_observation,
                canonical_operations=MVP_CANONICAL_OPERATIONS,
                impact_analyzer=ImpactAnalyzer(),
                impact_store=impact_store,
                approval_scope_planner=ApprovalScopePlanner(),
                approval_scope_store=scope_store,
                changeset_builder=ChangeSetBuilder(),
                changeset_store=changesets,
                materialization_planner=MaterializationPlanner(),
                materialization_plan_store=materializations,
                topology_registry=topology_registry,
                topology_environment_id=topology_snapshot.topology_environment_id,
                topology_revision=topology_snapshot.topology_revision,
                execution_plan_store=execution_plans,
                revision_barrier=RevisionBarrier(planning.revision_observation),
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
                approval_admission=admission,
                materialization_routing=_CrossHostMaterializationRouting(
                    topology_snapshot,
                    (auto_runtime, revit_runtime),
                ),
                provider_execution_snapshot=provider_snapshot,
                cross_host_operation_freshness=cross_host_freshness,
                cross_host_proposal_builder=proposal_builder,
            )
            services = DefaultWorkflowServices(
                operation_resolver=OperationResolver((SET_WALL_THICKNESS_V1,)),
                parameter_binder=ParameterBinder(
                    MVP_CANONICAL_OPERATIONS,
                    MVP_BINDING_RECIPES,
                ),
                artifact_store=artifact_store,
                external_owners=owners,
            )
            return CrossHostProductFlow(
                workflow_runtime=LangGraphWorkflowRuntime(
                    services=services,
                    checkpointer=checkpointer,
                ),
                start_gate=start_gate,
            )

        resolver = CrossHostProductFlowResolver(flow_factory)
        return CrossHostProductReferenceRuntime(
            query_service=query,
            request_store=request_store,
            proposal_decision_store=decisions,
            decision_consume_gate=consume_gate,
            artifact_store=artifact_store,
            observation_reader=observation_reader,
            flow_resolver=resolver,
            _closeables=tuple(closeables),
        )
    except Exception:
        _close_many(tuple(closeables))
        raise


__all__ = [
    "CrossHostCanonicalWorkflowOwnerPorts",
    "CrossHostOperationProposalBuilder",
    "CrossHostProductFlowResolver",
    "CrossHostProductReferenceRuntime",
    "build_cross_host_product_reference_runtime",
]
