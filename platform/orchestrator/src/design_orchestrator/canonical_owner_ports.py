"""Real-owner workflow 的 production/reference composition adapter。

本模块实现现有 ``ExternalOwnerPorts`` structural seam。Task 6 接通真实 Semantic
Runtime freshness、Impact、Approval Scope V2 与 ChangeSet V2；Task 7 之后的 execution
planning/provider/Saga/reconciliation 仍显式 fail closed。

这里允许做 request assembly、StableRef 解析与跨 owner dependency composition，但不得复制
authoritative owner 的领域规则，也不得通过通用 service locator 隐藏依赖。source-only owner
package 仅在方法执行时按需导入，使 adapter 本身保持 import-time 轻量。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from design_orchestrator.default_workflow_services import (
    OperationResolutionInputs,
    ParameterBindingInputs,
)
from design_orchestrator.parameter_binder import BoundOperationProposal
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    OperationFreshnessResult,
    StableRef,
)
from design_orchestrator.workflow_services import ExecutionOwnerView


@dataclass(frozen=True, slots=True)
class ContextFreshnessInputs:
    """Semantic Runtime context freshness 所需的最小环境输入。"""

    task_id: str
    project_id: str
    document_ref: str
    root_entities: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("task_id", "project_id", "document_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")
            object.__setattr__(self, field_name, value.strip())
        roots = tuple(
            item.strip()
            for item in self.root_entities
            if isinstance(item, str) and item.strip()
        )
        if not roots:
            raise ValueError("root_entities requires at least one semantic id")
        if len(set(roots)) != len(roots):
            raise ValueError("root_entities values must be unique")
        object.__setattr__(self, "root_entities", roots)


class SemanticReconstructionPort(Protocol):
    """Semantic/environment 输入的窄边界；领域判断仍归真实 resolver/binder/freshness owner。

    这里允许提供 OperationResolver / ParameterBinder 所需的 snapshot-bound read model，
    但实现不得复制 eligibility、slot binding 或 schema validation 规则。
    """

    def resolve_host_context(self, task_id: str) -> StableRef: ...

    def load_context_inputs(self, context_ref: StableRef) -> ContextFreshnessInputs: ...

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs: ...

    def load_parameter_binding_inputs(
        self,
        operation_space_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> ParameterBindingInputs: ...

    def reconstruct(self, contract: object, expected_host_revision: str) -> object: ...


class HostRevisionObservationPort(Protocol):
    """读取当前 Host document revision 的窄环境边界。"""

    def current_revision(self, document_ref: str) -> str: ...


class PreviewPort(Protocol):
    """Preview presentation boundary；返回值不是第二份 ChangeSet truth。"""

    def preview(self, changeset_ref: StableRef) -> StableRef: ...


class ApprovalAdmissionPort(Protocol):
    """Human/policy admission input；Gateway 仍拥有授权语义。"""

    def request_approval(
        self,
        changeset_ref: StableRef,
    ) -> object | AsyncOperationRef: ...


class CanonicalOwnerPortNotWiredError(RuntimeError):
    """尚未接入的 authoritative owner 调用统一 fail closed。"""

    code = "CANONICAL_OWNER_PORT_NOT_WIRED"

    def __init__(self, method_name: str) -> None:
        self.method_name = method_name
        super().__init__(f"canonical workflow owner port is not wired yet: {method_name}")


class _ReconstructionPending(RuntimeError):
    """把异步 reconstruction wait 从同步 FreshnessResolver callback 中带回 workflow。"""

    def __init__(self, operation_ref: AsyncOperationRef) -> None:
        self.operation_ref = operation_ref
        super().__init__(operation_ref.operation_id)


class CanonicalWorkflowOwnerPorts:
    """现有 ``ExternalOwnerPorts`` 的真实 owner composition adapter。

    Constructor 显式列出 production/reference composition dependencies；对象本身只保存 owner
    service/store 依赖，不保存 transition 正确性所必需的 task/operation/impact 私有 lineage。
    所有可恢复 lineage 必须来自 workflow 显式 StableRef 或 authoritative owner-local store。
    """

    __slots__ = (
        "_approval_admission",
        "_approval_scope_planner",
        "_approval_scope_store",
        "_canonical_operations",
        "_changeset_builder",
        "_changeset_store",
        "_convergence_verifier",
        "_coordination_clock",
        "_dispatch_intent_store",
        "_execution_coordinator",
        "_execution_plan_store",
        "_execution_recovery_projection",
        "_freshness_resolver",
        "_gateway_authorization",
        "_gateway_authorization_store",
        "_host_revision_observation",
        "_impact_analyzer",
        "_impact_store",
        "_materialization_plan_store",
        "_materialization_planner",
        "_materialization_routing",
        "_preview_port",
        "_provider_binding_store",
        "_provider_execution_snapshot",
        "_reconciliation_service",
        "_revision_barrier",
        "_saga_store",
        "_semantic_reconstruction",
        "_snapshot_registry",
        "_topology_environment_id",
        "_topology_registry",
        "_topology_revision",
        "_workflow_artifact_store",
    )

    def __init__(
        self,
        *,
        snapshot_registry: object,
        freshness_resolver: object,
        workflow_artifact_store: object,
        host_revision_observation: HostRevisionObservationPort,
        canonical_operations: object,
        impact_analyzer: object,
        impact_store: object,
        approval_scope_planner: object,
        approval_scope_store: object,
        changeset_builder: object,
        changeset_store: object,
        materialization_planner: object,
        materialization_plan_store: object,
        topology_registry: object,
        topology_environment_id: object,
        topology_revision: object,
        execution_plan_store: object,
        revision_barrier: object,
        gateway_authorization: object,
        gateway_authorization_store: object,
        coordination_clock: object,
        provider_binding_store: object,
        dispatch_intent_store: object,
        execution_recovery_projection: object,
        saga_store: object,
        execution_coordinator: object,
        reconciliation_service: object,
        convergence_verifier: object,
        semantic_reconstruction: SemanticReconstructionPort,
        preview_port: PreviewPort,
        approval_admission: ApprovalAdmissionPort,
        materialization_routing: object,
        provider_execution_snapshot: object,
    ) -> None:
        # 兼容 Task 4 shape tests：constructor 不执行 service discovery 或 eagerly validate fakes。
        self._snapshot_registry = snapshot_registry
        self._freshness_resolver = freshness_resolver
        self._workflow_artifact_store = workflow_artifact_store
        self._host_revision_observation = host_revision_observation
        self._canonical_operations = canonical_operations
        self._impact_analyzer = impact_analyzer
        self._impact_store = impact_store
        self._approval_scope_planner = approval_scope_planner
        self._approval_scope_store = approval_scope_store
        self._changeset_builder = changeset_builder
        self._changeset_store = changeset_store
        self._materialization_planner = materialization_planner
        self._materialization_plan_store = materialization_plan_store
        self._topology_registry = topology_registry
        self._topology_environment_id = topology_environment_id
        self._topology_revision = topology_revision
        self._execution_plan_store = execution_plan_store
        self._revision_barrier = revision_barrier
        self._gateway_authorization = gateway_authorization
        self._gateway_authorization_store = gateway_authorization_store
        self._coordination_clock = coordination_clock
        self._provider_binding_store = provider_binding_store
        self._dispatch_intent_store = dispatch_intent_store
        self._execution_recovery_projection = execution_recovery_projection
        self._saga_store = saga_store
        self._execution_coordinator = execution_coordinator
        self._reconciliation_service = reconciliation_service
        self._convergence_verifier = convergence_verifier
        self._semantic_reconstruction = semantic_reconstruction
        self._preview_port = preview_port
        self._approval_admission = approval_admission
        self._materialization_routing = materialization_routing
        self._provider_execution_snapshot = provider_execution_snapshot

    @staticmethod
    def _not_wired(method_name: str) -> CanonicalOwnerPortNotWiredError:
        """未接线的领域调用必须显式失败，禁止生成伪 owner truth。"""

        return CanonicalOwnerPortNotWiredError(method_name)

    @staticmethod
    def _ref_hash_matches(ref: StableRef, actual_hash: str, *, kind: str) -> None:
        """StableRef 带 hash 时必须与 owner artifact 精确一致。"""

        if ref.content_hash is not None and ref.content_hash != actual_hash:
            raise ValueError(f"{kind} StableRef hash does not match authoritative owner content")

    @staticmethod
    def _require_exact_ref_hash(
        ref: StableRef,
        actual_hash: str,
        *,
        kind: str,
    ) -> None:
        """Task 6 exact-lineage ref 必须携带并匹配 authoritative content hash。"""

        if ref.content_hash is None:
            raise ValueError(f"{kind} StableRef requires content_hash")
        CanonicalWorkflowOwnerPorts._ref_hash_matches(
            ref,
            actual_hash,
            kind=kind,
        )

    def _coordination_timestamp(self) -> str:
        """把共享 CoordinationClock 的 UTC 时间投影为 owner request 时间戳。"""

        current = self._coordination_clock.now()
        value = current.isoformat()
        if value.endswith("+00:00"):
            return f"{value[:-6]}Z"
        return value

    def _canonical_definition(self, canonical_operation: str, version: str):
        """按 exact operation/version 解析 platform-owned canonical definition。"""

        for definition in self._canonical_operations:
            if (
                definition.canonical_operation == canonical_operation
                and definition.version == version
            ):
                return definition
        raise ValueError(
            "canonical operation definition is unresolved: "
            f"{canonical_operation}@{version}"
        )

    def _resolve_freshness(self, contract: object, *, expected_host_revision: str):
        """始终经过真实 FreshnessResolver；异步 IO 只把 wait ref 带回 workflow。"""

        def reconstruct(owner_contract: object, expected_revision: str):
            result = self._semantic_reconstruction.reconstruct(
                owner_contract,
                expected_revision,
            )
            if isinstance(result, AsyncOperationRef):
                raise _ReconstructionPending(result)
            return result

        try:
            return self._freshness_resolver.resolve(
                contract,
                expected_host_revision=expected_host_revision,
                reconstruct=reconstruct,
            )
        except _ReconstructionPending as pending:
            return pending.operation_ref

    def _bound_operation(self, operation_ref: StableRef) -> BoundOperationProposal:
        """从 workflow-local artifact store 解析 Orchestrator-owned bound proposal。"""

        value = self._workflow_artifact_store.get(operation_ref)
        if not isinstance(value, BoundOperationProposal):
            raise TypeError("workflow operation ref must resolve to BoundOperationProposal")
        return value

    @staticmethod
    def _bound_targets(bound: BoundOperationProposal) -> tuple[str, ...]:
        """读取 binder 已冻结的 canonical targets，不重新解释 intent。"""

        raw_targets = bound.arguments.get("targets")
        if not isinstance(raw_targets, (tuple, list)):
            raise ValueError("bound operation requires canonical targets")
        targets = tuple(str(item).strip() for item in raw_targets if str(item).strip())
        if not targets:
            raise ValueError("bound operation requires at least one canonical target")
        return targets

    def _operation_freshness_contract(self, bound: BoundOperationProposal):
        """由 bound operation + authoritative ContextSnapshot 重建相同 owner contract identity。

        该 helper 只组装 Semantic Runtime public contract，不执行 freshness 决策；它只用于
        校验 exact PlanningSnapshot 的 contract lineage，不再承担 owner registry reverse lookup。
        """

        from semantic_runtime import build_operation_contract, requirements_from_mappings

        context_snapshot = self._snapshot_registry.get_snapshot(
            bound.context_snapshot_ref.context_snapshot_id
        )
        if bound.context_snapshot_ref.context_snapshot_hash != context_snapshot.hash:
            raise ValueError(
                "bound operation context snapshot hash does not match Semantic Runtime truth"
            )
        requirement_mappings = (
            *bound.planning_requirements.operation_freshness_requirements,
            *bound.planning_requirements.coverage_requirements,
            *bound.planning_requirements.assurance_requirements,
        )
        contract = build_operation_contract(
            project_id=context_snapshot.project_id,
            document_ref=bound.context_snapshot_ref.document_ref,
            canonical_operation=bound.operation.canonical_operation,
            targets=self._bound_targets(bound),
            arguments=dict(bound.arguments),
            requirements=requirements_from_mappings(requirement_mappings),
        )
        return contract, context_snapshot

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs:
        """把 snapshot-bound read-model 装配委托给显式环境边界，再交给真实 resolver。"""

        inputs = self._semantic_reconstruction.load_operation_resolution_inputs(snapshot_ref)
        if not isinstance(inputs, OperationResolutionInputs):
            raise TypeError(
                "load_operation_resolution_inputs must return OperationResolutionInputs"
            )
        return inputs

    def load_parameter_binding_inputs(
        self,
        operation_space_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> ParameterBindingInputs:
        """显式转发 operation-space 与 exact ContextSnapshot refs，再交给真实 ParameterBinder。"""

        inputs = self._semantic_reconstruction.load_parameter_binding_inputs(
            operation_space_ref,
            context_snapshot_ref,
        )
        if not isinstance(inputs, ParameterBindingInputs):
            raise TypeError(
                "load_parameter_binding_inputs must return ParameterBindingInputs"
            )
        authoritative_hash = context_snapshot_ref.content_hash
        if authoritative_hash is None:
            raise ValueError("ContextSnapshot StableRef requires content_hash")
        if (
            inputs.context.context_snapshot_id != context_snapshot_ref.ref_id
            or inputs.context.context_snapshot_hash != authoritative_hash
        ):
            raise ValueError(
                "ParameterBindingContext lineage does not match authoritative "
                "ContextSnapshot ref"
            )
        return inputs

    def resolve_host_context(self, task_id: str) -> StableRef:
        """把 Host/context reconstruction request 原样委托给明确的环境端口。"""

        return self._semantic_reconstruction.resolve_host_context(task_id)

    def ensure_context_freshness(
        self,
        snapshot_ref: StableRef,
    ) -> StableRef | AsyncOperationRef:
        """用真实 Context Freshness contract 生成 authoritative ContextSnapshot。"""

        from semantic_runtime import build_context_contract

        inputs = self._semantic_reconstruction.load_context_inputs(snapshot_ref)
        if not isinstance(inputs, ContextFreshnessInputs):
            raise TypeError("load_context_inputs must return ContextFreshnessInputs")
        contract = build_context_contract(
            inputs.document_ref,
            inputs.root_entities,
            project_id=inputs.project_id,
        )
        expected_revision = self._host_revision_observation.current_revision(
            inputs.document_ref
        )
        resolved = self._resolve_freshness(
            contract,
            expected_host_revision=expected_revision,
        )
        if isinstance(resolved, AsyncOperationRef):
            return resolved

        self._snapshot_registry.put_snapshot(resolved)
        return StableRef(resolved.snapshot_id, resolved.hash)

    def ensure_operation_freshness(
        self,
        operation_ref: StableRef,
    ) -> OperationFreshnessResult | AsyncOperationRef:
        """用真实 Operation Freshness contract 生成并显式返回 exact owner refs。"""

        from semantic_runtime import SnapshotSet

        bound = self._bound_operation(operation_ref)
        contract, _ = self._operation_freshness_contract(bound)
        expected_revision = self._host_revision_observation.current_revision(
            bound.context_snapshot_ref.document_ref
        )
        resolved = self._resolve_freshness(
            contract,
            expected_host_revision=expected_revision,
        )
        if isinstance(resolved, AsyncOperationRef):
            return resolved

        self._snapshot_registry.put_snapshot(resolved)
        snapshot_set = SnapshotSet.create((resolved,))
        self._snapshot_registry.put_snapshot_set(snapshot_set)
        return OperationFreshnessResult(
            operation_ref=operation_ref,
            planning_snapshot_ref=StableRef(resolved.snapshot_id, resolved.hash),
            snapshot_set_ref=StableRef(snapshot_set.snapshot_set_id, snapshot_set.hash),
        )

    def analyze_impact(
        self,
        operation_ref: StableRef,
        planning_snapshot_ref: StableRef,
        snapshot_set_ref: StableRef,
    ) -> StableRef:
        """按 exact owner refs 校验 freshness lineage 后调用真实 ImpactAnalyzer。"""

        from design_impact import (
            ImpactAnalysisRequest,
            IntentBoundary,
            PlanningSnapshotBinding,
            SemanticEnvironmentBinding,
            SnapshotSetBinding,
        )

        bound = self._bound_operation(operation_ref)
        planning = self._snapshot_registry.get_snapshot(planning_snapshot_ref.ref_id)
        snapshot_set = self._snapshot_registry.get_snapshot_set(snapshot_set_ref.ref_id)
        contract, context_snapshot = self._operation_freshness_contract(bound)

        self._require_exact_ref_hash(
            operation_ref,
            workflow_artifact_content_hash(bound),
            kind="BoundOperationProposal",
        )
        self._require_exact_ref_hash(
            planning_snapshot_ref,
            planning.hash,
            kind="PlanningSnapshot",
        )
        self._require_exact_ref_hash(
            snapshot_set_ref,
            snapshot_set.hash,
            kind="SnapshotSet",
        )

        if planning.snapshot_id != planning_snapshot_ref.ref_id:
            raise ValueError(
                "planning snapshot ref does not match authoritative identity"
            )
        if snapshot_set.snapshot_set_id != snapshot_set_ref.ref_id:
            raise ValueError(
                "snapshot-set ref does not match authoritative identity"
            )
        matching_members = [
            member
            for member in snapshot_set.members
            if member.snapshot_id == planning.snapshot_id
            and member.hash == planning.hash
        ]
        if len(matching_members) != 1:
            raise ValueError(
                "snapshot set does not contain the exact planning snapshot"
            )

        if planning.document_ref != contract.coverage.document_ref:
            raise ValueError(
                "planning snapshot document does not match bound operation"
            )
        if planning.project_id != contract.project_id:
            raise ValueError(
                "planning snapshot project does not match bound operation"
            )
        if planning.semantic_environment_ref != snapshot_set.semantic_environment_ref:
            raise ValueError(
                "planning snapshot environment does not match snapshot set"
            )
        if planning.semantic_environment_ref != context_snapshot.semantic_environment_ref:
            raise ValueError(
                "planning snapshot environment does not match bound-operation context"
            )
        if (
            planning.semantic_environment_ref.environment_id
            != bound.semantic_environment_ref
        ):
            raise ValueError(
                "planning snapshot environment does not match bound operation"
            )
        if planning.freshness_contract_id != contract.contract_id:
            raise ValueError(
                "planning snapshot freshness contract does not match bound operation"
            )
        if planning.freshness_contract_hash != contract.hash:
            raise ValueError(
                "planning snapshot freshness contract hash does not match bound operation"
            )

        environment = SemanticEnvironmentBinding(
            planning.semantic_environment_ref.environment_id,
            planning.semantic_environment_ref.content_hash,
        )
        planning_binding = PlanningSnapshotBinding(
            planning.snapshot_id,
            planning.hash,
            planning.document_ref,
            environment,
        )
        snapshot_set_binding = SnapshotSetBinding(
            snapshot_set.snapshot_set_id,
            snapshot_set.hash,
            snapshot_set.member_snapshot_ids,
            environment,
        )

        definition = self._canonical_definition(
            bound.operation.canonical_operation,
            bound.operation.version,
        )
        intent = IntentBoundary(
            direct_targets=self._bound_targets(bound),
            allowed_canonical_effects=tuple(
                getattr(item, "value", str(item)) for item in definition.effects
            ),
            allowed_existence_effects=tuple(
                item.value for item in definition.existence_effects
            ),
        )
        analysis = self._impact_analyzer.analyze(
            ImpactAnalysisRequest(
                bound_operation=bound,
                planning_snapshot_ref=planning_binding,
                snapshot_set_ref=snapshot_set_binding,
                semantic_environment_ref=environment,
                intent_boundary=intent,
            )
        )
        self._impact_store.put(analysis)
        return StableRef(analysis.analysis_id, analysis.analysis_fingerprint)

    @staticmethod
    def _planning_requirement_payload(bound: BoundOperationProposal) -> dict[str, object]:
        """把 binder value contract 投影成 ChangeSet owner 已冻结的 evidence shape。"""

        requirements = bound.planning_requirements
        return {
            "operation_freshness_requirements": (
                requirements.operation_freshness_requirements
            ),
            "coverage_requirements": requirements.coverage_requirements,
            "assurance_requirements": requirements.assurance_requirements,
        }

    @staticmethod
    def _binding_evidence_payload(bound: BoundOperationProposal) -> dict[str, object]:
        """保持 binder evidence 原值；不在 adapter 内重判 slot 来源。"""

        return {
            slot: {
                "binding_class": evidence.binding_class.value,
                "source": evidence.source,
                "source_ref": evidence.source_ref,
            }
            for slot, evidence in bound.binding_evidence.items()
        }

    def build_changeset(
        self,
        task_id: str,
        operation_ref: StableRef,
        impact_ref: StableRef,
    ) -> StableRef:
        """组合真实 Approval Scope V2 与 ChangeSet V2，并持久化 owner truth。

        ``task_id`` 与 ``operation_ref`` 是 workflow 已拥有的显式导航 lineage；不得从内容寻址
        SemanticSnapshot 或 adapter 私有字典反推。Impact/Planning/SnapshotSet body 始终重新从
        authoritative owner stores 解析并校验。
        """

        from design_approval_scope import (
            ApprovalScopePlanRequest,
            CanonicalEffectEvidence,
            DirectEntityEffect,
            ExecutionSliceScopeRule,
            bind_changeset_v2,
            bind_topology_snapshot_v2,
            direct_existing_rule_id,
        )
        from design_changeset import (
            BoundOperationEvidence,
            CanonicalOperationContractEvidence,
            ChangeSetBuildRequest,
            compute_bound_operation_evidence_fingerprint,
            compute_bound_operation_fingerprint,
            compute_contract_definition_fingerprint,
            validate_changeset_integrity_v2,
        )
        from design_impact import IntentBoundary

        normalized_task_id = str(task_id).strip()
        if not normalized_task_id:
            raise ValueError("task_id is required")

        # 必须先解析 authoritative Impact；缺失 ref 时后续 owner 绝不能被调用。
        analysis = self._impact_store.get(impact_ref.ref_id)
        if (
            impact_ref.content_hash is not None
            and impact_ref.content_hash != analysis.analysis_fingerprint
        ):
            raise ValueError(
                "ImpactAnalysis StableRef hash does not match authoritative owner content"
            )

        # operation_ref 由 workflow 显式携带，并用 Impact owner 已冻结的 material fingerprint
        # 校验同一条 lineage；这样重建 adapter 后不需要 ``impact -> operation`` 私有映射。
        bound = self._bound_operation(operation_ref)
        arguments = dict(bound.arguments)
        material_fingerprint = compute_bound_operation_fingerprint(
            bound.operation.canonical_operation,
            bound.operation.version,
            arguments,
        )
        if material_fingerprint != analysis.bound_operation_fingerprint:
            raise ValueError(
                "operation StableRef does not match authoritative ImpactAnalysis lineage"
            )

        planning_binding = analysis.planning_snapshot_ref
        planning_ref = StableRef(
            planning_binding.snapshot_id,
            planning_binding.snapshot_hash,
        )
        planning_snapshot = self._snapshot_registry.get_snapshot(planning_ref.ref_id)
        self._ref_hash_matches(
            planning_ref,
            planning_snapshot.hash,
            kind="PlanningSnapshot",
        )
        snapshot_set_binding = analysis.snapshot_set_ref
        snapshot_set_ref = StableRef(
            snapshot_set_binding.snapshot_set_id,
            snapshot_set_binding.snapshot_set_hash,
        )
        snapshot_set = self._snapshot_registry.get_snapshot_set(snapshot_set_ref.ref_id)
        self._ref_hash_matches(
            snapshot_set_ref,
            snapshot_set.hash,
            kind="SnapshotSet",
        )
        if planning_snapshot.snapshot_id not in snapshot_set.member_snapshot_ids:
            raise ValueError(
                "ImpactAnalysis planning snapshot is outside authoritative SnapshotSet"
            )

        definition = self._canonical_definition(
            bound.operation.canonical_operation,
            bound.operation.version,
        )
        if definition.existence_effects:
            # Task 6 不扩展 CREATE/DELETE product scenarios；不得临时发明 scope recipe。
            raise self._not_wired("build_changeset.existence_effects")

        topology = self._topology_registry.get(
            self._topology_environment_id,
            self._topology_revision,
        )
        targets = self._bound_targets(bound)
        effect_values = tuple(
            getattr(item, "value", str(item)) for item in definition.effects
        )
        intent = IntentBoundary(
            direct_targets=targets,
            allowed_canonical_effects=effect_values,
        )
        rule_ids = tuple(direct_existing_rule_id(target) for target in targets)
        document_refs = tuple(sorted({slot.document_ref for slot in topology.slots}))
        scope_v1 = self._approval_scope_planner.plan(
            ApprovalScopePlanRequest(
                canonical_effect_evidence=CanonicalEffectEvidence(
                    definition.canonical_operation,
                    definition.version,
                    effect_values,
                ),
                impact_analysis=analysis,
                intent_boundary=intent,
                direct_entity_effects=tuple(
                    DirectEntityEffect(target, effect_values) for target in targets
                ),
                execution_slice_scope_rules=tuple(
                    ExecutionSliceScopeRule(
                        f"SLICE-SCOPE-{index}",
                        document_ref,
                        existing_rule_ids=rule_ids,
                    )
                    for index, document_ref in enumerate(document_refs, start=1)
                ),
            )
        )
        scope_v2 = bind_topology_snapshot_v2(
            scope_v1,
            topology.topology_snapshot_hash,
        )

        planning_requirements = self._planning_requirement_payload(bound)
        binding_evidence = self._binding_evidence_payload(bound)
        evidence_fingerprint = compute_bound_operation_evidence_fingerprint(
            canonical_operation=bound.operation.canonical_operation,
            canonical_operation_version=bound.operation.version,
            arguments=arguments,
            context_snapshot_id=bound.context_snapshot_ref.context_snapshot_id,
            context_snapshot_hash=bound.context_snapshot_ref.context_snapshot_hash,
            document_ref=bound.context_snapshot_ref.document_ref,
            semantic_environment_id=bound.semantic_environment_ref,
            planning_requirements=planning_requirements,
            binding_evidence=binding_evidence,
        )
        bound_evidence = BoundOperationEvidence(
            canonical_operation=bound.operation.canonical_operation,
            canonical_operation_version=bound.operation.version,
            arguments=arguments,
            context_snapshot_id=bound.context_snapshot_ref.context_snapshot_id,
            context_snapshot_hash=bound.context_snapshot_ref.context_snapshot_hash,
            document_ref=bound.context_snapshot_ref.document_ref,
            semantic_environment_id=bound.semantic_environment_ref,
            planning_requirements=planning_requirements,
            binding_evidence=binding_evidence,
            bound_operation_fingerprint=material_fingerprint,
            bound_operation_evidence_fingerprint=evidence_fingerprint,
        )

        definition_fingerprint = compute_contract_definition_fingerprint(
            canonical_operation=definition.canonical_operation,
            canonical_operation_version=definition.version,
            argument_schema=definition.input_schema,
            effects=definition.effects,
            verification_contract=definition.verification_contract,
        )
        contract_evidence = CanonicalOperationContractEvidence(
            canonical_operation=definition.canonical_operation,
            canonical_operation_version=definition.version,
            argument_schema=definition.input_schema,
            effects=definition.effects,
            verification_contract=definition.verification_contract,
            definition_fingerprint=definition_fingerprint,
        )

        changeset = self._changeset_builder.build(
            ChangeSetBuildRequest(
                task_id=normalized_task_id,
                project_id=planning_snapshot.project_id,
                bound_operation_evidence=bound_evidence,
                impact_analysis=analysis,
                approval_scope_definition=scope_v2,
                canonical_operation_contracts=(contract_evidence,),
            )
        )
        boundary = bind_changeset_v2(
            scope_v2,
            changeset.changeset_hash,
            f"SCOPE-{changeset.changeset_id}",
        )
        validate_changeset_integrity_v2(changeset, boundary)

        # 只有所有 owner deterministic validators 通过后才发布 immutable reference truth。
        self._approval_scope_store.put_definition(scope_v2)
        self._changeset_store.put(changeset)
        self._approval_scope_store.put_boundary(boundary)
        return StableRef(changeset.changeset_id, changeset.changeset_hash)

    def preview(self, changeset_ref: StableRef) -> StableRef:
        """Preview 只走 presentation boundary，不解释 ChangeSet 内容。"""

        return self._preview_port.preview(changeset_ref)

    def request_approval(
        self,
        changeset_ref: StableRef,
    ) -> StableRef | AsyncOperationRef:
        """收集 human/policy admission，并由真实 Gateway V2 生成 approval truth。"""

        from design_gateway_authorization import ApprovalConsumptionRequestV2

        admission = self._approval_admission.request_approval(changeset_ref)
        if isinstance(admission, AsyncOperationRef):
            return admission

        # ChangeSet 与 final Boundary 都从 authoritative owner-local stores 重新解析；
        # adapter 不接受 admission 内自带的副本作为跨 owner truth。
        changeset = self._changeset_store.get(changeset_ref.ref_id)
        self._ref_hash_matches(
            changeset_ref,
            changeset.changeset_hash,
            kind="CanonicalChangeSet",
        )
        boundary = self._approval_scope_store.get_boundary(
            f"SCOPE-{changeset.changeset_id}"
        )
        approval = self._gateway_authorization.consume_approval(
            ApprovalConsumptionRequestV2(
                admission=admission,
                canonical_changeset=changeset,
                approval_scope_boundary=boundary,
                consumed_at=self._coordination_timestamp(),
            )
        )
        return StableRef(approval.approval_id, approval.approval_hash)

    def plan_execution(
        self,
        changeset_ref: StableRef,
        approval_ref: StableRef,
    ) -> StableRef:
        """组合真实 materialization / execution-planning owners 并发布不可变计划引用。

        本方法只解析 authoritative refs、组装 owner request 与校验跨 owner identity join；
        convergence profile、materialization 规则与 execution planning 规则仍由各自 owner
        的 package-root public API 决定，adapter 不复制任何选择或排序算法。
        """

        from design_convergence import (
            ConvergenceProfileBuildRequest,
            build_convergence_profile,
        )
        from design_execution_planning import (
            ExecutionPlanningRequestV2,
            MaterializationRoutingEvidence,
            plan_materialized_execution,
        )
        from design_materialization_planning import MaterializationPlanningRequest

        changeset = self._changeset_store.get(changeset_ref.ref_id)
        self._ref_hash_matches(
            changeset_ref,
            changeset.changeset_hash,
            kind="CanonicalChangeSet",
        )
        boundary = self._approval_scope_store.get_boundary(
            f"SCOPE-{changeset.changeset_id}"
        )

        # approval_ref 必须解析到 Gateway owner 已消费并持有的真实 approval；这里仅做
        # content identity join，不自行解释 approval lifecycle 或 policy semantics。
        stored_approval = self._gateway_authorization_store.get_approval(
            approval_ref.ref_id
        )
        if stored_approval is None:
            raise ValueError("Gateway approval StableRef is unresolved")
        approval = stored_approval.record
        self._ref_hash_matches(
            approval_ref,
            approval.approval_hash,
            kind="GatewayApproval",
        )
        if approval.changeset_hash != changeset.changeset_hash:
            raise ValueError("Gateway approval does not reference this ChangeSet")
        if approval.approved_scope_hash != boundary.scope_hash:
            raise ValueError("Gateway approval does not reference this approval scope")

        topology = self._topology_registry.get(
            self._topology_environment_id,
            self._topology_revision,
        )
        definition = self._canonical_definition(
            changeset.root_operation.canonical_operation,
            changeset.root_operation.canonical_operation_version,
        )
        convergence_profile = build_convergence_profile(
            ConvergenceProfileBuildRequest(
                canonical_changeset=changeset,
                approval_scope_boundary=boundary,
                canonical_operation_definition=definition,
            )
        )
        materialization_plan = self._materialization_planner.plan(
            MaterializationPlanningRequest(
                canonical_changeset=changeset,
                approval_scope_boundary=boundary,
                topology_snapshot=topology,
                convergence_profile=convergence_profile,
            )
        )
        self._materialization_plan_store.put(materialization_plan)

        # Runtime routing 是明确的环境边界；adapter 只要求它返回 owner public contract，
        # 不在这里选择 Host、排序 route 或推断 provider eligibility。
        routing = self._materialization_routing.routing_evidence(
            materialization_plan,
            topology,
        )
        if not isinstance(routing, MaterializationRoutingEvidence):
            raise TypeError(
                "materialization_routing must return MaterializationRoutingEvidence"
            )
        execution_plan = plan_materialized_execution(
            ExecutionPlanningRequestV2(
                canonical_changeset=changeset,
                approval_scope_boundary=boundary,
                materialization_plan=materialization_plan,
                topology_snapshot=topology,
                runtime_routing_evidence=routing,
            )
        )
        self._execution_plan_store.put(execution_plan)
        return StableRef(
            execution_plan.execution_plan_id,
            execution_plan.execution_plan_hash,
        )

    def check_revision_barrier(self, execution_plan_ref: StableRef) -> None:
        """按计划持有的 ChangeSet lineage 解析 exact SnapshotSet，并交给真实 barrier 校验。"""

        plan_getter = getattr(self._execution_plan_store, "get", None)
        if plan_getter is None:
            raise self._not_wired("check_revision_barrier")
        execution_plan = plan_getter(execution_plan_ref.ref_id)
        self._ref_hash_matches(
            execution_plan_ref,
            execution_plan.execution_plan_hash,
            kind="ExecutionPlanV2",
        )

        # SnapshotSet lineage 来自 authoritative ChangeSet owner；adapter 不维护
        # plan→snapshot-set 私有映射，也不自行比较 Host revision。
        changeset = self._changeset_store.get(execution_plan.changeset_id)
        if changeset.changeset_hash != execution_plan.changeset_hash:
            raise ValueError("ExecutionPlanV2 ChangeSet lineage does not match owner truth")
        snapshot_set_binding = changeset.snapshot_set_ref
        snapshot_set = self._snapshot_registry.get_snapshot_set(
            snapshot_set_binding.snapshot_set_id
        )
        if snapshot_set.hash != snapshot_set_binding.snapshot_set_hash:
            raise ValueError("ChangeSet SnapshotSet lineage does not match owner truth")

        self._revision_barrier.check(snapshot_set)

    def bind_providers(self, execution_plan_ref: StableRef) -> StableRef:
        """把 runtime provider evidence 交给真实 Provider Binding V2 owner 解析。"""

        from design_provider_binding import (
            ProviderExecutionSnapshotV2,
            resolve_provider_bindings_v2,
        )

        plan_getter = getattr(self._execution_plan_store, "get", None)
        if plan_getter is None:
            raise self._not_wired("bind_providers")
        execution_plan = plan_getter(execution_plan_ref.ref_id)
        self._ref_hash_matches(
            execution_plan_ref,
            execution_plan.execution_plan_hash,
            kind="ExecutionPlanV2",
        )

        # 当前 workflow contract 只携带一个 provider_binding_ref，因此本阶段只能对一个
        # exact ExecutionSliceV2 发布一个 BindingSetV2；不得静默挑选多 slice 中的任意一个。
        if len(execution_plan.execution_slices) != 1:
            raise ValueError("provider binding requires exactly one ExecutionSliceV2")
        execution_slice = execution_plan.execution_slices[0]

        snapshot_provider = self._provider_execution_snapshot
        if not callable(snapshot_provider):
            raise self._not_wired("bind_providers")
        snapshot = snapshot_provider(execution_slice)
        if not isinstance(snapshot, ProviderExecutionSnapshotV2):
            raise TypeError(
                "provider_execution_snapshot must return ProviderExecutionSnapshotV2"
            )

        binding_set = resolve_provider_bindings_v2(execution_slice, snapshot)
        self._provider_binding_store.put(binding_set)
        return StableRef(binding_set.binding_set_id, binding_set.binding_set_hash)

    def issue_execution_grant(
        self,
        execution_plan_ref: StableRef,
        approval_ref: StableRef,
        provider_binding_ref: StableRef,
    ) -> StableRef:
        """解析 exact owner refs，交给真实 Gateway V2 签发并 admission execution grant。"""

        from design_gateway_authorization import ExecutionGrantRequestV2

        plan_getter = getattr(self._execution_plan_store, "get", None)
        if plan_getter is None:
            raise self._not_wired("issue_execution_grant")
        execution_plan = plan_getter(execution_plan_ref.ref_id)
        self._ref_hash_matches(
            execution_plan_ref,
            execution_plan.execution_plan_hash,
            kind="ExecutionPlanV2",
        )

        binding_getter = getattr(self._provider_binding_store, "get", None)
        if binding_getter is None:
            raise self._not_wired("issue_execution_grant")
        binding_set = binding_getter(provider_binding_ref.ref_id)
        self._ref_hash_matches(
            provider_binding_ref,
            binding_set.binding_set_hash,
            kind="ProviderBindingSetV2",
        )

        matching_slices = tuple(
            execution_slice
            for execution_slice in execution_plan.execution_slices
            if (
                execution_slice.execution_slice_id == binding_set.execution_slice_id
                and execution_slice.execution_slice_hash == binding_set.execution_slice_hash
                and execution_slice.materialization_id == binding_set.materialization_id
                and execution_slice.materialization_plan_hash
                == binding_set.materialization_plan_hash
            )
        )
        if len(matching_slices) != 1:
            raise ValueError(
                "ProviderBindingSetV2 does not resolve to exactly one ExecutionSliceV2"
            )
        execution_slice = matching_slices[0]

        materialization_plan = self._materialization_plan_store.get(
            execution_plan.materialization_plan_hash
        )
        topology = self._topology_registry.get(
            self._topology_environment_id,
            self._topology_revision,
        )
        boundary = self._approval_scope_store.get_boundary(
            execution_plan.approval_scope_ref.scope_id
        )
        stored_approval = self._gateway_authorization_store.get_approval(
            approval_ref.ref_id
        )
        if stored_approval is None:
            raise ValueError("Gateway approval StableRef is unresolved")
        approval = stored_approval.record
        self._ref_hash_matches(
            approval_ref,
            approval.approval_hash,
            kind="GatewayApproval",
        )

        issued_at = self._coordination_timestamp()
        grant = self._gateway_authorization.issue_execution_grant(
            ExecutionGrantRequestV2(
                approval_id=approval.approval_id,
                execution_plan=execution_plan,
                execution_slice=execution_slice,
                provider_binding_set=binding_set,
                materialization_plan=materialization_plan,
                topology_snapshot=topology,
                approval_scope_boundary=boundary,
                issued_at=issued_at,
            )
        )
        authority = self._gateway_authorization.admit_execution_grant(
            grant.grant_hash,
            issued_at,
        )
        if authority.grant_hash != grant.grant_hash:
            raise ValueError("Gateway admitted authority does not reference issued grant")
        return StableRef(grant.grant_id, grant.grant_hash)

    def begin_execution(
        self,
        execution_plan_ref: StableRef,
        grant_ref: StableRef,
    ) -> str | AsyncOperationRef:
        """解析 exact execution lineage 后把执行交给真实 materialized coordinator。"""

        from design_convergence import (
            ConvergenceProfileBuildRequest,
            build_convergence_profile,
        )

        plan_getter = getattr(self._execution_plan_store, "get", None)
        if plan_getter is None:
            raise self._not_wired("begin_execution")
        execution_plan = plan_getter(execution_plan_ref.ref_id)
        self._require_exact_ref_hash(
            execution_plan_ref,
            execution_plan.execution_plan_hash,
            kind="ExecutionPlanV2",
        )
        if len(execution_plan.execution_slices) != 1:
            raise ValueError("canonical execution requires exactly one ExecutionSliceV2")
        execution_slice = execution_plan.execution_slices[0]

        if grant_ref.content_hash is None:
            raise ValueError("ExecutionGrantV2 StableRef requires content_hash")
        grant_getter = getattr(self._gateway_authorization_store, "get_grant_v2", None)
        if grant_getter is None:
            raise self._not_wired("begin_execution")
        grant = grant_getter(grant_ref.content_hash)
        if grant is None:
            raise ValueError("Gateway execution grant full hash is unresolved")
        if grant.grant_id != grant_ref.ref_id or grant.grant_hash != grant_ref.content_hash:
            raise ValueError("Gateway execution grant StableRef does not match owner truth")
        if (
            grant.changeset_hash != execution_plan.changeset_hash
            or grant.approved_scope_hash != execution_plan.approval_scope_ref.scope_hash
            or grant.materialization_plan_hash != execution_plan.materialization_plan_hash
            or grant.materialization_id != execution_slice.materialization_id
            or grant.execution_slice_id != execution_slice.execution_slice_id
            or grant.execution_slice_hash != execution_slice.execution_slice_hash
            or grant.host_instance_id != execution_slice.host_runtime_ref.host_instance_id
        ):
            raise ValueError("Gateway execution grant does not match exact ExecutionPlanV2 lineage")

        authority = self._gateway_authorization.admit_execution_grant(
            grant.grant_hash,
            self._coordination_timestamp(),
        )
        if (
            authority.grant_hash != grant.grant_hash
            or authority.changeset_hash != grant.changeset_hash
            or authority.approved_scope_hash != grant.approved_scope_hash
            or authority.materialization_plan_hash != grant.materialization_plan_hash
            or authority.materialization_id != grant.materialization_id
            or authority.execution_slice_hash != grant.execution_slice_hash
            or authority.binding_set_hash != grant.binding_set_hash
            or authority.host_instance_id != grant.host_instance_id
        ):
            raise ValueError("Gateway admitted authority does not match exact grant lineage")

        binding_getter = getattr(self._provider_binding_store, "get_by_hash", None)
        if binding_getter is None:
            raise self._not_wired("begin_execution")
        binding_set = binding_getter(authority.binding_set_hash)
        if binding_set is None:
            raise ValueError("Provider binding full hash is unresolved")
        if (
            binding_set.binding_set_hash != authority.binding_set_hash
            or binding_set.materialization_id != execution_slice.materialization_id
            or binding_set.materialization_plan_hash
            != execution_slice.materialization_plan_hash
            or binding_set.execution_slice_id != execution_slice.execution_slice_id
            or binding_set.execution_slice_hash != execution_slice.execution_slice_hash
        ):
            raise ValueError("Provider binding does not match exact admitted Slice lineage")

        changeset = self._changeset_store.get(execution_plan.changeset_id)
        if changeset.changeset_hash != execution_plan.changeset_hash:
            raise ValueError("ExecutionPlanV2 ChangeSet lineage does not match owner truth")
        boundary = self._approval_scope_store.get_boundary(
            execution_plan.approval_scope_ref.scope_id
        )
        if (
            boundary.changeset_hash != changeset.changeset_hash
            or boundary.scope_hash != execution_plan.approval_scope_ref.scope_hash
        ):
            raise ValueError("ExecutionPlanV2 approval scope lineage does not match owner truth")
        materialization_plan = self._materialization_plan_store.get(
            execution_plan.materialization_plan_hash
        )
        if (
            materialization_plan.materialization_plan_hash
            != execution_plan.materialization_plan_hash
            or materialization_plan.changeset_hash != changeset.changeset_hash
            or materialization_plan.approved_scope_hash != boundary.scope_hash
        ):
            raise ValueError("ExecutionPlanV2 materialization lineage does not match owner truth")

        definition = self._canonical_definition(
            changeset.root_operation.canonical_operation,
            changeset.root_operation.canonical_operation_version,
        )
        convergence_profile = build_convergence_profile(
            ConvergenceProfileBuildRequest(
                canonical_changeset=changeset,
                approval_scope_boundary=boundary,
                canonical_operation_definition=definition,
            )
        )
        if (
            convergence_profile.profile_hash
            != materialization_plan.convergence_profile_hash
            or convergence_profile.profile_hash
            != execution_plan.convergence_profile_hash
        ):
            raise ValueError("Convergence profile does not match frozen execution lineage")

        result = self._execution_coordinator.execute(
            changeset,
            boundary,
            materialization_plan,
            execution_plan,
            (binding_set,),
            (authority,),
            convergence_profile,
        )
        status = getattr(result.status, "value", result.status)
        if status == "READINESS_FAILED" or result.saga_id == "NOT_CREATED":
            raise ValueError("execution readiness failed before durable Saga creation")

        stored = self._saga_store.get_saga(result.saga_id)
        if stored is None:
            raise ValueError("execution coordinator returned an unresolved durable Saga")
        if status == "RECOVERY_REQUIRED":
            return AsyncOperationRef(
                kind=AsyncOperationKind.EXECUTION_JOB,
                owner="execution",
                operation_id=result.saga_id,
            )
        return result.saga_id

    def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView:
        """组合 durable Saga 与 dispatch intent 的公开只读 recovery 投影。"""

        from design_orchestrator.workflow_services import (
            ExecutionSagaView,
            HostDispatchRecoveryState,
            HostDispatchRecoveryView,
        )

        stored = self._saga_store.get_saga(saga_id)
        if stored is None:
            raise ValueError("execution Saga is unresolved")
        ordered_slice_hashes = tuple(stored.definition.ordered_slice_hashes)
        if len(ordered_slice_hashes) != 1:
            raise ValueError("canonical execution owner view requires exactly one Saga Slice")
        slice_hash = ordered_slice_hashes[0]

        dispatch_getter = getattr(self._dispatch_intent_store, "get_for_saga_slice", None)
        if dispatch_getter is None:
            raise self._not_wired("get_execution_owner_state")
        dispatch_intent = dispatch_getter(saga_id, slice_hash)
        projection = self._execution_recovery_projection
        if not callable(projection):
            raise self._not_wired("get_execution_owner_state")
        projected = projection(stored, slice_hash, dispatch_intent)
        disposition = getattr(projected, "disposition", None)

        active_recovery = None
        if disposition is not None:
            if dispatch_intent is None:
                raise ValueError(
                    "active execution recovery requires durable dispatch intent identity"
                )
            active_recovery = HostDispatchRecoveryView(
                dispatch_intent_id=str(dispatch_intent.dispatch_intent_id),
                execution_slice_hash=slice_hash,
                state=HostDispatchRecoveryState(
                    getattr(disposition, "value", disposition)
                ),
            )

        saga_status = getattr(stored.status, "value", stored.status)
        return ExecutionOwnerView(
            saga=ExecutionSagaView(
                saga_id=stored.definition.saga_id,
                saga_revision=stored.saga_revision,
                status=str(saga_status),
                active_slice_hash=(slice_hash if active_recovery is not None else None),
            ),
            active_dispatch_recovery=active_recovery,
        )

    def verify_reconcile(self, saga_id: str) -> ExecutionOwnerView:
        """只读取 owner truth；仅 terminal 且无 active recovery 时返回。"""

        from design_orchestrator.workflow_services import classify_execution_resume

        view = self.get_execution_owner_state(saga_id)
        if classify_execution_resume(view) != "TERMINAL":
            raise ValueError("execution owner state is not terminal")
        return view


__all__ = [
    "ApprovalAdmissionPort",
    "CanonicalOwnerPortNotWiredError",
    "CanonicalWorkflowOwnerPorts",
    "ContextFreshnessInputs",
    "HostRevisionObservationPort",
    "PreviewPort",
    "SemanticReconstructionPort",
]
