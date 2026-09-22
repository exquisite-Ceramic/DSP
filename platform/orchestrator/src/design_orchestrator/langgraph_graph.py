"""ADR-010 的 LangGraph 私有 graph topology。

LangGraph 在这里仅负责编排确定性服务、等待与恢复路由。每个节点最多调用一个
``WorkflowServices`` 方法；OperationResolver、ParameterBinder、Gateway、Execution Saga
与 Host-dispatch recovery 的业务规则继续由各自 authoritative owner 持有。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from design_orchestrator.langgraph_state import (
    WorkflowGraphState,
    _decode_async_ref,
    _decode_stable_ref,
    _encode_async_ref,
    _encode_stable_ref,
    decode_pending_interaction,
    encode_pending_interaction,
    graph_state_to_checkpoint_view,
)
from design_orchestrator.recovery import decide_apply_resume
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowPhase,
)
from design_orchestrator.workflow_services import WorkflowServices

MAIN_PATH = (
    "resolve_host_context",
    "ensure_context_freshness",
    "resolve_operations",
    "prepare_operation_proposal_pause",
    "await_operation_proposal",
    "parameter_binding",
    "ensure_operation_freshness",
    "analyze_impact",
    "build_changeset",
    "preview",
    "policy_approval",
    "execution_planning",
    "revision_barrier",
    "provider_binding",
    "execution_grant",
    "refresh_execution_owner",
    "apply_or_recover",
    "verify_reconcile",
)

_ASYNC_RESUME_NODES = {
    "ensure_context_freshness",
    "parameter_binding",
    "ensure_operation_freshness",
    "policy_approval",
    "refresh_execution_owner",
    "apply_or_recover",
}


def _require_stable_ref(state: WorkflowGraphState, field_name: str) -> StableRef:
    """从 graph state 读取必需的 StableRef，并在 checkpoint 损坏时 fail closed。"""

    ref = _decode_stable_ref(state.get(field_name), field_name)
    if ref is None:
        raise ValueError(f"{field_name} is required")
    return ref


def _set_async_wait(
    ref: AsyncOperationRef,
    *,
    resume_node: str,
    phase: WorkflowPhase,
) -> dict[str, object]:
    """把异步 owner 引用写入 state，并记录恢复后必须重新查询的确定性节点。"""

    return {
        "phase": phase.value,
        "async_operation_ref": _encode_async_ref(ref),
        "resume_node": resume_node,
    }


def _route_async_or(next_node: str):
    """生成只读取 workflow-local state 的异步条件路由器。"""

    def route(state: WorkflowGraphState) -> str:
        return "await_async_operation" if state.get("async_operation_ref") else next_node

    return route


def _route_after_async_wait(state: WorkflowGraphState) -> str:
    """等待恢复后回到原 service node，由 authoritative owner 重新给出当前事实。"""

    resume_node = state.get("resume_node")
    if not isinstance(resume_node, str) or resume_node not in _ASYNC_RESUME_NODES:
        raise ValueError("async resume_node is missing or invalid")
    return resume_node


def _route_after_operation_proposal(state: WorkflowGraphState) -> str:
    """根据已验证的人机决策路由到 binder 或稳定的 CANCELLED 终点。"""

    phase = state.get("phase")
    if phase == WorkflowPhase.PARAMETER_BINDING.value:
        return "parameter_binding"
    if phase == WorkflowPhase.CANCELLED.value:
        return "cancelled"
    raise ValueError("operation proposal resume route is missing or invalid")


def _route_after_execution_refresh(state: WorkflowGraphState) -> str:
    """只根据 refresh node 已持久化的纯路由结果选择下一 graph node。"""

    if state.get("async_operation_ref"):
        return "await_async_operation"
    route = state.get("execution_resume_route")
    if route == "MAY_DISPATCH":
        return "apply_or_recover"
    if route == "TERMINAL_EXECUTION_STATE":
        return "verify_reconcile"
    raise ValueError("execution resume route is missing or invalid")


def build_workflow_graph(services: WorkflowServices) -> StateGraph:
    """构建 ADR-010 LangGraph topology，但不在构图阶段执行任何 service side effect。"""

    builder = StateGraph(WorkflowGraphState)

    def resolve_host_context(state: WorkflowGraphState) -> dict[str, object]:
        ref = services.resolve_host_context(cast(str, state["task_id"]))
        return {
            "context_snapshot_ref": _encode_stable_ref(ref),
            "phase": WorkflowPhase.ENSURE_CONTEXT_FRESHNESS.value,
        }

    def ensure_context_freshness(state: WorkflowGraphState) -> dict[str, object]:
        result = services.ensure_context_freshness(
            _require_stable_ref(state, "context_snapshot_ref")
        )
        if isinstance(result, AsyncOperationRef):
            return _set_async_wait(
                result,
                resume_node="ensure_context_freshness",
                phase=WorkflowPhase.ENSURE_CONTEXT_FRESHNESS,
            )
        return {
            "context_snapshot_ref": _encode_stable_ref(result),
            "async_operation_ref": None,
            "phase": WorkflowPhase.RESOLVE_OPERATIONS.value,
        }

    def resolve_operations(state: WorkflowGraphState) -> dict[str, object]:
        result = services.resolve_operations(
            _require_stable_ref(state, "context_snapshot_ref")
        )
        return {
            "operation_ref": _encode_stable_ref(result),
            # v2 的 AWAIT_OPERATION_PROPOSAL checkpoint 必须与 pending identity 原子出现；
            # 因此 resolve node 保持当前 phase，真正的人机等待状态由下一 prepare node 写入。
            "phase": WorkflowPhase.RESOLVE_OPERATIONS.value,
        }

    def prepare_operation_proposal_pause(
        state: WorkflowGraphState,
    ) -> dict[str, object]:
        """在 interrupt 之前生成并持久化唯一 proposal pause identity。"""

        operation_ref = _require_stable_ref(state, "operation_ref")
        pending = PendingInteractionView(
            pause_id=str(uuid4()),
            kind=PendingInteractionKind.OPERATION_PROPOSAL,
            subject_ref=operation_ref,
            allowed_resume_kinds=(
                "OPERATION_PROPOSAL_ACCEPTED",
                "OPERATION_PROPOSAL_REJECTED",
            ),
        )
        return {
            "pending_interaction": encode_pending_interaction(pending),
            "async_operation_ref": None,
            "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
        }

    def await_operation_proposal(state: WorkflowGraphState) -> dict[str, object]:
        """暂停并只接受与 durable pause identity 精确相关的 ACCEPT/REJECT。"""

        operation_ref = _require_stable_ref(state, "operation_ref")
        pending = decode_pending_interaction(state.get("pending_interaction"))
        if pending is None:
            raise ValueError("pending_interaction is required for operation proposal wait")
        if pending.kind is not PendingInteractionKind.OPERATION_PROPOSAL:
            raise ValueError("pending interaction kind is invalid for operation proposal wait")
        if pending.subject_ref != operation_ref:
            raise ValueError("pending interaction subject does not match operation_ref")

        resumed = interrupt(
            {
                "pause_id": pending.pause_id,
                "kind": pending.kind.value,
                "subject_ref": _encode_stable_ref(pending.subject_ref),
            }
        )
        if not isinstance(resumed, Mapping):
            raise ValueError("operation proposal resume payload must be a mapping")

        expected_keys = {"pause_id", "resume_kind", "payload"}
        actual_keys = set(resumed)
        if actual_keys != expected_keys:
            raise ValueError(
                "operation proposal resume payload must contain exactly "
                "pause_id, resume_kind, and payload"
            )
        if resumed.get("pause_id") != pending.pause_id:
            raise ValueError("operation proposal resume pause_id does not match pending pause")

        resume_kind = resumed.get("resume_kind")
        if resume_kind not in pending.allowed_resume_kinds:
            raise ValueError("operation proposal resume_kind is not allowed")
        payload = resumed.get("payload")
        if not isinstance(payload, Mapping) or payload:
            raise ValueError("operation proposal human payload must be an empty mapping")

        if resume_kind == "OPERATION_PROPOSAL_REJECTED":
            return {
                "pending_interaction": None,
                "phase": WorkflowPhase.CANCELLED.value,
            }
        return {
            "pending_interaction": None,
            "phase": WorkflowPhase.PARAMETER_BINDING.value,
        }

    def parameter_binding(state: WorkflowGraphState) -> dict[str, object]:
        result = services.bind_parameters(_require_stable_ref(state, "operation_ref"))
        if isinstance(result, AsyncOperationRef):
            return _set_async_wait(
                result,
                resume_node="parameter_binding",
                phase=WorkflowPhase.PARAMETER_BINDING,
            )
        return {
            "operation_ref": _encode_stable_ref(result),
            "async_operation_ref": None,
            "phase": WorkflowPhase.ENSURE_OPERATION_FRESHNESS.value,
        }

    def ensure_operation_freshness(state: WorkflowGraphState) -> dict[str, object]:
        result = services.ensure_operation_freshness(
            _require_stable_ref(state, "operation_ref")
        )
        if isinstance(result, AsyncOperationRef):
            return _set_async_wait(
                result,
                resume_node="ensure_operation_freshness",
                phase=WorkflowPhase.ENSURE_OPERATION_FRESHNESS,
            )
        return {
            "operation_ref": _encode_stable_ref(result),
            "async_operation_ref": None,
            "phase": WorkflowPhase.ANALYZE_IMPACT.value,
        }

    def analyze_impact(state: WorkflowGraphState) -> dict[str, object]:
        result = services.analyze_impact(_require_stable_ref(state, "operation_ref"))
        return {
            "impact_ref": _encode_stable_ref(result),
            "phase": WorkflowPhase.BUILD_CHANGESET.value,
        }

    def build_changeset(state: WorkflowGraphState) -> dict[str, object]:
        """显式携带 task/operation/impact lineage，禁止从 content-addressed owner truth 反推 task。"""

        result = services.build_changeset(
            cast(str, state["task_id"]),
            _require_stable_ref(state, "operation_ref"),
            _require_stable_ref(state, "impact_ref"),
        )
        return {
            "changeset_ref": _encode_stable_ref(result),
            "phase": WorkflowPhase.PREVIEW.value,
        }

    def preview(state: WorkflowGraphState) -> dict[str, object]:
        result = services.preview(_require_stable_ref(state, "changeset_ref"))
        return {
            "preview_ref": _encode_stable_ref(result),
            "phase": WorkflowPhase.POLICY_APPROVAL.value,
        }

    def policy_approval(state: WorkflowGraphState) -> dict[str, object]:
        result = services.request_approval(_require_stable_ref(state, "changeset_ref"))
        if isinstance(result, AsyncOperationRef):
            return _set_async_wait(
                result,
                resume_node="policy_approval",
                phase=WorkflowPhase.POLICY_APPROVAL,
            )
        return {
            "approval_ref": _encode_stable_ref(result),
            "async_operation_ref": None,
            "phase": WorkflowPhase.EXECUTION_PLANNING.value,
        }

    def execution_planning(state: WorkflowGraphState) -> dict[str, object]:
        result = services.plan_execution(
            _require_stable_ref(state, "changeset_ref"),
            _require_stable_ref(state, "approval_ref"),
        )
        return {
            "execution_plan_ref": _encode_stable_ref(result),
            "phase": WorkflowPhase.REVISION_BARRIER.value,
        }

    def revision_barrier(state: WorkflowGraphState) -> dict[str, object]:
        services.check_revision_barrier(_require_stable_ref(state, "execution_plan_ref"))
        return {"phase": WorkflowPhase.PROVIDER_BINDING.value}

    def provider_binding(state: WorkflowGraphState) -> dict[str, object]:
        result = services.bind_providers(_require_stable_ref(state, "execution_plan_ref"))
        return {
            "provider_binding_ref": _encode_stable_ref(result),
            "phase": WorkflowPhase.EXECUTION_GRANT.value,
        }

    def execution_grant(state: WorkflowGraphState) -> dict[str, object]:
        result = services.issue_execution_grant(
            _require_stable_ref(state, "execution_plan_ref")
        )
        return {
            "grant_ref": _encode_stable_ref(result),
            "phase": WorkflowPhase.APPLY_WAIT.value,
        }

    def refresh_execution_owner(state: WorkflowGraphState) -> dict[str, object]:
        """在每次 apply/recovery 决策前重新读取完整 execution-owner authoritative truth。"""

        saga_id = state.get("saga_id")
        execution = None
        if isinstance(saga_id, str) and saga_id.strip():
            execution = services.get_execution_owner_state(saga_id.strip())

        decision = decide_apply_resume(
            checkpoint=graph_state_to_checkpoint_view(state),
            execution=execution,
        )
        update: dict[str, object] = {
            "execution_resume_route": decision.route,
            "refreshed_saga_revision": decision.refreshed_saga_revision,
            "async_operation_ref": None,
        }
        if decision.route == "RECOVER_OR_WAIT":
            if not isinstance(saga_id, str) or not saga_id.strip():
                raise ValueError("RECOVER_OR_WAIT requires durable saga_id")
            update.update(
                _set_async_wait(
                    AsyncOperationRef(
                        kind=AsyncOperationKind.EXECUTION_JOB,
                        owner="execution",
                        operation_id=saga_id.strip(),
                    ),
                    resume_node="refresh_execution_owner",
                    phase=WorkflowPhase.APPLY_WAIT,
                )
            )
        elif decision.route == "TERMINAL_EXECUTION_STATE":
            update["phase"] = WorkflowPhase.VERIFY_RECONCILE.value
        else:
            update["phase"] = WorkflowPhase.APPLY_WAIT.value
        return update

    def apply_or_recover(state: WorkflowGraphState) -> dict[str, object]:
        result = services.begin_execution(
            _require_stable_ref(state, "execution_plan_ref"),
            _require_stable_ref(state, "grant_ref"),
        )
        if isinstance(result, AsyncOperationRef):
            return _set_async_wait(
                result,
                resume_node="refresh_execution_owner",
                phase=WorkflowPhase.APPLY_WAIT,
            )
        if not isinstance(result, str) or not result.strip():
            raise ValueError("begin_execution must return saga_id or AsyncOperationRef")
        return {
            "saga_id": result.strip(),
            "async_operation_ref": None,
            "execution_resume_route": None,
            "phase": WorkflowPhase.VERIFY_RECONCILE.value,
        }

    def verify_reconcile(state: WorkflowGraphState) -> dict[str, object]:
        saga_id = state.get("saga_id")
        if not isinstance(saga_id, str) or not saga_id.strip():
            raise ValueError("saga_id is required for verify_reconcile")
        services.verify_reconcile(saga_id.strip())
        return {
            "execution_resume_route": None,
            "phase": WorkflowPhase.COMPLETED.value,
        }

    def await_async_operation(state: WorkflowGraphState) -> dict[str, object]:
        ref = _decode_async_ref(state.get("async_operation_ref"), "async_operation_ref")
        if ref is None:
            raise ValueError("async_operation_ref is required for async wait")
        interrupt(
            {
                "kind": "ASYNC_OPERATION",
                "operation_ref": _encode_async_ref(ref),
            }
        )
        # 恢复值只作为“允许重新查询 owner”的信号；远程结果仍必须由 service 自己重新读取。
        return {"async_operation_ref": None}

    for name, node in (
        ("resolve_host_context", resolve_host_context),
        ("ensure_context_freshness", ensure_context_freshness),
        ("resolve_operations", resolve_operations),
        ("prepare_operation_proposal_pause", prepare_operation_proposal_pause),
        ("await_operation_proposal", await_operation_proposal),
        ("parameter_binding", parameter_binding),
        ("ensure_operation_freshness", ensure_operation_freshness),
        ("analyze_impact", analyze_impact),
        ("build_changeset", build_changeset),
        ("preview", preview),
        ("policy_approval", policy_approval),
        ("execution_planning", execution_planning),
        ("revision_barrier", revision_barrier),
        ("provider_binding", provider_binding),
        ("execution_grant", execution_grant),
        ("refresh_execution_owner", refresh_execution_owner),
        ("apply_or_recover", apply_or_recover),
        ("verify_reconcile", verify_reconcile),
        ("await_async_operation", await_async_operation),
    ):
        builder.add_node(name, node)

    builder.add_edge(START, "resolve_host_context")
    builder.add_edge("resolve_host_context", "ensure_context_freshness")
    builder.add_conditional_edges(
        "ensure_context_freshness",
        _route_async_or("resolve_operations"),
        {
            "await_async_operation": "await_async_operation",
            "resolve_operations": "resolve_operations",
        },
    )
    builder.add_edge("resolve_operations", "prepare_operation_proposal_pause")
    builder.add_edge("prepare_operation_proposal_pause", "await_operation_proposal")
    builder.add_conditional_edges(
        "await_operation_proposal",
        _route_after_operation_proposal,
        {
            "parameter_binding": "parameter_binding",
            "cancelled": END,
        },
    )
    builder.add_conditional_edges(
        "parameter_binding",
        _route_async_or("ensure_operation_freshness"),
        {
            "await_async_operation": "await_async_operation",
            "ensure_operation_freshness": "ensure_operation_freshness",
        },
    )
    builder.add_conditional_edges(
        "ensure_operation_freshness",
        _route_async_or("analyze_impact"),
        {
            "await_async_operation": "await_async_operation",
            "analyze_impact": "analyze_impact",
        },
    )
    builder.add_edge("analyze_impact", "build_changeset")
    builder.add_edge("build_changeset", "preview")
    builder.add_edge("preview", "policy_approval")
    builder.add_conditional_edges(
        "policy_approval",
        _route_async_or("execution_planning"),
        {
            "await_async_operation": "await_async_operation",
            "execution_planning": "execution_planning",
        },
    )
    builder.add_edge("execution_planning", "revision_barrier")
    builder.add_edge("revision_barrier", "provider_binding")
    builder.add_edge("provider_binding", "execution_grant")
    builder.add_edge("execution_grant", "refresh_execution_owner")
    builder.add_conditional_edges(
        "refresh_execution_owner",
        _route_after_execution_refresh,
        {
            "await_async_operation": "await_async_operation",
            "apply_or_recover": "apply_or_recover",
            "verify_reconcile": "verify_reconcile",
        },
    )
    builder.add_conditional_edges(
        "apply_or_recover",
        _route_async_or("verify_reconcile"),
        {
            "await_async_operation": "await_async_operation",
            "verify_reconcile": "verify_reconcile",
        },
    )
    builder.add_conditional_edges(
        "await_async_operation",
        _route_after_async_wait,
        {node: node for node in sorted(_ASYNC_RESUME_NODES)},
    )
    builder.add_edge("verify_reconcile", END)

    return builder


__all__ = ["MAIN_PATH", "build_workflow_graph"]
