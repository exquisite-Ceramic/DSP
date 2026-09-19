"""ADR-010 默认 deterministic workflow service adapters。

本模块把既有 ``OperationResolver`` 与 ``ParameterBinder`` 接到 framework-neutral
``WorkflowServices`` 边界。Workflow Orchestrator 只拥有 workflow-local 的确定性中间产物；
已有 authoritative owner 的领域对象继续留在原 owner，通过 ``StableRef`` 或稳定 read model
跨边界访问。这里不得复制 eligibility、slot binding、freshness、Saga 或 Host dispatch
transition 规则。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
from typing import Protocol

from design_orchestrator.operation_resolver import (
    CapabilityProfile,
    OperationResolver,
    ResolutionContext,
    ResolutionResult,
)
from design_orchestrator.parameter_binder import (
    BoundOperationProposal,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)
from design_orchestrator.workflow_contracts import AsyncOperationRef, StableRef
from design_orchestrator.workflow_services import ExecutionOwnerView


@dataclass(frozen=True, slots=True)
class OperationResolutionInputs:
    """OperationResolver 一次调用所需的 owner-provided 只读输入。"""

    profiles: tuple[CapabilityProfile, ...]
    context: ResolutionContext

    def __post_init__(self) -> None:
        profiles = tuple(self.profiles)
        if not isinstance(self.context, ResolutionContext):
            raise TypeError("context must be a ResolutionContext")
        object.__setattr__(self, "profiles", profiles)


@dataclass(frozen=True, slots=True)
class ParameterBindingInputs:
    """ParameterBinder 一次调用所需的 proposal 与 snapshot-bound context。"""

    proposal: OperationProposal
    context: ParameterBindingContext

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, OperationProposal):
            raise TypeError("proposal must be an OperationProposal")
        if not isinstance(self.context, ParameterBindingContext):
            raise TypeError("context must be a ParameterBindingContext")


class WorkflowArtifactStore(Protocol):
    """只保存 workflow-local deterministic intermediate artifacts 的存储边界。"""

    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef: ...

    def get(self, ref: StableRef) -> object: ...


class ExternalOwnerPorts(Protocol):
    """DefaultWorkflowServices 访问其他 authoritative owners 的稳定端口集合。

    resolver/binder 所需事实通过专门 read-model 方法装配；其余 workflow service 调用保持
    原 owner 负责业务规则，本 adapter 只做参数转发，不解释其内部状态机。
    """

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs: ...

    def load_parameter_binding_inputs(
        self,
        operation_space_ref: StableRef,
    ) -> ParameterBindingInputs: ...

    def resolve_host_context(self, task_id: str) -> StableRef: ...

    def ensure_context_freshness(
        self,
        snapshot_ref: StableRef,
    ) -> StableRef | AsyncOperationRef: ...

    def ensure_operation_freshness(
        self,
        operation_ref: StableRef,
    ) -> StableRef | AsyncOperationRef: ...

    def analyze_impact(self, operation_ref: StableRef) -> StableRef: ...

    def build_changeset(self, impact_ref: StableRef) -> StableRef: ...

    def preview(self, changeset_ref: StableRef) -> StableRef: ...

    def request_approval(
        self,
        changeset_ref: StableRef,
    ) -> StableRef | AsyncOperationRef: ...

    def plan_execution(
        self,
        changeset_ref: StableRef,
        approval_ref: StableRef,
    ) -> StableRef: ...

    def check_revision_barrier(self, execution_plan_ref: StableRef) -> None: ...

    def bind_providers(self, execution_plan_ref: StableRef) -> StableRef: ...

    def issue_execution_grant(self, execution_plan_ref: StableRef) -> StableRef: ...

    def begin_execution(
        self,
        execution_plan_ref: StableRef,
        grant_ref: StableRef,
    ) -> str | AsyncOperationRef: ...

    def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView: ...

    def verify_reconcile(self, saga_id: str) -> ExecutionOwnerView: ...


def _normalize_for_hash(value: object) -> object:
    """把 workflow-local artifact 递归投影成确定性的 JSON-compatible 结构。

    这里的 hash 只服务于 Workflow Orchestrator 自己的 artifact 完整性引用，不替代任何
    领域 owner 的 canonical hash。遇到无法稳定序列化的对象时 fail closed，避免把进程地址、
    repr 或其他非确定性信息写进 checkpoint-facing ``StableRef``。
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _normalize_for_hash(value.value)
    if isinstance(value, Mapping):
        normalized_items: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("workflow artifact mappings require string keys")
            normalized_items[key] = _normalize_for_hash(item)
        return {key: normalized_items[key] for key in sorted(normalized_items)}
    if isinstance(value, (tuple, list)):
        return [_normalize_for_hash(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_normalize_for_hash(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _normalize_for_hash(getattr(value, field.name))
            for field in fields(value)
        }

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json")
        except TypeError:
            dumped = model_dump()
        return _normalize_for_hash(dumped)

    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping):
        public_attributes = {
            str(key): item
            for key, item in attributes.items()
            if not str(key).startswith("_")
        }
        if public_attributes:
            return _normalize_for_hash(public_attributes)

    raise TypeError(
        "workflow-local artifact contains a value without deterministic serialization"
    )


def _artifact_content_hash(value: object) -> str:
    """计算 workflow-local artifact 的 lowercase SHA-256 内容摘要。"""

    normalized = _normalize_for_hash(value)
    payload = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


class DefaultWorkflowServices:
    """ADR-010 的默认 service 组合器。

    ``OperationResolver`` 与 ``ParameterBinder`` 是本包已有的确定性模块，因此在这里直接调用；
    其余能力继续由各 authoritative owner 提供。本类只把结果转成 workflow-local artifact ref，
    不把完整 ``ResolutionResult``、``BoundOperationProposal`` 或外部 owner 对象送入 checkpoint。
    """

    def __init__(
        self,
        *,
        operation_resolver: OperationResolver,
        parameter_binder: ParameterBinder,
        artifact_store: WorkflowArtifactStore,
        external_owners: ExternalOwnerPorts,
    ) -> None:
        if not isinstance(operation_resolver, OperationResolver):
            raise TypeError("operation_resolver must be an OperationResolver")
        if not isinstance(parameter_binder, ParameterBinder):
            raise TypeError("parameter_binder must be a ParameterBinder")
        if artifact_store is None:
            raise ValueError("artifact_store must not be None")
        if external_owners is None:
            raise ValueError("external_owners must not be None")
        self._operation_resolver = operation_resolver
        self._parameter_binder = parameter_binder
        self._artifact_store = artifact_store
        self._external_owners = external_owners

    def resolve_host_context(self, task_id: str) -> StableRef:
        """把 Host/context owner 的解析调用原样委托出去。"""

        return self._external_owners.resolve_host_context(task_id)

    def ensure_context_freshness(
        self,
        snapshot_ref: StableRef,
    ) -> StableRef | AsyncOperationRef:
        """由 freshness authoritative owner 决定立即继续还是进入异步等待。"""

        return self._external_owners.ensure_context_freshness(snapshot_ref)

    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef:
        """调用真实 OperationResolver，并仅把 workflow-local operation space 以 ref 暴露。"""

        inputs = self._external_owners.load_operation_resolution_inputs(snapshot_ref)
        if not isinstance(inputs, OperationResolutionInputs):
            raise TypeError(
                "load_operation_resolution_inputs must return OperationResolutionInputs"
            )
        profiles = inputs.profiles
        resolution_context = inputs.context
        resolution = self._operation_resolver.resolve(profiles, resolution_context)
        return self._artifact_store.put(
            kind="operation_resolution",
            value=resolution,
            content_hash=_artifact_content_hash(resolution),
        )

    def bind_parameters(
        self,
        operation_ref: StableRef,
    ) -> StableRef | AsyncOperationRef:
        """调用真实 ParameterBinder，并把绑定结果保存在 workflow-local artifact store。

        adapter 只验证 proposal 属于前一步已经持久化的 operation space；eligibility、slot
        binding、schema validation 等规则仍完全由 OperationResolver/ParameterBinder 持有。
        """

        operation_space = self._artifact_store.get(operation_ref)
        if not isinstance(operation_space, ResolutionResult):
            raise ValueError(
                "operation_ref must reference a persisted ResolutionResult operation space"
            )

        inputs = self._external_owners.load_parameter_binding_inputs(operation_ref)
        if not isinstance(inputs, ParameterBindingInputs):
            raise TypeError(
                "load_parameter_binding_inputs must return ParameterBindingInputs"
            )
        allowed_operations = {
            item.canonical_operation for item in operation_space.resolved_operations
        }
        if inputs.proposal.canonical_operation not in allowed_operations:
            raise ValueError("operation proposal is outside persisted operation space")

        proposal = inputs.proposal
        binding_context = inputs.context
        bound = self._parameter_binder.bind(proposal, binding_context)
        if not isinstance(bound, BoundOperationProposal):
            raise TypeError("ParameterBinder.bind must return BoundOperationProposal")
        return self._artifact_store.put(
            kind="bound_operation_proposal",
            value=bound,
            content_hash=_artifact_content_hash(bound),
        )

    def ensure_operation_freshness(
        self,
        operation_ref: StableRef,
    ) -> StableRef | AsyncOperationRef:
        """把 operation freshness 判断交还给 freshness authoritative owner。"""

        return self._external_owners.ensure_operation_freshness(operation_ref)

    def analyze_impact(self, operation_ref: StableRef) -> StableRef:
        """委托 Impact owner；本 adapter 不复制 impact 规则。"""

        return self._external_owners.analyze_impact(operation_ref)

    def build_changeset(self, impact_ref: StableRef) -> StableRef:
        """委托 ChangeSet owner；workflow 只接收稳定引用。"""

        return self._external_owners.build_changeset(impact_ref)

    def preview(self, changeset_ref: StableRef) -> StableRef:
        """委托 preview owner，并保持 ChangeSet authoritative truth 不进入 checkpoint。"""

        return self._external_owners.preview(changeset_ref)

    def request_approval(
        self,
        changeset_ref: StableRef,
    ) -> StableRef | AsyncOperationRef:
        """委托 Gateway/Approval owner 处理自动或 HITL approval。"""

        return self._external_owners.request_approval(changeset_ref)

    def plan_execution(
        self,
        changeset_ref: StableRef,
        approval_ref: StableRef,
    ) -> StableRef:
        """委托 execution-planning owner，不在 workflow 中复制计划规则。"""

        return self._external_owners.plan_execution(changeset_ref, approval_ref)

    def check_revision_barrier(self, execution_plan_ref: StableRef) -> None:
        """把 revision barrier 判断交给原 deterministic owner。"""

        self._external_owners.check_revision_barrier(execution_plan_ref)

    def bind_providers(self, execution_plan_ref: StableRef) -> StableRef:
        """委托 late ProviderBinding；resolver 的 provider candidates 不在 graph 中解释。"""

        return self._external_owners.bind_providers(execution_plan_ref)

    def issue_execution_grant(self, execution_plan_ref: StableRef) -> StableRef:
        """委托 Gateway owner 签发 ExecutionGrant。"""

        return self._external_owners.issue_execution_grant(execution_plan_ref)

    def begin_execution(
        self,
        execution_plan_ref: StableRef,
        grant_ref: StableRef,
    ) -> str | AsyncOperationRef:
        """委托 execution owner 启动执行；本 adapter 不制造 Saga/dispatch transition。"""

        return self._external_owners.begin_execution(execution_plan_ref, grant_ref)

    def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView:
        """读取 execution boundary 已组合好的 Saga + dispatch-recovery 稳定投影。"""

        return self._external_owners.get_execution_owner_state(saga_id)

    def verify_reconcile(self, saga_id: str) -> ExecutionOwnerView:
        """委托 execution/reconciliation owner 完成验证与收口。"""

        return self._external_owners.verify_reconcile(saga_id)


__all__ = [
    "DefaultWorkflowServices",
    "ExternalOwnerPorts",
    "OperationResolutionInputs",
    "ParameterBindingInputs",
    "WorkflowArtifactStore",
]
