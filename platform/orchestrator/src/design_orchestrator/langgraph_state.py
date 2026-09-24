"""ADR-010 LangGraph private state 的 checkpoint-safe 序列化边界。

本模块属于 Workflow Orchestrator runtime adapter 内部。LangGraph state 只能保存 workflow-local
导航数据、JSON-compatible 中间值与显式 stable-ref 字典；它不能持有 ChangeSet、Approval、
Execution Saga、Host dispatch intent、SemanticProjection 或 ActualDelta 等 authoritative 对象。
"""

from __future__ import annotations

from typing import Mapping, TypedDict

from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
)

# v2 是第一版显式持久化 human-pause identity 的 checkpoint contract。版本号属于 runtime-private
# persistence schema，不进入 framework-neutral WorkflowCheckpointView 公共契约。
CHECKPOINT_CONTRACT_VERSION = 2

# 这些名字用于 fail-closed 防线：即使调用者绕过正常转换器手工构造 state，也不能把其他
# authoritative owner 的完整对象重新塞进 Workflow Orchestrator checkpoint。
FORBIDDEN_AUTHORITATIVE_STATE_KEYS = frozenset(
    {
        "changeset_object",
        "approval_record_object",
        "execution_saga_object",
        "dispatch_intent_object",
        "semantic_projection_object",
        "actual_delta_object",
    }
)


class WorkflowGraphState(TypedDict, total=False):
    """LangGraph 私有状态；字段值必须可由 JSON-compatible checkpoint serializer 表达。"""

    checkpoint_contract_version: int
    task_id: str
    phase: str
    request_data: dict[str, object]
    initial_host_ref: dict[str, object] | None
    context_snapshot_ref: dict[str, object] | None
    operation_ref: dict[str, object] | None
    interaction_ref: dict[str, object] | None
    changeset_ref: dict[str, object] | None
    approval_ref: dict[str, object] | None
    execution_plan_ref: dict[str, object] | None
    saga_id: str | None
    async_operation_ref: dict[str, object] | None
    error_code: str | None
    pending_interaction: dict[str, object] | None

    # 以下字段仅用于 runtime 内部节点间传递稳定引用；它们仍然不是 authoritative object。
    planning_snapshot_ref: dict[str, object] | None
    snapshot_set_ref: dict[str, object] | None
    impact_ref: dict[str, object] | None
    preview_ref: dict[str, object] | None
    provider_binding_ref: dict[str, object] | None
    grant_ref: dict[str, object] | None
    resume_node: str | None

    # Task 7 只持久化“最近一次刷新后的路由分类/修订号”，不复制 Saga 或 dispatch recovery 对象。
    execution_resume_route: str | None
    refreshed_saga_revision: int | None


def _encode_stable_ref(ref: StableRef | None) -> dict[str, object] | None:
    """把 StableRef 显式编码为普通字典，避免依赖 Python object identity/pickle。"""

    if ref is None:
        return None
    if not isinstance(ref, StableRef):
        raise ValueError("stable ref must be a StableRef")
    return {
        "ref_id": ref.ref_id,
        "content_hash": ref.content_hash,
    }


def _decode_stable_ref(value: object, field_name: str) -> StableRef | None:
    """从 runtime-private 字典恢复 StableRef，并复用公共契约的 canonical 校验。"""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a stable-ref mapping")
    extra = set(value) - {"ref_id", "content_hash"}
    if extra:
        raise ValueError(f"{field_name} contains unsupported keys: {sorted(extra)}")
    return StableRef(
        ref_id=value.get("ref_id"),
        content_hash=value.get("content_hash"),
    )


def _encode_async_ref(ref: AsyncOperationRef | None) -> dict[str, object] | None:
    """把 AsyncOperationRef 编码为可跨进程恢复的 owner/kind/operation_id 三元组。"""

    if ref is None:
        return None
    if not isinstance(ref, AsyncOperationRef):
        raise ValueError("async operation ref must be an AsyncOperationRef")
    return {
        "kind": ref.kind.value,
        "owner": ref.owner,
        "operation_id": ref.operation_id,
    }


