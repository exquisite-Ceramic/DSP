"""ADR-010 LangGraph private state 与 graph topology 的 RED/GREEN 边界测试。

这些测试不把 LangGraph 类型提升为 DSP 公共契约，只验证 runtime adapter 内部的 state 可以
安全持久化，并且 graph topology 只负责调用 deterministic services、等待与路由。
"""

from __future__ import annotations

import json
from uuid import UUID

from design_orchestrator.langgraph_graph import MAIN_PATH, build_workflow_graph
from design_orchestrator.langgraph_state import (
    checkpoint_view_to_graph_state,
    graph_state_to_checkpoint_view,
)
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

FORBIDDEN_KEYS = {
    "changeset_object",
    "approval_record_object",
    "execution_saga_object",
    "dispatch_intent_object",
    "semantic_projection_object",
    "actual_delta_object",
}

EXPECTED_MAIN_PATH = (
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
    # Task 7 冻结：进入 apply/recovery 决策前必须先重新读取 execution-owner authoritative truth。
    "refresh_execution_owner",
    "apply_or_recover",
    "verify_reconcile",
)


class _CompileOnlyServices:
    """仅供 graph builder 结构测试使用；任何方法被执行都说明测试越过了结构边界。"""

    def __getattr__(self, name: str):
        raise AssertionError(f"graph build must not execute service method: {name}")


class _ProposalPauseServices:
    """把 graph 推到 proposal human pause，并用下一次 async wait 截断 ACCEPT 路径。"""

    def __init__(self) -> None:
        self.bind_count = 0

    def resolve_host_context(self, task_id: str) -> StableRef:
        """返回稳定 context snapshot，避免测试依赖任何真实 Host。"""

        return StableRef(f"snapshot-{task_id}", "a" * 64)

    def ensure_context_freshness(self, snapshot_ref: StableRef) -> StableRef:
        """保持 snapshot 不变，使测试只观察 HITL topology。"""

        return snapshot_ref

    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef:
        """返回固定 operation ref，供 pending subject 精确绑定。"""

        return StableRef("operation-1", "b" * 64)

    def bind_parameters(self, operation_ref: StableRef) -> AsyncOperationRef:
        """记录 ACCEPT 是否真正进入 binder，并立即转入既有 external-owner wait。"""

        self.bind_count += 1
        return AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="interaction-1",
        )

    def __getattr__(self, name: str):
        """任何超出 proposal/binder 边界的调用都说明测试拓扑意外前进。"""

        raise AssertionError(f"unexpected workflow service call: {name}")


def _checkpoint() -> WorkflowCheckpointView:
    """构造包含全部关键稳定引用的 framework-neutral checkpoint。"""

    waiting = AsyncOperationRef(
        kind=AsyncOperationKind.RECONSTRUCTION_JOB,
        owner="semantic-runtime",
        operation_id="reconstruction-1",
    )
    return WorkflowCheckpointView(
        task_id="task-1",
        phase=WorkflowPhase.ENSURE_CONTEXT_FRESHNESS,
        context_snapshot_ref=StableRef("snapshot-1", "a" * 64),
        operation_ref=StableRef("operation-1", "b" * 64),
        interaction_ref=AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="interaction-1",
        ),
        changeset_ref=StableRef("changeset-1", "c" * 64),
        approval_ref=StableRef("approval-1", "d" * 64),
        execution_plan_ref=StableRef("plan-1", "e" * 64),
        saga_id="saga-1",
        async_operation_ref=waiting,
        error_code="WAITING_FOR_OWNER",
    )


def _proposal_graph():
    """构建只用于 proposal pause RED/GREEN 的 compiled graph 与稳定 checkpoint config。"""

    services = _ProposalPauseServices()
    saver = InMemorySaver()
    graph = build_workflow_graph(services).compile(checkpointer=saver)
    config = {
        "configurable": {
            "thread_id": "task-proposal-pause",
            "checkpoint_ns": "",
        }
    }
    initial_state = {
        "checkpoint_contract_version": 2,
        "task_id": "task-proposal-pause",
        "phase": WorkflowPhase.RESOLVE_HOST_CONTEXT.value,
    }
    return services, graph, config, initial_state


def test_langgraph_state_contains_only_workflow_local_json_values() -> None:
    """Private graph state 只能包含 workflow-local JSON 值与显式编码后的稳定引用。"""

    state = checkpoint_view_to_graph_state(_checkpoint())

    assert FORBIDDEN_KEYS.isdisjoint(state)
    assert isinstance(state["task_id"], str)
    assert isinstance(state["phase"], str)
    assert isinstance(state["context_snapshot_ref"], dict)
    assert isinstance(state["async_operation_ref"], dict)

    # JSON round-trip 是 checkpoint-safe state 的最低证明；禁止依赖 pickle/domain object identity。
    encoded = json.dumps(state, sort_keys=True)
    assert json.loads(encoded) == state


def test_graph_state_round_trips_to_framework_neutral_checkpoint() -> None:
    """Runtime-private serialization 不得改变 DSP 稳定 checkpoint view 的含义。"""

    expected = _checkpoint()
    actual = graph_state_to_checkpoint_view(checkpoint_view_to_graph_state(expected))

    assert actual == expected


