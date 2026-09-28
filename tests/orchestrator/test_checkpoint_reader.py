"""Product Front Door 所需的只读 LangGraph checkpoint adapter 契约测试。

这些测试故意只给读取侧传入 checkpointer，不构造 ``WorkflowServices`` 或可执行 workflow
runtime。checkpoint 的写入使用最小 LangGraph graph，仅用于制造真实持久化数据。
"""

from __future__ import annotations

import pytest

# 轻量 deterministic lane 不安装 LangGraph；该模块只属于 runtime 专用验证。
pytest.importorskip("langgraph")

import design_orchestrator.langgraph_runtime as langgraph_runtime
from design_orchestrator import LangGraphWorkflowCheckpointReader
from design_orchestrator.langgraph_state import (
    CHECKPOINT_CONTRACT_VERSION,
    WorkflowGraphState,
)
from design_orchestrator.workflow_contracts import WorkflowCheckpointView, WorkflowPhase
from design_orchestrator.workflow_services import WorkflowStateError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


def _persist_checkpoint(
    saver: InMemorySaver,
    *,
    lookup_task_id: str,
    state_task_id: str,
    phase: str,
) -> None:
    """通过真实 LangGraph saver 写入一个最小 root checkpoint。"""

    builder = StateGraph(WorkflowGraphState)

    def persist(state: WorkflowGraphState) -> dict[str, object]:
        """节点不产生新的业务事实，只让输入状态经过真实 checkpoint persistence。"""

        del state
        return {}

    builder.add_node("persist", persist)
    builder.add_edge(START, "persist")
    builder.add_edge("persist", END)
    graph = builder.compile(checkpointer=saver)
    graph.invoke(
        {
            "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
            "task_id": state_task_id,
            "phase": phase,
        },
        langgraph_runtime._runtime_config(lookup_task_id),
    )


def test_reader_projects_real_persisted_checkpoint_without_workflow_services() -> None:
    """reader 必须只依赖 saver，并返回 framework-neutral checkpoint view。"""

    saver = InMemorySaver()
    _persist_checkpoint(
        saver,
        lookup_task_id="task-reader-1",
        state_task_id="task-reader-1",
        phase=WorkflowPhase.RESOLVE_HOST_CONTEXT.value,
    )

    reader = LangGraphWorkflowCheckpointReader(checkpointer=saver)
    checkpoint = reader.get_checkpoint("task-reader-1")

    assert checkpoint == WorkflowCheckpointView(
        task_id="task-reader-1",
        phase=WorkflowPhase.RESOLVE_HOST_CONTEXT,
    )


def test_reader_returns_none_for_missing_task() -> None:
    """不存在的 root checkpoint 必须返回 None，不能创建 graph 或猜测任务状态。"""

    reader = LangGraphWorkflowCheckpointReader(checkpointer=InMemorySaver())

    assert reader.get_checkpoint("task-reader-missing") is None


def test_reader_preserves_checkpoint_invalid_for_corrupt_persisted_state() -> None:
    """损坏的持久化 state 必须继续归一成稳定的 WORKFLOW_CHECKPOINT_INVALID。"""

    saver = InMemorySaver()
    _persist_checkpoint(
        saver,
        lookup_task_id="task-reader-corrupt",
        state_task_id="task-reader-corrupt",
        phase="NOT_A_WORKFLOW_PHASE",
    )
    reader = LangGraphWorkflowCheckpointReader(checkpointer=saver)

    with pytest.raises(WorkflowStateError) as exc_info:
        reader.get_checkpoint("task-reader-corrupt")

    assert exc_info.value.code == "WORKFLOW_CHECKPOINT_INVALID"