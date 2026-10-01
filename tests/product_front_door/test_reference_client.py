"""Task 8：repository-owned minimal reference client durable recovery / HITL 契约测试。"""

from __future__ import annotations

from pathlib import Path

import design_product_front_door as front_door
import pytest
from design_changeset import canonical_hash
from design_orchestrator import (
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
)
from design_product_runtime import (
    ProductFlowStatus,
    ProductFlowView,
    ProductTaskQueryState,
    ProductTaskQueryView,
)
from revit_sidecar import RevitContextObservation, RevitSelectedElement


def _reference_types():
    """延迟取得 Task 8 reference-client 类型，使缺实现时只形成明确 TDD RED。"""

    reference_type = getattr(front_door, "ReferenceClient", None)
    human_port = getattr(front_door, "HumanDecisionPort", None)
    assert reference_type is not None, "ReferenceClient 尚未实现"
    assert human_port is not None, "HumanDecisionPort 尚未实现"
    return reference_type, human_port


class _ProposalInterpreter:
    """严格只接受 correlation + utterance；多传 MCP endpoint/tool metadata 会直接 TypeError。"""

    def __init__(self, proposal) -> None:
        self._proposal = proposal
        self.calls: list[tuple[str, str]] = []

    def interpret(self, *, client_submission_ref: str, utterance: str):
        """记录模型实际输入并返回固定窄 proposal。"""

        self.calls.append((client_submission_ref, utterance))
        return self._proposal


