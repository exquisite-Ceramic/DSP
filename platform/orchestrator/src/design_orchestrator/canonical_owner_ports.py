"""Real-owner workflow 的 production/reference composition skeleton。

本模块实现现有 ``ExternalOwnerPorts`` structural seam，但 Task 4 只建立 composition
形状与最窄的 environment/presentation 委托。Impact、ChangeSet、Gateway、Execution
Planning、Provider Binding、Saga 与 Reconciliation 的真实业务调用分别留给后续任务。

这里不得复制 authoritative owner 的领域规则，也不得通过通用 service locator 隐藏依赖。
所有未来需要的 owner/service/store 都以显式 keyword-only constructor dependency 固定下来。
"""

from __future__ import annotations

from typing import Protocol

from design_orchestrator.default_workflow_services import (
    OperationResolutionInputs,
    ParameterBindingInputs,
)
from design_orchestrator.workflow_contracts import AsyncOperationRef, StableRef
from design_orchestrator.workflow_services import ExecutionOwnerView


class SemanticReconstructionPort(Protocol):
    """Host/context reconstruction 的窄环境边界。"""

    def resolve_host_context(self, task_id: str) -> StableRef: ...


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
    """Task 4 skeleton 对尚未接入的 authoritative owner 调用统一 fail closed。"""

    code = "CANONICAL_OWNER_PORT_NOT_WIRED"

    def __init__(self, method_name: str) -> None:
        self.method_name = method_name
        super().__init__(
            f"canonical workflow owner port is not wired in Task 4 skeleton: {method_name}"
        )


class CanonicalWorkflowOwnerPorts:
    """现有 ``ExternalOwnerPorts`` 的真实 owner composition adapter skeleton。

    Constructor 故意完整列出 owner dependencies。Task 4 不调用尚未冻结 wiring 的领域服务；
    保存这些依赖只是先冻结 production/reference composition shape，后续 Task 6-8 再逐段接通。
    """

    __slots__ = (
        "_snapshot_registry",
        "_impact_analyzer",
        "_impact_store",
        "_approval_scope_planner",
        "_approval_scope_store",
        "_changeset_builder",
        "_changeset_store",
        "_materialization_planner",
        "_materialization_plan_store",
        "_topology_registry",
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
        impact_analyzer: object,
        impact_store: object,
        approval_scope_planner: object,
        approval_scope_store: object,
        changeset_builder: object,
        changeset_store: object,
        materialization_planner: object,
        materialization_plan_store: object,
        topology_registry: object,
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
        # Task 4 不做 service discovery；每个依赖都保留独立字段，后续 wiring 可逐项审计。
        self._snapshot_registry = snapshot_registry
        self._impact_analyzer = impact_analyzer
        self._impact_store = impact_store
        self._approval_scope_planner = approval_scope_planner
        self._approval_scope_store = approval_scope_store
        self._changeset_builder = changeset_builder
        self._changeset_store = changeset_store
        self._materialization_planner = materialization_planner
        self._materialization_plan_store = materialization_plan_store
        self._topology_registry = topology_registry
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

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs:
        raise self._not_wired("load_operation_resolution_inputs")

    def load_parameter_binding_inputs(
        self,
        operation_space_ref: StableRef,
    ) -> ParameterBindingInputs:
        raise self._not_wired("load_parameter_binding_inputs")

    def resolve_host_context(self, task_id: str) -> StableRef:
        """把 Host/context reconstruction 原样委托给明确的环境端口。"""

        return self._semantic_reconstruction.resolve_host_context(task_id)

    def ensure_context_freshness(
        self,
        snapshot_ref: StableRef,
    ) -> StableRef | AsyncOperationRef:
        raise self._not_wired("ensure_context_freshness")

    def ensure_operation_freshness(
        self,
        operation_ref: StableRef,
    ) -> StableRef | AsyncOperationRef:
        raise self._not_wired("ensure_operation_freshness")

    def analyze_impact(self, operation_ref: StableRef) -> StableRef:
        raise self._not_wired("analyze_impact")

    def build_changeset(self, impact_ref: StableRef) -> StableRef:
        raise self._not_wired("build_changeset")

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
