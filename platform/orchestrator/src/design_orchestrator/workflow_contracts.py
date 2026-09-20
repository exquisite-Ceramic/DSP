"""ADR-010 的 framework-neutral workflow 公共契约。

本模块只定义 Workflow Orchestrator 自己拥有的导航、等待与稳定引用数据。任何第三方
workflow runtime 的对象都不得进入这些类型；跨 owner 的业务事实只能通过 stable ref
被引用，不能复制成 checkpoint 的第二份 authoritative truth。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _required_text(value: object, field_name: str) -> str:
    """规范化必填文本，并拒绝非字符串或空白身份。"""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _optional_text(value: object | None, field_name: str) -> str | None:
    """规范化可选文本；一旦提供，就必须满足必填文本约束。"""

    if value is None:
        return None
    return _required_text(value, field_name)


def _optional_sha256(value: object | None, field_name: str) -> str | None:
    """规范化并验证 canonical lowercase SHA-256。"""

    if value is None:
        return None
    normalized = _required_text(value, field_name)
    if _SHA256_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _copy_mapping(value: Mapping[str, object], field_name: str) -> dict[str, object]:
    """复制调用方 mapping，避免后续外部修改污染已经冻结的 workflow command。"""

    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    copied = dict(value)
    if any(not isinstance(key, str) or not key.strip() for key in copied):
        raise ValueError(f"{field_name} keys must be non-blank strings")
    return copied


class AsyncOperationKind(str, Enum):
    """可持久化等待的异步操作种类。"""

    INTERACTION_SESSION = "INTERACTION_SESSION"
    RECONSTRUCTION_JOB = "RECONSTRUCTION_JOB"
    EXECUTION_JOB = "EXECUTION_JOB"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class AsyncOperationRef:
    """指向外部 authoritative owner 长任务的稳定恢复引用。"""

    kind: AsyncOperationKind
    owner: str
    operation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", AsyncOperationKind(self.kind))
        object.__setattr__(self, "owner", _required_text(self.owner, "owner"))
        object.__setattr__(
            self,
            "operation_id",
            _required_text(self.operation_id, "operation_id"),
        )


@dataclass(frozen=True, slots=True)
class StableRef:
    """引用 authoritative artifact，而不是复制其完整业务对象。"""

    ref_id: str
    content_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_id", _required_text(self.ref_id, "ref_id"))
        object.__setattr__(
            self,
            "content_hash",
            _optional_sha256(self.content_hash, "content_hash"),
        )


class PendingInteractionKind(str, Enum):
    """Workflow Orchestrator 自己拥有的人机暂停交互种类。"""

    OPERATION_PROPOSAL = "OPERATION_PROPOSAL"


@dataclass(frozen=True, slots=True)
class PendingInteractionView:
    """可跨 runtime 重启观察和相关的人机暂停稳定视图。"""

    pause_id: str
    kind: PendingInteractionKind
    subject_ref: StableRef
    allowed_resume_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pause_id", _required_text(self.pause_id, "pause_id"))
        object.__setattr__(self, "kind", PendingInteractionKind(self.kind))
        if not isinstance(self.subject_ref, StableRef):
            raise TypeError("subject_ref must be a StableRef")
        if not isinstance(self.allowed_resume_kinds, tuple):
            raise ValueError("allowed_resume_kinds must be a tuple")
        normalized = tuple(
            _required_text(item, "allowed_resume_kinds")
            for item in self.allowed_resume_kinds
        )
        if not normalized:
            raise ValueError("allowed_resume_kinds must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_resume_kinds must not contain duplicates")
        object.__setattr__(self, "allowed_resume_kinds", normalized)


class WorkflowPhase(str, Enum):
    """DSP v0.6 Workflow Orchestrator 的稳定导航阶段。"""

    RESOLVE_INTENT = "RESOLVE_INTENT"
    RESOLVE_HOST_CONTEXT = "RESOLVE_HOST_CONTEXT"
    ENSURE_CONTEXT_FRESHNESS = "ENSURE_CONTEXT_FRESHNESS"
    RESOLVE_OPERATIONS = "RESOLVE_OPERATIONS"
    AWAIT_OPERATION_PROPOSAL = "AWAIT_OPERATION_PROPOSAL"
    PARAMETER_BINDING = "PARAMETER_BINDING"
    ENSURE_OPERATION_FRESHNESS = "ENSURE_OPERATION_FRESHNESS"
    ANALYZE_IMPACT = "ANALYZE_IMPACT"
    BUILD_CHANGESET = "BUILD_CHANGESET"
    PREVIEW = "PREVIEW"
    POLICY_APPROVAL = "POLICY_APPROVAL"
    EXECUTION_PLANNING = "EXECUTION_PLANNING"
    REVISION_BARRIER = "REVISION_BARRIER"
    PROVIDER_BINDING = "PROVIDER_BINDING"
    EXECUTION_GRANT = "EXECUTION_GRANT"
    APPLY_WAIT = "APPLY_WAIT"
    VERIFY_RECONCILE = "VERIFY_RECONCILE"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointView:
    """只暴露 workflow-local navigation state 与跨 owner 稳定引用的 checkpoint 视图。"""

    task_id: str
    phase: WorkflowPhase
    context_snapshot_ref: StableRef | None = None
    operation_ref: StableRef | None = None
    interaction_ref: AsyncOperationRef | None = None
    changeset_ref: StableRef | None = None
    approval_ref: StableRef | None = None
    execution_plan_ref: StableRef | None = None
    saga_id: str | None = None
    async_operation_ref: AsyncOperationRef | None = None
    error_code: str | None = None
    pending_interaction: PendingInteractionView | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _required_text(self.task_id, "task_id"))
        object.__setattr__(self, "phase", WorkflowPhase(self.phase))
        object.__setattr__(self, "saga_id", _optional_text(self.saga_id, "saga_id"))
        object.__setattr__(
            self,
            "error_code",
            _optional_text(self.error_code, "error_code"),
        )
        if self.pending_interaction is not None:
            if not isinstance(self.pending_interaction, PendingInteractionView):
                raise TypeError("pending_interaction must be a PendingInteractionView")
            if self.async_operation_ref is not None or self.interaction_ref is not None:
                raise ValueError(
                    "pending_interaction is mutually exclusive with external waits"
                )


@dataclass(frozen=True, slots=True)
class WorkflowStartRequest:
    """启动 workflow 所需的本地请求数据与初始稳定引用。"""

    task_id: str
    request_data: Mapping[str, object] = field(default_factory=dict)
    initial_host_ref: StableRef | None = None
    initial_context_ref: StableRef | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _required_text(self.task_id, "task_id"))
        object.__setattr__(
            self,
            "request_data",
            _copy_mapping(self.request_data, "request_data"),
        )


@dataclass(frozen=True, slots=True)
class WorkflowResumeCommand:
    """显式 HITL/用户继续输入；不得携带其他 owner 的 authoritative 对象。"""

    resume_kind: str
    payload: Mapping[str, object] = field(default_factory=dict)
    pause_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resume_kind",
            _required_text(self.resume_kind, "resume_kind"),
        )
        object.__setattr__(self, "payload", _copy_mapping(self.payload, "payload"))
        object.__setattr__(
            self,
            "pause_id",
            _optional_text(self.pause_id, "pause_id"),
        )


__all__ = [
    "AsyncOperationKind",
    "AsyncOperationRef",
    "PendingInteractionKind",
    "PendingInteractionView",
    "StableRef",
    "WorkflowCheckpointView",
    "WorkflowPhase",
    "WorkflowResumeCommand",
    "WorkflowStartRequest",
]
