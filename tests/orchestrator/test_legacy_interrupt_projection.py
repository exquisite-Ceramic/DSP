"""Task 7 Step 5：legacy interrupt-aware checkpoint projection 的 fail-closed 契约。

本文件补充两条与真实旧 graph fixture 正交的边界：

1. 未版本化 state 如果没有真实 LangGraph interrupt，不能只看 phase 猜测存在 human pause；
2. 未版本化 state 如果确实带有 interrupt，但形状既不是精确 Operation Proposal human wait，
   也不是精确 external-owner async wait，则必须以 ``WORKFLOW_CHECKPOINT_INVALID`` fail closed。

真实历史 human/async payload 的正向 fixture 已由 ``test_langgraph_runtime.py`` 覆盖；这里不重复
业务 happy path，只冻结“不能猜”和“未知 interrupt 不能静默忽略”两条防御边界。
"""

from __future__ import annotations

from importlib import import_module

import pytest
from design_orchestrator.langgraph_state import (
    WorkflowGraphState,
    _decode_stable_ref,
    _encode_stable_ref,
)
from design_orchestrator.workflow_contracts import StableRef, WorkflowPhase
from design_orchestrator.workflow_services import WorkflowStateError

# Step36 的轻量验证 lane 不安装 LangGraph。该文件只验证 runtime-private LangGraph
# checkpoint 行为，因此必须在动态加载 runtime/graph 类型前做模块级 skip，避免可选依赖
# 污染无关的 orchestrator 收集；Repository regression 安装 LangGraph 后仍会执行全部断言。
pytest.importorskip(
    "langgraph",
    reason="langgraph is required for legacy interrupt projection tests",
)
_runtime_module = import_module("design_orchestrator.langgraph_runtime")
LangGraphWorkflowRuntime = _runtime_module.LangGraphWorkflowRuntime
_checkpoint_lookup_config = _runtime_module._checkpoint_lookup_config
_runtime_config = _runtime_module._runtime_config
InMemorySaver = import_module("langgraph.checkpoint.memory").InMemorySaver
_graph_module = import_module("langgraph.graph")
END = _graph_module.END
START = _graph_module.START
StateGraph = _graph_module.StateGraph
interrupt = import_module("langgraph.types").interrupt


class _UnusedServices:
    """Projection 测试不会执行当前 production graph node，因此不提供任何 owner 行为。"""


def _runtime(checkpointer: InMemorySaver) -> LangGraphWorkflowRuntime:
    """用同一个 checkpointer 打开 legacy root checkpoint。"""

    return LangGraphWorkflowRuntime(
        services=_UnusedServices(),
        checkpointer=checkpointer,
    )


def _build_legacy_non_interrupt_graph(checkpointer: InMemorySaver):
    """构造会持久化 AWAIT_OPERATION_PROPOSAL phase、但从未产生 interrupt 的旧 graph。"""

    builder = StateGraph(WorkflowGraphState)

    def persist_legacy_state(state: WorkflowGraphState) -> dict[str, object]:
        """保持旧 phase/ref 原样结束，用来证明 runtime 不能仅凭 phase 猜 human pause。"""

        operation_ref = _decode_stable_ref(state["operation_ref"], "operation_ref")
        assert operation_ref is not None
        return {
            "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
            "operation_ref": _encode_stable_ref(operation_ref),
        }

    builder.add_node("persist_legacy_state", persist_legacy_state)
    builder.add_edge(START, "persist_legacy_state")
    builder.add_edge("persist_legacy_state", END)
    return builder.compile(checkpointer=checkpointer)


def _build_unrecognized_legacy_interrupt_graph(checkpointer: InMemorySaver):
    """用真实历史 node name 构造 payload 不属于冻结闭集的 legacy interrupt。"""

    builder = StateGraph(WorkflowGraphState)

    def await_unknown_legacy_interrupt(state: WorkflowGraphState) -> dict[str, object]:
        """保留旧 await node identity，但产生未知 kind，runtime 必须 fail closed。"""

        operation_ref = _decode_stable_ref(state["operation_ref"], "operation_ref")
        assert operation_ref is not None
        interrupt(
            {
                "kind": "UNKNOWN_LEGACY_WAIT",
                "operation_ref": _encode_stable_ref(operation_ref),
            }
        )
        return {"phase": WorkflowPhase.PARAMETER_BINDING.value}

    # 当前 runtime 只能可靠恢复历史 topology 闭集内的 pending task。这里故意复用真实旧
    # node name，仅篡改 interrupt payload，才能准确验证“可恢复但未知的 legacy shape”。
    builder.add_node("await_operation_proposal", await_unknown_legacy_interrupt)
    builder.add_edge(START, "await_operation_proposal")
    builder.add_edge("await_operation_proposal", END)
    return builder.compile(checkpointer=checkpointer)


def _legacy_state(task_id: str, operation_ref: StableRef) -> dict[str, object]:
    """返回未版本化、未携带 pending identity 的历史 operation-proposal state。"""

    return {
        "task_id": task_id,
        "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
        "context_snapshot_ref": _encode_stable_ref(
            StableRef("legacy-snapshot", "a" * 64)
        ),
        "operation_ref": _encode_stable_ref(operation_ref),
    }


def test_unversioned_operation_phase_without_interrupt_does_not_guess_human_pause() -> None:
    """没有真实 interrupt 时，即使 phase 看似 human wait，也只能返回无 pending 的旧投影。"""

    task_id = "task-legacy-no-interrupt"
    operation_ref = StableRef("legacy-operation", "b" * 64)
    saver = InMemorySaver()
    legacy_graph = _build_legacy_non_interrupt_graph(saver)
    legacy_graph.invoke(
        _legacy_state(task_id, operation_ref),
        _runtime_config(task_id),
    )

    legacy_snapshot = legacy_graph.get_state(_checkpoint_lookup_config(task_id))
    assert legacy_snapshot.values.get("checkpoint_contract_version") is None
    assert legacy_snapshot.interrupts == ()

    checkpoint = _runtime(saver).get_checkpoint(task_id)

    assert checkpoint is not None
    assert checkpoint.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert checkpoint.operation_ref == operation_ref
    assert checkpoint.pending_interaction is None


def test_unrecognized_real_legacy_interrupt_fails_closed() -> None:
    """历史 node 上的未知真实 interrupt 不能被静默当成普通 unversioned state。"""

    task_id = "task-legacy-unknown-interrupt"
    operation_ref = StableRef("legacy-operation", "b" * 64)
    saver = InMemorySaver()
    legacy_graph = _build_unrecognized_legacy_interrupt_graph(saver)
    legacy_graph.invoke(
        _legacy_state(task_id, operation_ref),
        _runtime_config(task_id),
    )

    legacy_snapshot = legacy_graph.get_state(_checkpoint_lookup_config(task_id))
    assert len(legacy_snapshot.interrupts) == 1
    assert legacy_snapshot.interrupts[0].value == {
        "kind": "UNKNOWN_LEGACY_WAIT",
        "operation_ref": _encode_stable_ref(operation_ref),
    }

    with pytest.raises(WorkflowStateError) as captured:
        _runtime(saver).get_checkpoint(task_id)

    assert captured.value.code == "WORKFLOW_CHECKPOINT_INVALID"