def test_graph_state_rejects_authoritative_object_keys() -> None:
    """即使调用方手工构造 state，也不能把 authoritative object 偷渡进 checkpoint。"""

    state = checkpoint_view_to_graph_state(_checkpoint())
    state["execution_saga_object"] = {"status": "EXECUTING"}

    try:
        graph_state_to_checkpoint_view(state)
    except ValueError as exc:
        assert "execution_saga_object" in str(exc)
    else:
        raise AssertionError("authoritative object key must be rejected")


def test_langgraph_builder_freezes_adr010_main_path_without_running_services() -> None:
    """Graph builder 必须声明 ADR-010 主路径，并且构图阶段绝不能执行 service side effect。"""

    builder = build_workflow_graph(_CompileOnlyServices())

    assert MAIN_PATH == EXPECTED_MAIN_PATH
    assert set(EXPECTED_MAIN_PATH).issubset(builder.nodes)
    assert "await_async_operation" in builder.nodes

    # 这里只断言真正无条件的静态边；可返回 AsyncOperationRef 的节点必须通过 conditional
    # routing 选择正常主路径或 await_async_operation，不能同时声明会绕过等待的静态边。
    assert ("resolve_host_context", "ensure_context_freshness") in builder.edges
    assert ("resolve_operations", "prepare_operation_proposal_pause") in builder.edges
    assert ("prepare_operation_proposal_pause", "await_operation_proposal") in builder.edges
    assert ("analyze_impact", "build_changeset") in builder.edges
    assert ("execution_planning", "revision_barrier") in builder.edges
    assert ("revision_barrier", "provider_binding") in builder.edges
    assert ("provider_binding", "execution_grant") in builder.edges
    assert ("execution_grant", "refresh_execution_owner") in builder.edges

    # human ACCEPT/REJECT 必须通过 conditional routing 决定进入 binder 还是 CANCELLED/END；
    # 因此 await_operation_proposal 不能保留旧的无条件 parameter_binding 静态边。
    assert "await_operation_proposal" in builder.branches
    assert ("await_operation_proposal", "parameter_binding") not in builder.edges

    # Task 7 后 refresh_execution_owner 必须通过 conditional routing 决定 dispatch、等待或
    # terminal reconcile；它不能用静态 edge 跳过 authoritative owner 的恢复判定。
    assert "refresh_execution_owner" in builder.branches

    # apply_or_recover 的逻辑下一步仍由 MAIN_PATH 冻结为 verify_reconcile，但它必须保留
    # AsyncOperationRef detour，因此这里验证它有条件分支而不是强迫一个无条件静态 edge。
    assert "apply_or_recover" in builder.branches


def test_prepare_node_persists_correlated_operation_proposal_pause() -> None:
    """Human pause identity 必须在 interrupt 前持久化，并精确绑定当前 operation stable ref。"""

    services, graph, config, initial_state = _proposal_graph()

    graph.invoke(initial_state, config)
    snapshot = graph.get_state(config)
    pending = snapshot.values["pending_interaction"]

    assert snapshot.values["checkpoint_contract_version"] == 2
    assert snapshot.values["phase"] == WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value
    assert pending["kind"] == "OPERATION_PROPOSAL"
    assert pending["subject_ref"] == {
        "ref_id": "operation-1",
        "content_hash": "b" * 64,
    }
    assert pending["allowed_resume_kinds"] == [
        "OPERATION_PROPOSAL_ACCEPTED",
        "OPERATION_PROPOSAL_REJECTED",
    ]
    assert snapshot.values.get("async_operation_ref") is None
    assert UUID(pending["pause_id"])
    assert services.bind_count == 0


def test_operation_proposal_accept_clears_pending_and_enters_parameter_binding() -> None:
    """匹配 pause_id 的 ACCEPT 才能消费 human pause，并进入既有 binder。"""

    services, graph, config, initial_state = _proposal_graph()
    graph.invoke(initial_state, config)
    pause_id = graph.get_state(config).values["pending_interaction"]["pause_id"]

    graph.invoke(
        Command(
            resume={
                "pause_id": pause_id,
                "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
                "payload": {},
            }
        ),
        config,
    )
    snapshot = graph.get_state(config)

    assert services.bind_count == 1
    assert snapshot.values.get("pending_interaction") is None
    assert snapshot.values["phase"] == WorkflowPhase.PARAMETER_BINDING.value
    assert snapshot.values["async_operation_ref"] == {
        "kind": AsyncOperationKind.INTERACTION_SESSION.value,
        "owner": "interaction",
        "operation_id": "interaction-1",
    }


def test_operation_proposal_reject_cancels_without_calling_binder() -> None:
    """匹配 pause_id 的 REJECT 必须终止 workflow，且不能触发 binder 或任何下游 service。"""

    services, graph, config, initial_state = _proposal_graph()
    graph.invoke(initial_state, config)
    pause_id = graph.get_state(config).values["pending_interaction"]["pause_id"]

    graph.invoke(
        Command(
            resume={
                "pause_id": pause_id,
                "resume_kind": "OPERATION_PROPOSAL_REJECTED",
                "payload": {},
            }
        ),
        config,
    )
    snapshot = graph.get_state(config)

    assert services.bind_count == 0
    assert snapshot.values.get("pending_interaction") is None
    assert snapshot.values["phase"] == WorkflowPhase.CANCELLED.value
