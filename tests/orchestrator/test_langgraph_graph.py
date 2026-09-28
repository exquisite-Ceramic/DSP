"""ADR-010 LangGraph private state 与 graph topology 的 RED/GREEN 边界测试。

这些测试不把 LangGraph 类型提升为 DSP 公共契约，只验证 runtime adapter 内部的 state 可以
安全持久化，并且 graph topology 只负责调用 deterministic services、等待与路由。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

import pytest
from design_orchestrator import workflow_contracts as workflow_contracts_module
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
from design_orchestrator.workflow_services import (
    ExecutionOwnerView,
    ExecutionSagaView,
    HostDispatchRecoveryState,
    HostDispatchRecoveryView,
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

    def bind_parameters(
        self,
        task_id: str,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> AsyncOperationRef:
        """记录 ACCEPT 是否真正进入 binder，并立即转入既有 external-owner wait。"""

        del operation_ref, context_snapshot_ref
        self.bind_count += 1
        return AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="interaction-1",
        )

    def __getattr__(self, name: str):
        """任何超出 proposal/binder 边界的调用都说明测试拓扑意外前进。"""

        raise AssertionError(f"unexpected workflow service call: {name}")


@dataclass(frozen=True, slots=True)
class _OperationFreshnessResultProbe:
    """RED 阶段临时表达已批准的新 tuple；GREEN 后工厂会自动使用 production type。"""

    operation_ref: StableRef
    planning_snapshot_ref: StableRef
    snapshot_set_ref: StableRef


def _freshness_result(
    operation_ref: StableRef,
    planning_snapshot_ref: StableRef,
    snapshot_set_ref: StableRef,
):
    """在 contract 尚未实现时仍让 graph RED 精确落在 tuple 处理能力。"""

    result_type = getattr(
        workflow_contracts_module,
        "OperationFreshnessResult",
        _OperationFreshnessResultProbe,
    )
    return result_type(
        operation_ref=operation_ref,
        planning_snapshot_ref=planning_snapshot_ref,
        snapshot_set_ref=snapshot_set_ref,
    )


class _FreshnessGraphServices:
    """把真实 graph 推过 freshness/Impact，并在 approval async wait 处稳定截断。"""

    def __init__(self, *, async_first: bool = False) -> None:
        self.async_first = async_first
        self.freshness_calls = 0
        self.impact_calls: list[tuple[StableRef, StableRef, StableRef]] = []
        self.bound_ref = StableRef("bound-operation-42", "a" * 64)
        self.planning_ref = StableRef("PS-42", "b" * 64)
        self.snapshot_set_ref = StableRef("PSS-42", "c" * 64)

    def resolve_host_context(self, task_id: str) -> StableRef:
        """返回测试固定的 Host/context 引用。"""

        return StableRef(f"context-{task_id}", "1" * 64)

    def ensure_context_freshness(self, snapshot_ref: StableRef) -> StableRef:
        """保持 context 引用不变，使测试聚焦 operation freshness。"""

        return snapshot_ref

    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef:
        """返回 proposal pause 绑定的 operation-space 引用。"""

        return StableRef("operation-space-42", "2" * 64)

    def bind_parameters(
        self,
        task_id: str,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> StableRef:
        """Human ACCEPT 后返回已绑定 operation 引用。"""

        del operation_ref, context_snapshot_ref
        return self.bound_ref

    def ensure_operation_freshness(self, operation_ref: StableRef):
        """可先模拟一次异步 wait，随后返回批准的 exact freshness tuple。"""

        assert operation_ref == self.bound_ref
        self.freshness_calls += 1
        if self.async_first and self.freshness_calls == 1:
            return AsyncOperationRef(
                kind=AsyncOperationKind.RECONSTRUCTION_JOB,
                owner="semantic-runtime",
                operation_id="reconstruct-43",
            )
        return _freshness_result(
            self.bound_ref,
            self.planning_ref,
            self.snapshot_set_ref,
        )

    def analyze_impact(
        self,
        operation_ref: StableRef,
        planning_snapshot_ref: StableRef,
        snapshot_set_ref: StableRef,
    ) -> StableRef:
        """记录 graph 是否把同一个 successful freshness tuple 原样传入 Impact。"""

        self.impact_calls.append(
            (operation_ref, planning_snapshot_ref, snapshot_set_ref)
        )
        return StableRef("impact-42", "d" * 64)

    def build_changeset(
        self,
        task_id: str,
        operation_ref: StableRef,
        impact_ref: StableRef,
    ) -> StableRef:
        """返回稳定 ChangeSet ref，把测试继续推进到 approval wait。"""

        return StableRef("changeset-42", "e" * 64)

    def preview(self, changeset_ref: StableRef) -> StableRef:
        """返回 presentation ref，不引入额外 workflow 语义。"""

        return StableRef("preview-42", "f" * 64)

    def request_approval(self, changeset_ref: StableRef) -> AsyncOperationRef:
        """用既有 async wait 稳定截断 graph，便于读取 saver 中间状态。"""

        return AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="approval",
            operation_id="approval-42",
        )


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


def _freshness_graph(*, async_first: bool, seed_stale_pair: bool):
    """构建 Task 6R.1 freshness tuple 测试所需的 compiled graph。"""

    services = _FreshnessGraphServices(async_first=async_first)
    saver = InMemorySaver()
    graph = build_workflow_graph(services).compile(checkpointer=saver)
    config = {
        "configurable": {
            "thread_id": (
                "task-freshness-async" if async_first else "task-freshness-success"
            ),
            "checkpoint_ns": "",
        }
    }
    initial_state: dict[str, object] = {
        "checkpoint_contract_version": 2,
        "task_id": config["configurable"]["thread_id"],
        "phase": WorkflowPhase.RESOLVE_HOST_CONTEXT.value,
    }
    if seed_stale_pair:
        initial_state.update(
            {
                "planning_snapshot_ref": {
                    "ref_id": "PS-old",
                    "content_hash": "8" * 64,
                },
                "snapshot_set_ref": {
                    "ref_id": "PSS-old",
                    "content_hash": "9" * 64,
                },
            }
        )
    return services, graph, config, initial_state


def _accept_operation_proposal(graph, config, initial_state) -> None:
    """把 graph 从 proposal pause 精确恢复到 ACCEPT 路径。"""

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


def test_operation_freshness_success_persists_atomic_exact_tuple_and_forwards_it() -> None:
    """successful freshness 必须一次持久化三个 exact refs，并原样传给 Impact。"""

    services, graph, config, initial_state = _freshness_graph(
        async_first=False,
        seed_stale_pair=False,
    )

    try:
        _accept_operation_proposal(graph, config, initial_state)
    except (TypeError, ValueError) as exc:
        raise AssertionError(
            "graph must understand the approved exact operation-freshness tuple"
        ) from exc

    snapshot = graph.get_state(config)
    assert snapshot.values["operation_ref"] == {
        "ref_id": "bound-operation-42",
        "content_hash": "a" * 64,
    }
    assert snapshot.values["planning_snapshot_ref"] == {
        "ref_id": "PS-42",
        "content_hash": "b" * 64,
    }
    assert snapshot.values["snapshot_set_ref"] == {
        "ref_id": "PSS-42",
        "content_hash": "c" * 64,
    }
    assert services.impact_calls == [
        (services.bound_ref, services.planning_ref, services.snapshot_set_ref)
    ]


def test_operation_freshness_async_wait_clears_stale_pair_then_writes_new_tuple() -> None:
    """async wait 必须清掉旧 pair，resume 后只能写入并消费新的 successful tuple。"""

    services, graph, config, initial_state = _freshness_graph(
        async_first=True,
        seed_stale_pair=True,
    )

    _accept_operation_proposal(graph, config, initial_state)
    waiting = graph.get_state(config)

    assert waiting.values.get("planning_snapshot_ref") is None
    assert waiting.values.get("snapshot_set_ref") is None
    assert waiting.values["async_operation_ref"] == {
        "kind": AsyncOperationKind.RECONSTRUCTION_JOB.value,
        "owner": "semantic-runtime",
        "operation_id": "reconstruct-43",
    }
    assert services.impact_calls == []

    # 直接驱动 compiled graph 时也使用 production runtime 的非空 async resume payload shape；
    # 空 dict 会被 LangGraph 解释为未提供可消费的 interrupt resume value。
    graph.invoke(
        Command(
            resume={
                "pause_id": None,
                "resume_kind": "ASYNC_OPERATION_COMPLETED",
                "payload": {"operation_id": "reconstruct-43"},
            }
        ),
        config,
    )
    resumed = graph.get_state(config)

    assert resumed.values["operation_ref"] == {
        "ref_id": "bound-operation-42",
        "content_hash": "a" * 64,
    }
    assert resumed.values["planning_snapshot_ref"] == {
        "ref_id": "PS-42",
        "content_hash": "b" * 64,
    }
    assert resumed.values["snapshot_set_ref"] == {
        "ref_id": "PSS-42",
        "content_hash": "c" * 64,
    }
    assert services.impact_calls == [
        (services.bound_ref, services.planning_ref, services.snapshot_set_ref)
    ]


def _freshness_graph_before_impact():
    """使用真实 InMemorySaver 把 production graph 停在 analyze_impact 执行前。"""

    services = _FreshnessGraphServices(async_first=False)
    saver = InMemorySaver()
    graph = build_workflow_graph(services).compile(checkpointer=saver)
    config = {
        "configurable": {
            "thread_id": "task-freshness-before-impact",
            "checkpoint_ns": "",
        }
    }
    initial_state = {
        "checkpoint_contract_version": 2,
        "task_id": "task-freshness-before-impact",
        "phase": WorkflowPhase.RESOLVE_HOST_CONTEXT.value,
    }
    graph.invoke(initial_state, config=config)
    pause_id = graph.get_state(config).values["pending_interaction"]["pause_id"]
    graph.invoke(
        Command(
            resume={
                "pause_id": pause_id,
                "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
                "payload": {},
            }
        ),
        config=config,
        interrupt_before=["analyze_impact"],
    )
    return services, saver, graph, config


def _round_trip_exact_refs(values: dict[str, object]) -> dict[str, StableRef]:
    """只从 saver 读回的 JSON-compatible values 重建三个 StableRef。"""

    persisted = {
        field_name: values[field_name]
        for field_name in (
            "operation_ref",
            "planning_snapshot_ref",
            "snapshot_set_ref",
        )
    }
    restored = json.loads(json.dumps(persisted, sort_keys=True))
    return {
        field_name: StableRef(**restored[field_name])
        for field_name in persisted
    }


def test_task6r3_saver_backed_exact_refs_survive_json_round_trip() -> None:
    """真实 LangGraph saver 中的三个 exact refs 必须可经 JSON round-trip 恢复。"""

    services, _, graph, config = _freshness_graph_before_impact()
    snapshot = graph.get_state(config)

    assert snapshot.next == ("analyze_impact",)
    assert FORBIDDEN_KEYS.isdisjoint(snapshot.values)
    restored = _round_trip_exact_refs(snapshot.values)
    assert restored == {
        "operation_ref": services.bound_ref,
        "planning_snapshot_ref": services.planning_ref,
        "snapshot_set_ref": services.snapshot_set_ref,
    }
    assert services.impact_calls == []


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("operation_ref", None),
        ("planning_snapshot_ref", None),
        ("snapshot_set_ref", None),
        ("operation_ref", {"ref_id": "", "content_hash": "a" * 64}),
        ("planning_snapshot_ref", {"ref_id": "PS-42", "content_hash": "invalid"}),
        ("snapshot_set_ref", {"ref_id": "PSS-42", "unexpected": "value"}),
    ),
    ids=(
        "missing-operation",
        "missing-planning",
        "missing-snapshot-set",
        "malformed-operation-id",
        "malformed-planning-hash",
        "malformed-snapshot-set-shape",
    ),
)
def test_task6r3_graph_rejects_missing_or_malformed_ref_before_service_dispatch(
    field_name: str,
    invalid_value: object,
) -> None:
    """graph 只对缺失/编码非法 ref fail closed，且不得调用 WorkflowServices Impact seam。"""

    services, _, graph, config = _freshness_graph_before_impact()
    graph.update_state(
        config,
        {field_name: invalid_value},
        as_node="ensure_operation_freshness",
    )

    with pytest.raises(ValueError):
        graph.invoke(None, config=config)
    assert services.impact_calls == []


class _ExecutionSagaWaitServices:
    """只记录 Task 8.5 apply/wait/recovery 调用，不复制 execution owner 状态机。"""

    def __init__(
        self,
        *,
        async_kind: AsyncOperationKind = AsyncOperationKind.EXECUTION_JOB,
        async_owner: str = "execution",
    ) -> None:
        self.async_kind = async_kind
        self.async_owner = async_owner
        self.begin_count = 0
        self.owner_refresh_count = 0

    def __getattr__(self, name: str):
        """Task 8.5 只允许 graph 调用 execution 边界；其它调用说明测试越界。"""

        raise AssertionError(f"unexpected workflow service call: {name}")

    def begin_execution(
        self,
        execution_plan_ref: StableRef,
        grant_ref: StableRef,
    ) -> AsyncOperationRef:
        """模拟 owner 已创建 durable Saga 后返回异步等待引用。"""

        assert execution_plan_ref == StableRef("plan-task8", "1" * 64)
        assert grant_ref == StableRef("grant-task8", "2" * 64)
        self.begin_count += 1
        operation_id = (
            "SAGA-123"
            if self.async_kind is AsyncOperationKind.EXECUTION_JOB
            else "not-a-saga-operation"
        )
        return AsyncOperationRef(
            kind=self.async_kind,
            owner=self.async_owner,
            operation_id=operation_id,
        )

    def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView:
        """恢复时暴露 OUTCOME_UNKNOWN owner truth，证明 graph 不得再次 dispatch。"""

        assert saga_id == "SAGA-123"
        self.owner_refresh_count += 1
        slice_hash = "a" * 64
        return ExecutionOwnerView(
            saga=ExecutionSagaView(
                saga_id=saga_id,
                saga_revision=4,
                status="EXECUTING",
                active_slice_hash=slice_hash,
            ),
            active_dispatch_recovery=HostDispatchRecoveryView(
                dispatch_intent_id="dispatch-task8",
                execution_slice_hash=slice_hash,
                state=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
            ),
        )


def _seed_execution_apply(services: _ExecutionSagaWaitServices):
    """把 saver-backed graph 定位到 execution_grant 后、首次 execution refresh 之前。"""

    saver = InMemorySaver()
    graph = build_workflow_graph(services).compile(checkpointer=saver)
    config = {
        "configurable": {
            "thread_id": f"task8-execution-{services.async_kind.value}",
            "checkpoint_ns": "",
        }
    }
    graph.update_state(
        config,
        {
            "checkpoint_contract_version": 2,
            "task_id": config["configurable"]["thread_id"],
            "phase": WorkflowPhase.APPLY_WAIT.value,
            "execution_plan_ref": {
                "ref_id": "plan-task8",
                "content_hash": "1" * 64,
            },
            "grant_ref": {
                "ref_id": "grant-task8",
                "content_hash": "2" * 64,
            },
        },
        as_node="execution_grant",
    )
    return graph, config


def test_execution_async_wait_persists_saga_identity_atomically() -> None:
    """EXECUTION_JOB wait 必须与 durable Saga identity 在同一 node update 中出现。"""

    services = _ExecutionSagaWaitServices()
    graph, config = _seed_execution_apply(services)

    graph.invoke(None, config=config)
    snapshot = graph.get_state(config).values

    assert services.begin_count == 1
    assert snapshot.get("saga_id") == "SAGA-123"
    assert snapshot["async_operation_ref"] == {
        "kind": AsyncOperationKind.EXECUTION_JOB.value,
        "owner": "execution",
        "operation_id": "SAGA-123",
    }
    assert snapshot["resume_node"] == "refresh_execution_owner"
    assert snapshot["phase"] == WorkflowPhase.APPLY_WAIT.value


def test_non_execution_async_wait_never_copies_operation_id_to_saga_id() -> None:
    """其它合法 async kind 的 operation id 绝不能被 graph 提升成 Saga identity。"""

    services = _ExecutionSagaWaitServices(
        async_kind=AsyncOperationKind.RECONSTRUCTION_JOB,
        async_owner="semantic-runtime",
    )
    graph, config = _seed_execution_apply(services)

    graph.invoke(None, config=config)
    snapshot = graph.get_state(config).values

    assert services.begin_count == 1
    assert snapshot.get("saga_id") is None
    assert snapshot["async_operation_ref"]["operation_id"] == "not-a-saga-operation"


def test_execution_saga_unknown_resume_does_not_redispatch() -> None:
    """Saver 唤醒后必须用已持久化 Saga refresh OUTCOME_UNKNOWN，不能第二次 begin。"""

    services = _ExecutionSagaWaitServices()
    graph, config = _seed_execution_apply(services)

    graph.invoke(None, config=config)
    assert services.begin_count == 1

    graph.invoke(Command(resume={"status": "wake"}), config=config)

    assert services.begin_count == 1
    assert services.owner_refresh_count == 1
    snapshot = graph.get_state(config).values
    assert snapshot.get("saga_id") == "SAGA-123"
    assert snapshot["resume_node"] == "refresh_execution_owner"
    assert snapshot["phase"] == WorkflowPhase.APPLY_WAIT.value
