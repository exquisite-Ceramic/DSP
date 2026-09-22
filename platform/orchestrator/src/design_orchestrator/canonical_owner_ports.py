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
from design_orchestrator.workflow_contracts import AsyncOperationRef, StableRef
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
    ) -> StableRef | AsyncOperationRef: ...


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
        "_snapshot_registry",
        "_freshness_resolver",
        "_workflow_artifact_store",
        "_host_revision_observation",
        "_canonical_operations",
        "_impact_analyzer",
        "_impact_store",
        "_approval_scope_planner",
        "_approval_scope_store",
        "_changeset_builder",
        "_changeset_store",
        "_materialization_planner",
        "_materialization_plan_store",
        "_topology_registry",
        "_topology_environment_id",
        "_topology_revision",
        "_execution_plan_store",
        "_revision_barrier",
        "_gateway_authorization",
        "_provider_binding_store",
        "_saga_store",
        "_execution_coordinator",
        "_reconciliation_service",
        "_convergence_verifier",
        "_semantic_reconstruction",
        "_preview_port",
        "_approval_admission",
        "_materialization_routing",
        "_provider_execution_snapshot",
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
        provider_binding_store: object,
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
        self._provider_binding_store = provider_binding_store
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

        该 helper 只组装 Semantic Runtime public contract，不执行 freshness 决策；因此 adapter
        重建后可以按 contract identity 查询 owner registry，而不依赖 process-local 映射。
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
    ) -> ParameterBindingInputs:
        """把 proposal/context read-model 装配委托给边界，再交给真实 ParameterBinder。"""

        inputs = self._semantic_reconstruction.load_parameter_binding_inputs(
            operation_space_ref
        )
        if not isinstance(inputs, ParameterBindingInputs):
            raise TypeError(
                "load_parameter_binding_inputs must return ParameterBindingInputs"
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
    ) -> StableRef | AsyncOperationRef:
        """用真实 Operation Freshness contract 生成 PlanningSnapshot/SnapshotSet。"""

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
        return operation_ref

    def analyze_impact(self, operation_ref: StableRef) -> StableRef:
        """从 owner-local freshness lineage 解析 refs 后调用真实 ImpactAnalyzer。"""

        from design_impact import (
            ImpactAnalysisRequest,
            IntentBoundary,
            PlanningSnapshotBinding,
            SemanticEnvironmentBinding,
            SnapshotSetBinding,
        )

        bound = self._bound_operation(operation_ref)
        contract, _ = self._operation_freshness_contract(bound)
        planning = self._snapshot_registry.get_snapshot_for_freshness_contract(
            contract.contract_id,
            contract.hash,
        )
        snapshot_set = self._snapshot_registry.get_snapshot_set_for_member(
            planning.snapshot_id
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
        """只收集 approval admission 输入；Gateway 授权规则不在此实现。"""

        return self._approval_admission.request_approval(changeset_ref)

    def plan_execution(
        self,
        changeset_ref: StableRef,
        approval_ref: StableRef,
    ) -> StableRef:
        raise self._not_wired("plan_execution")

    def check_revision_barrier(self, execution_plan_ref: StableRef) -> None:
        raise self._not_wired("check_revision_barrier")

    def bind_providers(self, execution_plan_ref: StableRef) -> StableRef:
        raise self._not_wired("bind_providers")

    def issue_execution_grant(self, execution_plan_ref: StableRef) -> StableRef:
        raise self._not_wired("issue_execution_grant")

    def begin_execution(
        self,
        execution_plan_ref: StableRef,
        grant_ref: StableRef,
    ) -> str | AsyncOperationRef:
        raise self._not_wired("begin_execution")

    def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView:
        raise self._not_wired("get_execution_owner_state")

    def verify_reconcile(self, saga_id: str) -> ExecutionOwnerView:
        raise self._not_wired("verify_reconcile")


__all__ = [
    "ApprovalAdmissionPort",
    "CanonicalOwnerPortNotWiredError",
    "CanonicalWorkflowOwnerPorts",
    "ContextFreshnessInputs",
    "HostRevisionObservationPort",
    "PreviewPort",
    "SemanticReconstructionPort",
]
