"""ADR-010 的 LangGraph 私有 graph topology。

LangGraph 在这里仅负责编排确定性服务、等待与恢复路由。每个节点最多调用一个
``WorkflowServices`` 方法；OperationResolver、ParameterBinder、Gateway、Execution Saga
与 Host-dispatch recovery 的业务规则继续由各自 authoritative owner 持有。
"""

from __future__ import annotations

from typing import Literal, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from design_orchestrator.langgraph_state import (
    WorkflowGraphState,
    _decode_async_ref,
    _decode_stable_ref,
    _encode_async_ref,
    _encode_stable_ref,
)
from design_orchestrator.workflow_contracts import (
    AsyncOperationRef,
    StableRef,
    WorkflowPhase,
)
from design_orchestrator.workflow_services import WorkflowServices

MAIN_PATH = (
    "resolve_host_context",
    "ensure_context_freshness",
    "resolve_operations",
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
    "apply_or_recover",
    "verify_reconcile",
)

_ASYNC_RESUME_NODES = {
    "ensure_context_freshness",
    "parameter_binding",
    "ensure_operation_freshness",
    "policy_approval",
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
            "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
        }

    def await_operation_proposal(state: WorkflowGraphState) -> dict[str, object]:
        operation_ref = _require_stable_ref(state, "operation_ref")
        interrupt(
            {
                "kind": "OPERATION_PROPOSAL",
                "operation_ref": _encode_stable_ref(operation_ref),
            }
        )
        return {"phase": WorkflowPhase.PARAMETER_BINDING.value}

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
        result = services.build_changeset(_require_stable_ref(state, "impact_ref"))
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

    def apply_or_recover(state: WorkflowGraphState) -> dict[str, object]:
        result = services.begin_execution(
            _require_stable_ref(state, "execution_plan_ref"),
            _require_stable_ref(state, "grant_ref"),
        )
        if isinstance(result, AsyncOperationRef):
            return _set_async_wait(
                result,
                resume_node="apply_or_recover",
                phase=WorkflowPhase.APPLY_WAIT,
            )
        if not isinstance(result, str) or not result.strip():
            raise ValueError("begin_execution must return saga_id or AsyncOperationRef")
        return {
            "saga_id": result.strip(),
            "async_operation_ref": None,
            "phase": WorkflowPhase.VERIFY_RECONCILE.value,
        }

    def verify_reconcile(state: WorkflowGraphState) -> dict[str, object]:
        saga_id = state.get("saga_id")
        if not isinstance(saga_id, str) or not saga_id.strip():
            raise ValueError("saga_id is required for verify_reconcile")
        services.verify_reconcile(saga_id.strip())
        return {"phase": WorkflowPhase.COMPLETED.value}

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
    builder.add_edge("resolve_operations", "await_operation_proposal")
    builder.add_edge("await_operation_proposal", "parameter_binding")
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
    builder.add_edge("execution_grant", "apply_or_recover")
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
