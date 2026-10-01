"""Repository-owned minimal Product Front Door reference client。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import Protocol, TextIO
from uuid import uuid4

from design_orchestrator import PendingInteractionKind, PendingInteractionView
from design_product_runtime import ProductTaskQueryState, ProductTaskQueryView

from .agent import AgentClarificationRequired
from .sqlite_state import FrozenSubmission, SubmissionRecord

_CORRELATION_NOT_FOUND = "FRONT_DOOR_CORRELATION_NOT_FOUND"
_LINEAGE_INVALID = "FRONT_DOOR_CLIENT_LINEAGE_INVALID"
_DELIVERY_ACKNOWLEDGED = "ACKNOWLEDGED"


class HumanDecisionPort(Protocol):
    """模型之外的显式人类决定边界。"""

    def decide(self, pending: PendingInteractionView) -> str:
        """针对 owner-derived pending interaction 返回一个显式 resume kind。"""

        ...


class ReferenceClient:
    """编排 durable correlation、真实 MCP 与显式 HITL；不拥有业务执行真相。"""

    def __init__(
        self,
        *,
        state_store: object,
        submission_controller: object,
        mcp_client: object,
        human_decision_port: HumanDecisionPort,
    ) -> None:
        """注入全部 client-side seam；reference client 不创建隐藏 singleton。"""

        for method_name in (
            "create_submission",
            "get_submission",
            "mark_delivery",
        ):
            if not callable(getattr(state_store, method_name, None)):
                raise TypeError(f"state_store must provide callable {method_name}")
        if not callable(getattr(submission_controller, "prepare_submission", None)):
            raise TypeError("submission_controller must provide prepare_submission")
        for method_name in (
            "submit",
            "get",
            "resume_operation_proposal",
        ):
            if not callable(getattr(mcp_client, method_name, None)):
                raise TypeError(f"mcp_client must provide callable {method_name}")
        if not callable(getattr(human_decision_port, "decide", None)):
            raise TypeError("human_decision_port must provide decide")

        self._state_store = state_store
        self._submission_controller = submission_controller
        self._mcp_client = mcp_client
        self._human_decision_port = human_decision_port

    async def run_submission(
        self,
        *,
        client_submission_ref: str,
        utterance: str | None = None,
    ) -> ProductTaskQueryView | AgentClarificationRequired:
        """恢复/冻结一个 correlation，经 MCP 提交并在 exact pending 上执行显式 human resume。"""

        normalized_ref = self._require_nonblank(
            client_submission_ref,
            "client_submission_ref",
        )
        resolved_utterance = self._resolve_utterance(
            client_submission_ref=normalized_ref,
            utterance=utterance,
        )

        prepared = self._submission_controller.prepare_submission(
            client_submission_ref=normalized_ref,
            utterance=resolved_utterance,
        )
        if isinstance(prepared, AgentClarificationRequired):
            return prepared
        if not isinstance(prepared, FrozenSubmission):
            raise TypeError(
                "submission_controller must return FrozenSubmission or "
                "AgentClarificationRequired"
            )

        # frozen request 已经 durable 后才允许首次/重送 MCP；异常时保持 DELIVERY_PENDING，
        # 让下一个进程继续发送同一个 exact winner。
        submitted = await self._mcp_client.submit(prepared.request)
        self._require_exact_view(prepared, submitted, "submit")
        self._state_store.mark_delivery(normalized_ref, _DELIVERY_ACKNOWLEDGED)

        pending = self._pending_interaction(submitted)
        if pending is None:
            # ACCEPTED_PRE_WORKFLOW、terminal、recovery/failed 等 owner 状态原样返回；
            # transport 完成绝不被 reference client 投影成业务成功。
            return submitted

        decision = self._human_decision_port.decide(pending)
        if not isinstance(decision, str) or decision not in pending.allowed_resume_kinds:
            raise ValueError(
                "human decision must be one of pending_interaction.allowed_resume_kinds"
            )

        resumed = await self._mcp_client.resume_operation_proposal(
            task_id=prepared.request.task_id,
            pause_id=pending.pause_id,
            resume_kind=decision,
        )
        self._require_exact_view(prepared, resumed, "resume")

        # resume 返回只是该调用后的 owner 投影；最终呈现再次按 exact same task 查询，
        # 避免把 transport completion 或 callback 返回值当成第二份 outcome truth。
        queried = await self._mcp_client.get(prepared.request.task_id)
        if queried is None:
            raise ValueError(f"{_LINEAGE_INVALID}: resumed task disappeared from exact query")
        self._require_exact_view(prepared, queried, "get")
        return queried

    def _resolve_utterance(
        self,
        *,
        client_submission_ref: str,
        utterance: str | None,
    ) -> str:
        """首次调用先持久化文本；恢复调用从 durable SubmissionRecord 读取原始文本。"""

        if utterance is not None:
            if not isinstance(utterance, str):
                raise TypeError("utterance must be a string or None")
            # 这一步故意发生在模型调用之前：同 correlation + 新 utterance 必须先冲突，
            # 不能让模型看见一份最终不会属于该 correlation 的新文本。
            record = self._state_store.create_submission(
                client_submission_ref,
                utterance,
            )
            return self._record_utterance(record)

        record = self._state_store.get_submission(client_submission_ref)
        if record is None:
            raise ValueError(
                f"{_CORRELATION_NOT_FOUND}: recovery requires an existing submission"
            )
        return self._record_utterance(record)

    @staticmethod
    def _record_utterance(record: object) -> str:
        """只接受既有 SQLite owner 的 SubmissionRecord，不从 frozen payload 反推文本。"""

        if not isinstance(record, SubmissionRecord):
            raise TypeError("state_store must return SubmissionRecord")
        if not isinstance(record.utterance, str):
            raise TypeError("SubmissionRecord.utterance must be a string")
        return record.utterance

    @staticmethod
    def _pending_interaction(view: ProductTaskQueryView) -> PendingInteractionView | None:
        """只识别 workflow owner 当前公开的 Operation Proposal pending interaction。"""

        if view.state is not ProductTaskQueryState.WORKFLOW or view.flow is None:
            return None
        pending = view.flow.checkpoint.pending_interaction
        if pending is None:
            return None
        if pending.kind is not PendingInteractionKind.OPERATION_PROPOSAL:
            raise ValueError("reference client only supports OPERATION_PROPOSAL human resume")
        return pending

    @staticmethod
    def _require_exact_view(
        frozen: FrozenSubmission,
        view: object,
        operation: str,
    ) -> None:
        """所有 MCP 返回都必须继续属于 frozen winner 的同一 task/request lineage。"""

        if not isinstance(view, ProductTaskQueryView):
            raise TypeError(f"MCP {operation} must return ProductTaskQueryView")
        if (
            view.task_id != frozen.request.task_id
            or view.request_hash != frozen.request.request_hash
        ):
            raise ValueError(
                f"{_LINEAGE_INVALID}: MCP {operation} view does not match frozen request"
            )

    @staticmethod
    def _require_nonblank(value: object, field_name: str) -> str:
        """规范化 client-side locator 外围空白，拒绝空 correlation。"""

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-blank string")
        return value.strip()


def render_reference_result(
    result: ProductTaskQueryView | AgentClarificationRequired,
) -> str:
    """把 owner-derived 结果做最小用户呈现，不折叠或重新解释业务状态。"""

    if isinstance(result, AgentClarificationRequired):
        return f"CLARIFICATION_REQUIRED: {result.question}"
    if not isinstance(result, ProductTaskQueryView):
        raise TypeError(
            "reference result must be ProductTaskQueryView or AgentClarificationRequired"
        )
    if result.state is ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW:
        return f"{result.state.value} task_id={result.task_id}"
    if result.flow is None:
        raise ValueError("WORKFLOW reference result requires ProductFlowView")
    return f"{result.flow.status.value} task_id={result.task_id}"


def _default_submission_ref() -> str:
    """为一次新的显式 CLI submit 生成 opaque client delivery correlation。"""

    return f"submission-{uuid4()}"


def _build_reference_cli_parser() -> argparse.ArgumentParser:
    """构造最小 reference CLI；不声明模型 vendor、credential 或通用 MCP tool 参数。"""

    parser = argparse.ArgumentParser(prog="dsp-product-front-door")
    parser.add_argument(
        "--submission-ref",
        dest="submission_ref",
        help="恢复已有 client submission；省略时为新提交生成 correlation。",
    )
    parser.add_argument(
        "utterance",
        nargs="?",
        help="新提交的自然语言；恢复时可省略并从 durable state 读取。",
    )
    return parser


async def run_reference_cli(
    *,
    reference_client: ReferenceClient,
    argv: Sequence[str],
    submission_ref_factory: Callable[[], str] = _default_submission_ref,
    stdout: TextIO | None = None,
) -> ProductTaskQueryView | AgentClarificationRequired:
    """执行一次最小 CLI submit/recovery，并在任何模型/网络工作前公布 correlation。"""

    if not callable(getattr(reference_client, "run_submission", None)):
        raise TypeError("reference_client must provide run_submission")
    if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence):
        raise TypeError("argv must be a sequence of strings")
    if not callable(submission_ref_factory):
        raise TypeError("submission_ref_factory must be callable")

    args = _build_reference_cli_parser().parse_args(tuple(argv))
    if args.submission_ref is None:
        submission_ref = submission_ref_factory()
    else:
        submission_ref = args.submission_ref
    submission_ref = ReferenceClient._require_nonblank(
        submission_ref,
        "client_submission_ref",
    )

    output = sys.stdout if stdout is None else stdout
    if not callable(getattr(output, "write", None)) or not callable(
        getattr(output, "flush", None)
    ):
        raise TypeError("stdout must provide write and flush")

    # 这是恢复身份的用户可见 durable locator。必须在任何模型、Host probe 或 MCP 调用前
    # 单次写出并显式 flush，避免进程崩溃后用户连 correlation 都无法恢复。
    output.write(f"client_submission_ref={submission_ref}\n")
    output.flush()

    result = await reference_client.run_submission(
        client_submission_ref=submission_ref,
        utterance=args.utterance,
    )
    output.write(f"{render_reference_result(result)}\n")
    output.flush()
    return result


__all__ = [
    "HumanDecisionPort",
    "ReferenceClient",
    "render_reference_result",
    "run_reference_cli",
]