def _decode_async_ref(value: object, field_name: str) -> AsyncOperationRef | None:
    """从 runtime-private 字典恢复 AsyncOperationRef，并拒绝隐藏 session/process 对象。"""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an async-ref mapping")
    extra = set(value) - {"kind", "owner", "operation_id"}
    if extra:
        raise ValueError(f"{field_name} contains unsupported keys: {sorted(extra)}")
    try:
        kind = AsyncOperationKind(value.get("kind"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}.kind is invalid") from exc
    return AsyncOperationRef(
        kind=kind,
        owner=value.get("owner"),
        operation_id=value.get("operation_id"),
    )


def encode_pending_interaction(
    value: PendingInteractionView | None,
) -> dict[str, object] | None:
    """把 human pause 稳定视图编码成唯一允许的四字段 JSON-compatible body。"""

    if value is None:
        return None
    if not isinstance(value, PendingInteractionView):
        raise ValueError("pending interaction must be a PendingInteractionView")
    return {
        "pause_id": value.pause_id,
        "kind": value.kind.value,
        "subject_ref": _encode_stable_ref(value.subject_ref),
        "allowed_resume_kinds": list(value.allowed_resume_kinds),
    }


def decode_pending_interaction(
    value: object,
    field_name: str = "pending_interaction",
) -> PendingInteractionView | None:
    """严格恢复 persisted human pause，并拒绝任何未冻结隐藏字段或非 JSON 序列形状。"""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a pending-interaction mapping")

    allowed_keys = {
        "pause_id",
        "kind",
        "subject_ref",
        "allowed_resume_kinds",
    }
    extra = set(value) - allowed_keys
    if extra:
        raise ValueError(f"{field_name} contains unsupported keys: {sorted(extra)}")
    missing = allowed_keys - set(value)
    if missing:
        raise ValueError(f"{field_name} is missing required keys: {sorted(missing)}")

    subject_ref = _decode_stable_ref(value.get("subject_ref"), f"{field_name}.subject_ref")
    if subject_ref is None:
        raise ValueError(f"{field_name}.subject_ref is required")

    resume_kinds = value.get("allowed_resume_kinds")
    if not isinstance(resume_kinds, list):
        raise ValueError(f"{field_name}.allowed_resume_kinds must be a list")
    try:
        kind = PendingInteractionKind(value.get("kind"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}.kind is invalid") from exc

    return PendingInteractionView(
        pause_id=value.get("pause_id"),
        kind=kind,
        subject_ref=subject_ref,
        allowed_resume_kinds=tuple(resume_kinds),
    )


def checkpoint_view_to_graph_state(view: WorkflowCheckpointView) -> dict[str, object]:
    """把 framework-neutral checkpoint view 转成 LangGraph 私有、JSON-compatible state。

    该 helper 继续服务于 unversioned legacy characterization，因此不会凭空补 v2 版本号；只有
    runtime ``start()`` 能创建新的 versioned workflow identity。
    """

    if not isinstance(view, WorkflowCheckpointView):
        raise ValueError("view must be a WorkflowCheckpointView")
    return {
        "task_id": view.task_id,
        "phase": view.phase.value,
        "context_snapshot_ref": _encode_stable_ref(view.context_snapshot_ref),
        "operation_ref": _encode_stable_ref(view.operation_ref),
        "interaction_ref": _encode_async_ref(view.interaction_ref),
        "changeset_ref": _encode_stable_ref(view.changeset_ref),
        "approval_ref": _encode_stable_ref(view.approval_ref),
        "execution_plan_ref": _encode_stable_ref(view.execution_plan_ref),
        "saga_id": view.saga_id,
        "async_operation_ref": _encode_async_ref(view.async_operation_ref),
        "error_code": view.error_code,
        "pending_interaction": encode_pending_interaction(view.pending_interaction),
    }


def graph_state_to_checkpoint_view(state: Mapping[str, object]) -> WorkflowCheckpointView:
    """把 LangGraph 私有 state 投影回稳定公共 checkpoint view。

    私有的 impact/provider/grant 等中间引用不会泄漏到公共 view；它们只帮助 runtime 在节点间
    导航。若发现其他 owner 的 authoritative-object key，则立即 fail closed。未携带版本号的旧
    checkpoint 仅按 legacy 导航事实投影；v2 checkpoint 则必须满足完整 human-pause invariant。
    """

    if not isinstance(state, Mapping):
        raise ValueError("graph state must be a mapping")
    forbidden = FORBIDDEN_AUTHORITATIVE_STATE_KEYS.intersection(state)
    if forbidden:
        key = sorted(forbidden)[0]
        raise ValueError(f"authoritative object key is forbidden in graph state: {key}")

    version = state.get("checkpoint_contract_version")
    pending_interaction: PendingInteractionView | None = None
    if version is None:
        # 旧 checkpoint 允许继续投影，但这里绝不为它合成 human pause identity；
        # 精确 legacy migration 与恢复授权属于后续 Task 7 runtime 层。
        pending_interaction = None
    elif type(version) is int and version == CHECKPOINT_CONTRACT_VERSION:
        pending_interaction = decode_pending_interaction(state.get("pending_interaction"))
        try:
            phase = WorkflowPhase(state.get("phase"))
        except (TypeError, ValueError) as exc:
            raise ValueError("phase is invalid for checkpoint contract version 2") from exc
        if phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL and pending_interaction is None:
            raise ValueError(
                "pending_interaction is required for version 2 AWAIT_OPERATION_PROPOSAL"
            )
    else:
        raise ValueError(
            "checkpoint_contract_version is unsupported: "
            f"{version!r}"
        )

    return WorkflowCheckpointView(
        task_id=state.get("task_id"),
        phase=state.get("phase"),
        context_snapshot_ref=_decode_stable_ref(
            state.get("context_snapshot_ref"),
            "context_snapshot_ref",
        ),
        operation_ref=_decode_stable_ref(state.get("operation_ref"), "operation_ref"),
        interaction_ref=_decode_async_ref(
            state.get("interaction_ref"),
            "interaction_ref",
        ),
        changeset_ref=_decode_stable_ref(state.get("changeset_ref"), "changeset_ref"),
        approval_ref=_decode_stable_ref(state.get("approval_ref"), "approval_ref"),
        execution_plan_ref=_decode_stable_ref(
            state.get("execution_plan_ref"),
            "execution_plan_ref",
        ),
        saga_id=state.get("saga_id"),
        async_operation_ref=_decode_async_ref(
            state.get("async_operation_ref"),
            "async_operation_ref",
        ),
        error_code=state.get("error_code"),
        pending_interaction=pending_interaction,
    )


__all__ = [
    "CHECKPOINT_CONTRACT_VERSION",
    "FORBIDDEN_AUTHORITATIVE_STATE_KEYS",
    "WorkflowGraphState",
    "checkpoint_view_to_graph_state",
    "decode_pending_interaction",
    "encode_pending_interaction",
    "graph_state_to_checkpoint_view",
]
