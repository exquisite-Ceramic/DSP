"""ADR-010 Workflow Orchestrator 的 deterministic service 边界。

本模块只定义 framework-neutral 的 service protocol 与 execution-owner read model。Workflow
Orchestrator 可以据此编排现有确定性能力，但不能直接依赖具体 workflow runtime、数据库
repository 或其他 owner 的内部领域对象。执行恢复尤其必须先读取 Host effect recovery truth，
再解释 Saga 状态，不能从 checkpoint 位置推断外部副作用是否已经发生。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from design_orchestrator.workflow_contracts import AsyncOperationRef, StableRef

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _required_text(value: object, field_name: str) -> str:
    """规范化必填文本身份，并拒绝非字符串或空白值。"""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _optional_sha256(value: object | None, field_name: str) -> str | None:
    """验证可选的 canonical lowercase SHA-256。"""

    if value is None:
        return None
    normalized = _required_text(value, field_name)
    if _SHA256_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


class WorkflowStateError(RuntimeError):
    """Workflow owner 对无法安全分类的状态暴露稳定错误码。"""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = _required_text(code, "code")
        self.detail = None if detail is None else _required_text(detail, "detail")
        message = self.code if self.detail is None else f"{self.code}: {self.detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class OwnerStateView:
    """其他 authoritative owner 对 orchestrator 暴露的最小稳定状态投影。"""

    ref: StableRef
    status: str

    def __post_init__(self) -> None:
        if not isinstance(self.ref, StableRef):
            raise ValueError("ref must be a StableRef")
        object.__setattr__(self, "status", _required_text(self.status, "status"))


@dataclass(frozen=True, slots=True)
class OperationArtifactResolution:
    """Operation Resolution artifact 可用性检查的稳定结果。

    ``ref`` 始终指向当前可供 v2 workflow 使用的 durable artifact；``source`` 只记录该
    artifact 是直接命中 durable store，还是由经过 legacy hash 校验的历史状态重建而来。
    完整 ``ResolutionResult`` 不跨越这个 framework-neutral service 边界。
    """

    ref: StableRef
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.ref, StableRef):
            raise ValueError("ref must be a StableRef")
        normalized_source = _required_text(self.source, "source")
        if normalized_source not in {"durable", "rehydrated"}:
            raise ValueError("source must be 'durable' or 'rehydrated'")
        object.__setattr__(self, "source", normalized_source)


@dataclass(frozen=True, slots=True)
class ExecutionSagaView:
    """Execution Saga owner 暴露给 workflow 的只读执行投影。"""

    saga_id: str
    saga_revision: int
    status: str
    active_slice_hash: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "saga_id", _required_text(self.saga_id, "saga_id"))
        if isinstance(self.saga_revision, bool) or not isinstance(self.saga_revision, int):
            raise ValueError("saga_revision must be an integer")
        if self.saga_revision < 0:
            raise ValueError("saga_revision must be non-negative")
        object.__setattr__(self, "status", _required_text(self.status, "status"))
        object.__setattr__(
            self,
            "active_slice_hash",
            _optional_sha256(self.active_slice_hash, "active_slice_hash"),
        )


class HostDispatchRecoveryState(str, Enum):
    """ADR-009 Host effect recovery truth 的 workflow-facing 状态集合。"""

    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SAFE_TO_RETRY = "SAFE_TO_RETRY"


@dataclass(frozen=True, slots=True)
class HostDispatchRecoveryView:
    """当前 active Host dispatch recovery 的最小只读投影。"""

    dispatch_intent_id: str
    execution_slice_hash: str
    state: HostDispatchRecoveryState

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dispatch_intent_id",
            _required_text(self.dispatch_intent_id, "dispatch_intent_id"),
        )
        normalized_hash = _optional_sha256(
            self.execution_slice_hash,
            "execution_slice_hash",
        )
        if normalized_hash is None:
            raise ValueError("execution_slice_hash must not be null")
        object.__setattr__(self, "execution_slice_hash", normalized_hash)
        object.__setattr__(self, "state", HostDispatchRecoveryState(self.state))


@dataclass(frozen=True, slots=True)
class ExecutionOwnerView:
    """组合 Saga truth 与 Host-effect recovery truth 的 execution boundary read model。

    该 read model 只是查询边界，不合并两个 owner 的写入所有权。Host effect recovery 保持
    独立投影，因此不会为了方便 workflow 恢复而向 Saga 枚举中添加 OUTCOME_UNKNOWN。
    """

    saga: ExecutionSagaView
    active_dispatch_recovery: HostDispatchRecoveryView | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.saga, ExecutionSagaView):
            raise ValueError("saga must be an ExecutionSagaView")
        if self.active_dispatch_recovery is not None and not isinstance(
            self.active_dispatch_recovery,
            HostDispatchRecoveryView,
        ):
            raise ValueError(
                "active_dispatch_recovery must be a HostDispatchRecoveryView or None"
            )


class WorkflowServices(Protocol):
    """Workflow Orchestrator 可调用的 deterministic service port 集合。"""

    def resolve_host_context(self, task_id: str) -> StableRef: ...

    def ensure_context_freshness(
        self,
        snapshot_ref: StableRef,
    ) -> StableRef | AsyncOperationRef: ...

    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef: ...

    def ensure_operation_artifact(
        self,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
        *,
        allow_legacy_rehydrate: bool,
    ) -> OperationArtifactResolution: ...

    def bind_parameters(
        self,
        operation_ref: StableRef,
    ) -> StableRef | AsyncOperationRef: ...

    def ensure_operation_freshness(
        self,
        operation_ref: StableRef,
    ) -> StableRef | AsyncOperationRef: ...

    def analyze_impact(self, operation_ref: StableRef) -> StableRef: ...

    def build_changeset(
        self,
        task_id: str,
        operation_ref: StableRef,
        impact_ref: StableRef,
    ) -> StableRef: ...

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


def classify_execution_resume(view: ExecutionOwnerView) -> str:
    """根据最新 execution-owner truth 决定 workflow 的恢复类别。

    顺序是 ADR-010 的安全不变量：必须先解释 active Host dispatch recovery，再解释 Saga。
    即使 Saga 看起来仍允许 dispatch，只要存在未收口的 Host-effect recovery，workflow 就只能
    进入恢复/等待路径，不能创建新的 Host command identity。
    """

    if not isinstance(view, ExecutionOwnerView):
        raise ValueError("view must be an ExecutionOwnerView")

    recovery = view.active_dispatch_recovery
    if recovery is not None:
        if recovery.state in {
            HostDispatchRecoveryState.OUTCOME_UNKNOWN,
            HostDispatchRecoveryState.RECOVERY_REQUIRED,
            HostDispatchRecoveryState.SAFE_TO_RETRY,
        }:
            return "RECOVER_OR_WAIT"
        raise WorkflowStateError(
            "WORKFLOW_EXECUTION_RECOVERY_STATE_UNKNOWN",
            str(recovery.state),
        )

    saga = view.saga
    if saga.status in {"SUCCEEDED", "DIVERGED", "PARTIALLY_COMMITTED", "FAILED"}:
        return "TERMINAL"
    if saga.status in {"EXECUTING", "CONVERGENCE_PENDING"}:
        return "RECOVER_OR_WAIT"
    if saga.status == "READY":
        return "MAY_DISPATCH"
    raise WorkflowStateError("WORKFLOW_SAGA_STATUS_UNKNOWN", saga.status)


__all__ = [
    "ExecutionOwnerView",
    "ExecutionSagaView",
    "HostDispatchRecoveryState",
    "HostDispatchRecoveryView",
    "OperationArtifactResolution",
    "OwnerStateView",
    "WorkflowServices",
    "WorkflowStateError",
    "classify_execution_resume",
]
