"""Task 8：minimal reference CLI correlation ordering 与 owner-state presentation 契约。"""

from __future__ import annotations

import design_product_front_door as front_door
import pytest
from design_orchestrator import WorkflowCheckpointView, WorkflowPhase
from design_product_runtime import (
    ProductFlowStatus,
    ProductFlowView,
    ProductTaskQueryState,
    ProductTaskQueryView,
)


def _cli_seams():
    """延迟取得 Task 8 CLI seam；缺失时形成精确 TDD RED。"""

    run_cli = getattr(front_door, "run_reference_cli", None)
    render = getattr(front_door, "render_reference_result", None)
    assert run_cli is not None, "run_reference_cli 尚未实现"
    assert render is not None, "render_reference_result 尚未实现"
    return run_cli, render


def _accepted_view() -> ProductTaskQueryView:
    """构造 request 已持久化但 workflow 尚未开始的 owner-derived view。"""

    return ProductTaskQueryView(
        task_id="task-cli-001",
        request_hash="a" * 64,
        state=ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW,
        flow=None,
    )


def _workflow_view(status: ProductFlowStatus) -> ProductTaskQueryView:
    """构造指定 ProductFlowStatus 的同一 task owner projection。"""

    checkpoint = WorkflowCheckpointView(
        task_id="task-cli-001",
        phase=WorkflowPhase.COMPLETED,
    )
    return ProductTaskQueryView(
        task_id="task-cli-001",
        request_hash="a" * 64,
        state=ProductTaskQueryState.WORKFLOW,
        flow=ProductFlowView(status=status, checkpoint=checkpoint),
    )


class _RecordingOutput:
    """记录 write/flush 次序，证明 correlation 在模型/网络工作前已对用户可见。"""

    def __init__(self, events: list[tuple[str, str | None]]) -> None:
        self._events = events

    def write(self, value: str) -> int:
        """记录完整输出片段；返回长度以满足 TextIO 最小协议。"""

        self._events.append(("write", value))
        return len(value)

    def flush(self) -> None:
        """显式记录 flush；CLI 必须在调用 reference client 前完成一次 flush。"""

        self._events.append(("flush", None))


class _CliReferenceClient:
    """只记录 CLI 传入的 correlation/utterance，并返回确定 owner view。"""

    def __init__(
        self,
        *,
        events: list[tuple[str, str | None]],
        result: ProductTaskQueryView | front_door.AgentClarificationRequired,
    ) -> None:
        self._events = events
        self._result = result
        self.calls: list[tuple[str, str | None]] = []

    async def run_submission(
        self,
        *,
        client_submission_ref: str,
        utterance: str | None = None,
    ):
        """断言 correlation 已经 write+flush 后才允许进入模型/网络编排。"""

        self._events.append(("client", client_submission_ref))
        self.calls.append((client_submission_ref, utterance))
        return self._result


@pytest.mark.asyncio
async def test_cli_generates_and_flushes_submission_ref_before_reference_client_work() -> None:
    """新提交先生成、打印并 flush correlation，再允许模型/MCP 路径开始。"""

    run_cli, _ = _cli_seams()
    events: list[tuple[str, str | None]] = []
    output = _RecordingOutput(events)
    client = _CliReferenceClient(events=events, result=_accepted_view())

    result = await run_cli(
        reference_client=client,
        argv=["把 primary-revit 当前选中的墙厚改成 300mm。"],
        submission_ref_factory=lambda: "submission-cli-generated",
        stdout=output,
    )

    assert result.state is ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW
    assert client.calls == [
        (
            "submission-cli-generated",
            "把 primary-revit 当前选中的墙厚改成 300mm。",
        )
    ]
    client_index = events.index(("client", "submission-cli-generated"))
    assert ("write", "client_submission_ref=submission-cli-generated\n") in events[:client_index]
    assert ("flush", None) in events[:client_index]


@pytest.mark.asyncio
async def test_cli_recovery_uses_explicit_submission_ref_without_synthetic_utterance() -> None:
    """--submission-ref recovery 允许省略 utterance，让 ReferenceClient 从 SQLite owner 恢复。"""

    run_cli, _ = _cli_seams()
    events: list[tuple[str, str | None]] = []
    client = _CliReferenceClient(events=events, result=_accepted_view())

    await run_cli(
        reference_client=client,
        argv=["--submission-ref", "submission-cli-existing"],
        submission_ref_factory=lambda: (_ for _ in ()).throw(
            AssertionError("explicit recovery must not generate a new correlation")
        ),
        stdout=_RecordingOutput(events),
    )

    assert client.calls == [("submission-cli-existing", None)]


@pytest.mark.asyncio
async def test_cli_does_not_embed_model_vendor_credential_options() -> None:
    """reference CLI 不拥有模型 vendor credentials；未知 credential flag 必须被 parser 拒绝。"""

    run_cli, _ = _cli_seams()
    events: list[tuple[str, str | None]] = []
    client = _CliReferenceClient(events=events, result=_accepted_view())

    with pytest.raises(SystemExit):
        await run_cli(
            reference_client=client,
            argv=["--api-key", "secret", "修改墙厚。"],
            submission_ref_factory=lambda: "submission-never-used",
            stdout=_RecordingOutput(events),
        )

    assert client.calls == []
    assert events == []


def test_presentation_keeps_accepted_pre_workflow_distinct_from_success() -> None:
    """request-only durable fact 必须明确呈现 ACCEPTED_PRE_WORKFLOW，而不是 transport success。"""

    _, render = _cli_seams()
    assert render(_accepted_view()) == "ACCEPTED_PRE_WORKFLOW task_id=task-cli-001"


@pytest.mark.parametrize(
    "status",
    [
        ProductFlowStatus.WAITING,
        ProductFlowStatus.RECOVERY_REQUIRED,
        ProductFlowStatus.CANCELLED,
        ProductFlowStatus.SUCCEEDED,
        ProductFlowStatus.FAILED,
        ProductFlowStatus.PARTIALLY_COMMITTED,
        ProductFlowStatus.DIVERGED,
    ],
)
def test_presentation_preserves_each_authoritative_workflow_status(
    status: ProductFlowStatus,
) -> None:
    """CLI 直接呈现 owner status 闭集，不把失败/恢复/部分提交折叠成成功。"""

    _, render = _cli_seams()
    assert render(_workflow_view(status)) == f"{status.value} task_id=task-cli-001"


def test_presentation_keeps_clarification_outside_product_task_status() -> None:
    """模型澄清仍是 pre-ProductTask 用户交互，不伪造 task outcome。"""

    _, render = _cli_seams()
    clarification = front_door.AgentClarificationRequired(question="请补充目标厚度。")
    assert render(clarification) == "CLARIFICATION_REQUIRED: 请补充目标厚度。"