class _ClarifyingInterpreter:
    """返回固定澄清问题，证明澄清不会越过 ProductTask/MCP 边界。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def interpret(self, *, client_submission_ref: str, utterance: str):
        """只读取 durable utterance，不产生 proposal。"""

        self.calls.append((client_submission_ref, utterance))
        return front_door.AgentClarificationRequired(
            question="请明确要把 primary-revit 当前选中的墙改成多少毫米。"
        )


class _ForbiddenInterpreter:
    """freeze 后 restart 若再次调用模型，测试立即失败。"""

    def interpret(self, *, client_submission_ref: str, utterance: str):
        """禁止已冻结 correlation 重新解释自然语言。"""

        raise AssertionError(
            f"frozen restart must not reinterpret {client_submission_ref=} {utterance=}"
        )


class _CandidateSource:
    """只按 exact configured key 返回一个 immutable candidate。"""

    def __init__(self, candidate) -> None:
        self._candidate = candidate

    def get(self, candidate_key: str):
        """未知 key 明确返回 None，不提供 fuzzy/latest fallback。"""

        if candidate_key != self._candidate.candidate_key:
            return None
        return self._candidate


class _ForbiddenCandidateSource:
    """freeze 后 recovery/clarification 路径不得重新解析 candidate authority。"""

    def get(self, candidate_key: str):
        """任何访问都代表 reference-client recovery 边界发生回退。"""

        raise AssertionError(f"must not resolve candidate after freeze: {candidate_key}")


class _Probe:
    """返回固定 fresh Revit runtime/document/selection evidence。"""

    def __init__(self, observation: RevitContextObservation) -> None:
        self._observation = observation

    def discover(self, *, command_id: str, document_id: str):
        """校验 controller 仍按 configured document 做 fresh probe。"""

        assert command_id
        assert document_id == self._observation.document_id
        return self._observation


class _ProbeFactory:
    """为 configured transport locator 创建一个窄 context probe。"""

    def __init__(self, observation: RevitContextObservation) -> None:
        self._observation = observation

    def __call__(self, transport_locator: str):
        """locator 只用于连接定位，不被当作 runtime identity。"""

        assert transport_locator == "revit-pipe-001"
        return _Probe(self._observation)


def _forbidden_probe_factory(*args, **kwargs):
    """freeze 后 recovery/clarification 不得访问 Host。"""

    del args, kwargs
    raise AssertionError("path must not create Host probe")


def _forbidden_identity_factory() -> str:
    """freeze 后 recovery/clarification 不得分配新的 task/session identity。"""

    raise AssertionError("path must not allocate business identity")


class _FixedFactory:
    """返回确定 identity，便于重启前后比较 exact frozen request。"""

    def __init__(self, value: str) -> None:
        self._value = value

    def __call__(self) -> str:
        """返回固定 opaque identity。"""

        return self._value


def _candidate():
    """构造通过 canonical candidate hash 完整性校验的配置候选。"""

    fields = {
        "candidate_key": "primary-revit",
        "project_id": "project-001",
        "transport_locator": "revit-pipe-001",
        "document_id": r"C:\DSP\fixtures\front-door.rvt",
        "semantic_target_id": "WALL-001",
        "native_target_unique_id": "wall-native-001",
    }
    return front_door.ConfiguredRevitCandidate(
        **fields,
        candidate_hash=canonical_hash(
            front_door.configured_revit_candidate_hash_body(**fields)
        ),
    )


def _observation() -> RevitContextObservation:
    """构造恰好选中 configured Wall 的 fresh Host evidence。"""

    return RevitContextObservation(
        document_id=r"C:\DSP\fixtures\front-door.rvt",
        document_title="front-door.rvt",
        host_instance_id="revit-runtime-001",
        revision=31,
        selected_elements=(
            RevitSelectedElement(
                unique_id="wall-native-001",
                native_kind="Wall",
            ),
        ),
    )


def _proposal():
    """返回 Task 8 当前唯一支持的窄 wall-thickness proposal。"""

    return front_door.AgentProposal(
        candidate_key="primary-revit",
        thickness_value=300.0,
        thickness_unit="mm",
    )


def _controller(*, store, interpreter, frozen_recovery: bool = False):
    """按测试场景组装真实 SubmissionController，不复制 correlation/freeze 逻辑。"""

    if frozen_recovery:
        return front_door.SubmissionController(
            state_store=store,
            agent_interpreter=interpreter,
            candidate_source=_ForbiddenCandidateSource(),
            context_probe_factory=_forbidden_probe_factory,
            session_ref_factory=_forbidden_identity_factory,
            task_id_factory=_forbidden_identity_factory,
        )
    return front_door.SubmissionController(
        state_store=store,
        agent_interpreter=interpreter,
        candidate_source=_CandidateSource(_candidate()),
        context_probe_factory=_ProbeFactory(_observation()),
        session_ref_factory=_FixedFactory("session-reference-client-001"),
        task_id_factory=_FixedFactory("task-reference-client-001"),
    )


def _accepted_view(request) -> ProductTaskQueryView:
    """表示 server 已持久化 request 但尚无 checkpoint；transport 完成不能伪造成功。"""

    return ProductTaskQueryView(
        task_id=request.task_id,
        request_hash=request.request_hash,
        state=ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW,
        flow=None,
    )


def _pending_view(request) -> ProductTaskQueryView:
    """构造 owner-derived Operation Proposal pending interaction。"""

    pending = PendingInteractionView(
        pause_id="pause-reference-client-001",
        kind=PendingInteractionKind.OPERATION_PROPOSAL,
        subject_ref=StableRef(
            ref_id="operation-reference-client-001",
            content_hash="1" * 64,
        ),
        allowed_resume_kinds=(
            "OPERATION_PROPOSAL_ACCEPTED",
            "OPERATION_PROPOSAL_REJECTED",
        ),
    )
    checkpoint = WorkflowCheckpointView(
        task_id=request.task_id,
        phase=WorkflowPhase.AWAIT_OPERATION_PROPOSAL,
        pending_interaction=pending,
    )
    return ProductTaskQueryView(
        task_id=request.task_id,
        request_hash=request.request_hash,
        state=ProductTaskQueryState.WORKFLOW,
        flow=ProductFlowView(
            status=ProductFlowStatus.WAITING,
            checkpoint=checkpoint,
        ),
    )


def _terminal_view(request) -> ProductTaskQueryView:
    """构造同一 task 的 authoritative terminal projection。"""

    checkpoint = WorkflowCheckpointView(
        task_id=request.task_id,
        phase=WorkflowPhase.COMPLETED,
    )
    return ProductTaskQueryView(
        task_id=request.task_id,
        request_hash=request.request_hash,
        state=ProductTaskQueryState.WORKFLOW,
        flow=ProductFlowView(
            status=ProductFlowStatus.SUCCEEDED,
            checkpoint=checkpoint,
        ),
    )


class _ResponseLostMcpClient:
    """模拟 server 已受理 submit，但 response 在 client 收到前丢失。"""

    endpoint_url = "http://127.0.0.1:8010/mcp"

    def __init__(self) -> None:
        self.submitted: list[object] = []

    async def submit(self, request):
        """先记录 server 已收到的 exact request，再模拟 response loss。"""

        self.submitted.append(request)
        raise ConnectionError("simulated MCP response loss after server acceptance")

    async def get(self, task_id: str):
        """该场景不应进入 get。"""

        raise AssertionError(f"response-loss first attempt must not get: {task_id}")

    async def resume_operation_proposal(self, **kwargs):
        """该场景不应进入 HITL resume。"""

        raise AssertionError(f"response-loss first attempt must not resume: {kwargs}")


class _AcceptedMcpClient:
    """记录 exact submit，并返回 request-only durable fact。"""

    endpoint_url = "http://127.0.0.1:8010/mcp"

    def __init__(self) -> None:
        self.submitted: list[object] = []
        self.get_calls: list[str] = []

    async def submit(self, request):
        """返回 ACCEPTED_PRE_WORKFLOW，不把网络成功解释为产品成功。"""

        self.submitted.append(request)
        return _accepted_view(request)

    async def get(self, task_id: str):
        """若 reference client 做 exact read-back，仍返回同一 durable fact。"""

        self.get_calls.append(task_id)
        request = self.submitted[-1]
        assert task_id == request.task_id
        return _accepted_view(request)

    async def resume_operation_proposal(self, **kwargs):
        """request-only 场景没有 pending human interaction。"""

        raise AssertionError(f"must not resume without pending interaction: {kwargs}")


class _HumanFlowMcpClient:
    """返回 owner pending interaction，并记录 deterministic resume/get 顺序。"""

    endpoint_url = "http://127.0.0.1:8010/mcp"

    def __init__(self) -> None:
        self.submitted: list[object] = []
        self.resume_calls: list[dict[str, str]] = []
        self.get_calls: list[str] = []

    async def submit(self, request):
        """第一次 submit 到达 exact Operation Proposal pause。"""

        self.submitted.append(request)
        return _pending_view(request)

    async def resume_operation_proposal(
        self,
        *,
        task_id: str,
        pause_id: str,
        resume_kind: str,
    ):
        """记录 controller-only human resume，并返回 terminal owner view。"""

        self.resume_calls.append(
            {
                "task_id": task_id,
                "pause_id": pause_id,
                "resume_kind": resume_kind,
            }
        )
        request = self.submitted[-1]
        return _terminal_view(request)

    async def get(self, task_id: str):
        """resume 后只按 exact same task 做最终 read-back。"""

        self.get_calls.append(task_id)
        request = self.submitted[-1]
        assert task_id == request.task_id
        return _terminal_view(request)


class _ForbiddenMcpClient:
    """clarification/conflict 路径只要触碰 MCP 就立即失败。"""

    endpoint_url = "http://127.0.0.1:8010/mcp"

    async def submit(self, request):
        """禁止 clarification/conflict 产生 ProductTask send。"""

        raise AssertionError(f"path must not submit MCP request: {request}")

    async def get(self, task_id: str):
        """禁止 clarification/conflict 做 task query。"""

        raise AssertionError(f"path must not get MCP task: {task_id}")

    async def resume_operation_proposal(self, **kwargs):
        """禁止 clarification/conflict 做 human resume。"""

        raise AssertionError(f"path must not resume MCP task: {kwargs}")


class _ForbiddenHumanDecision:
    """没有 owner pending interaction 时不得请求人类决定。"""

    def decide(self, pending: PendingInteractionView) -> str:
        """任何调用都代表 reference client 虚构了 HITL。"""

        raise AssertionError(f"must not request human decision: {pending}")


class _AcceptHumanDecision:
    """记录显式 owner-derived pending interaction，并返回允许的 accept 事件。"""

    def __init__(self) -> None:
        self.pending: list[PendingInteractionView] = []

    def decide(self, pending: PendingInteractionView) -> str:
        """只接受真实 PendingInteractionView；模型不参与此方法。"""

        assert isinstance(pending, PendingInteractionView)
        self.pending.append(pending)
        return "OPERATION_PROPOSAL_ACCEPTED"


def _reference_client(*, store, controller, mcp_client, human_decision):
    """按 Task 8 最小依赖组装 reference client。"""

    reference_type, _ = _reference_types()
    return reference_type(
        state_store=store,
        submission_controller=controller,
        mcp_client=mcp_client,
        human_decision_port=human_decision,
    )


@pytest.mark.asyncio
async def test_response_loss_after_freeze_reopens_sqlite_and_resends_exact_request(
    tmp_path: Path,
) -> None:
    """server 接受后丢 response；进程重启只重送 durable winner，绝不重新调用模型。"""

    _reference_types()
    db_path = tmp_path / "front-door.sqlite3"
    first_store = front_door.SqliteFrontDoorStateStore(str(db_path))
    first_interpreter = _ProposalInterpreter(_proposal())
    first_mcp = _ResponseLostMcpClient()
    first = _reference_client(
        store=first_store,
        controller=_controller(store=first_store, interpreter=first_interpreter),
        mcp_client=first_mcp,
        human_decision=_ForbiddenHumanDecision(),
    )
    utterance = "把 primary-revit 当前选中的墙厚改成 300mm。"

    try:
        with pytest.raises(ConnectionError, match="response loss"):
            await first.run_submission(
                client_submission_ref="submission-response-loss",
                utterance=utterance,
            )
        frozen = first_store.get_frozen_submission("submission-response-loss")
        assert frozen is not None
        assert frozen.delivery_state == "DELIVERY_PENDING"
        assert len(first_mcp.submitted) == 1
        assert first_mcp.submitted[0] == frozen.request
    finally:
        first_store.close()

    reopened_store = front_door.SqliteFrontDoorStateStore(str(db_path))
    recovery_mcp = _AcceptedMcpClient()
    recovery = _reference_client(
        store=reopened_store,
        controller=_controller(
            store=reopened_store,
            interpreter=_ForbiddenInterpreter(),
            frozen_recovery=True,
        ),
        mcp_client=recovery_mcp,
        human_decision=_ForbiddenHumanDecision(),
    )
    try:
        result = await recovery.run_submission(
            client_submission_ref="submission-response-loss",
            utterance=None,
        )
        assert result.state is ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW
        assert len(recovery_mcp.submitted) == 1
        replayed = recovery_mcp.submitted[0]
        assert replayed == first_mcp.submitted[0]
        assert replayed.task_id == frozen.request.task_id
        assert replayed.session_ref == frozen.request.session_ref
        assert replayed.request_hash == frozen.request.request_hash

        durable = reopened_store.get_frozen_submission("submission-response-loss")
        assert durable is not None
        assert durable.delivery_state == "ACKNOWLEDGED"
    finally:
        reopened_store.close()


@pytest.mark.asyncio
async def test_restart_before_freeze_reloads_stored_utterance_and_may_reinterpret(
    tmp_path: Path,
) -> None:
    """UNFROZEN 重启从 SQLite 读取原始 utterance；不要求 caller 重复提供文本。"""

    _reference_types()
    db_path = tmp_path / "front-door.sqlite3"
    original_store = front_door.SqliteFrontDoorStateStore(str(db_path))
    utterance = "把 primary-revit 当前选中的墙厚改成 300mm。"
    original_store.create_submission("submission-unfrozen", utterance)
    original_store.close()

    reopened = front_door.SqliteFrontDoorStateStore(str(db_path))
    interpreter = _ProposalInterpreter(_proposal())
    mcp_client = _AcceptedMcpClient()
    client = _reference_client(
        store=reopened,
        controller=_controller(store=reopened, interpreter=interpreter),
        mcp_client=mcp_client,
        human_decision=_ForbiddenHumanDecision(),
    )
    try:
        result = await client.run_submission(
            client_submission_ref="submission-unfrozen",
            utterance=None,
        )
        assert result.state is ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW
        assert interpreter.calls == [("submission-unfrozen", utterance)]
        assert len(mcp_client.submitted) == 1
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_restart_before_freeze_rejects_same_ref_with_new_utterance(
    tmp_path: Path,
) -> None:
    """同一 durable correlation 不能在 recovery 时被新 utterance 改写。"""

    _reference_types()
    store = front_door.SqliteFrontDoorStateStore(str(tmp_path / "front-door.sqlite3"))
    store.create_submission("submission-conflict", "原始请求。")
    interpreter = _ProposalInterpreter(_proposal())
    client = _reference_client(
        store=store,
        controller=_controller(store=store, interpreter=interpreter),
        mcp_client=_ForbiddenMcpClient(),
        human_decision=_ForbiddenHumanDecision(),
    )
    try:
        with pytest.raises(ValueError, match="FRONT_DOOR_CORRELATION_CONFLICT"):
            await client.run_submission(
                client_submission_ref="submission-conflict",
                utterance="不同的新请求。",
            )
        assert interpreter.calls == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_clarification_returns_to_user_without_mcp_submit(tmp_path: Path) -> None:
    """CLARIFICATION_REQUIRED 保持 UNFROZEN，不分配 ProductTask，也不触发 MCP/HITL。"""

    _reference_types()
    store = front_door.SqliteFrontDoorStateStore(str(tmp_path / "front-door.sqlite3"))
    interpreter = _ClarifyingInterpreter()
    controller = front_door.SubmissionController(
        state_store=store,
        agent_interpreter=interpreter,
        candidate_source=_ForbiddenCandidateSource(),
        context_probe_factory=_forbidden_probe_factory,
        session_ref_factory=_forbidden_identity_factory,
        task_id_factory=_forbidden_identity_factory,
    )
    client = _reference_client(
        store=store,
        controller=controller,
        mcp_client=_ForbiddenMcpClient(),
        human_decision=_ForbiddenHumanDecision(),
    )
    try:
        result = await client.run_submission(
            client_submission_ref="submission-clarify",
            utterance="把墙改厚一点。",
        )
        assert isinstance(result, front_door.AgentClarificationRequired)
        record = store.get_submission("submission-clarify")
        assert record is not None
        assert record.state is front_door.SubmissionState.UNFROZEN
        assert record.frozen is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_only_human_port_receives_pending_and_controller_calls_exact_resume(
    tmp_path: Path,
) -> None:
    """模型只解释自然语言；owner pending 只交给 HumanDecisionPort，再由确定代码 resume。"""

    _reference_types()
    store = front_door.SqliteFrontDoorStateStore(str(tmp_path / "front-door.sqlite3"))
    interpreter = _ProposalInterpreter(_proposal())
    mcp_client = _HumanFlowMcpClient()
    human = _AcceptHumanDecision()
    client = _reference_client(
        store=store,
        controller=_controller(store=store, interpreter=interpreter),
        mcp_client=mcp_client,
        human_decision=human,
    )
    utterance = "把 primary-revit 当前选中的墙厚改成 300mm。"

    try:
        result = await client.run_submission(
            client_submission_ref="submission-human",
            utterance=utterance,
        )
        assert interpreter.calls == [("submission-human", utterance)]
        assert len(human.pending) == 1
        pending = human.pending[0]
        assert pending.pause_id == "pause-reference-client-001"
        assert pending.kind is PendingInteractionKind.OPERATION_PROPOSAL
        assert mcp_client.resume_calls == [
            {
                "task_id": "task-reference-client-001",
                "pause_id": "pause-reference-client-001",
                "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
            }
        ]
        assert mcp_client.get_calls == ["task-reference-client-001"]
        assert result.flow is not None
        assert result.flow.status is ProductFlowStatus.SUCCEEDED
    finally:
        store.close()


@pytest.mark.asyncio
async def test_transport_success_preserves_accepted_pre_workflow_presentation(
    tmp_path: Path,
) -> None:
    """MCP submit 返回并不等于业务成功；ACCEPTED_PRE_WORKFLOW 必须原样呈现。"""

    _reference_types()
    store = front_door.SqliteFrontDoorStateStore(str(tmp_path / "front-door.sqlite3"))
    mcp_client = _AcceptedMcpClient()
    client = _reference_client(
        store=store,
        controller=_controller(
            store=store,
            interpreter=_ProposalInterpreter(_proposal()),
        ),
        mcp_client=mcp_client,
        human_decision=_ForbiddenHumanDecision(),
    )
    try:
        result = await client.run_submission(
            client_submission_ref="submission-accepted",
            utterance="把 primary-revit 当前选中的墙厚改成 300mm。",
        )
        assert result.state is ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW
        assert result.flow is None
    finally:
        store.close()
