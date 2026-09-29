"""Task 4：SubmissionController correlation / clarification / atomic freeze 契约测试。"""

from __future__ import annotations

import threading
from pathlib import Path

import design_product_front_door as front_door
import pytest
from design_changeset import canonical_hash
from revit_sidecar import RevitContextObservation, RevitSelectedElement


def _controller_types():
    """延迟取得 Task 4 controller/agent 类型，使尚未实现时形成明确 RED。"""

    controller_type = getattr(front_door, "SubmissionController", None)
    clarification_type = getattr(front_door, "AgentClarificationRequired", None)
    assert controller_type is not None, "SubmissionController 尚未实现"
    assert clarification_type is not None, "AgentClarificationRequired 尚未实现"
    return controller_type, clarification_type


def _freeze_types():
    """取得 freeze/replay 所需公共类型；缺失时保持 TDD RED。"""

    proposal_type = getattr(front_door, "AgentProposal", None)
    frozen_type = getattr(front_door, "FrozenSubmission", None)
    reader_type = getattr(front_door, "SqliteSessionBindingReader", None)
    assert proposal_type is not None, "AgentProposal 尚未实现"
    assert frozen_type is not None, "FrozenSubmission 尚未实现"
    assert reader_type is not None, "SqliteSessionBindingReader 尚未实现"
    return proposal_type, frozen_type, reader_type


class _ClarifyingInterpreter:
    """只返回澄清问题，并记录 controller 实际传入的 durable utterance。"""

    def __init__(self, clarification_type) -> None:
        self._clarification_type = clarification_type
        self.calls: list[tuple[str, str]] = []

    def interpret(self, *, client_submission_ref: str, utterance: str):
        """返回用户可见澄清，不生成 proposal 或业务 identity。"""

        self.calls.append((client_submission_ref, utterance))
        return self._clarification_type(question="请确认要修改哪一个已配置的 Revit 候选？")


class _ProposalInterpreter:
    """返回固定规范 proposal；可用 barrier 强制两个 controller 同时进入 freeze 前阶段。"""

    def __init__(self, proposal, barrier: threading.Barrier | None = None) -> None:
        self._proposal = proposal
        self._barrier = barrier
        self.calls: list[tuple[str, str]] = []

    def interpret(self, *, client_submission_ref: str, utterance: str):
        """记录调用后返回固定 proposal。"""

        self.calls.append((client_submission_ref, utterance))
        if self._barrier is not None:
            self._barrier.wait(timeout=10)
        return self._proposal


class _ForbiddenInterpreter:
    """冻结后 replay 若再次解释自然语言，测试立即失败。"""

    def interpret(self, *, client_submission_ref: str, utterance: str):
        """禁止 frozen replay 重新调用模型。"""

        raise AssertionError(
            f"frozen replay must not reinterpret: {client_submission_ref=} {utterance=}"
        )


class _ForbiddenCandidateSource:
    """clarification/replay 路径若访问 candidate authority，测试必须立即失败。"""

    def get(self, candidate_key: str):
        """禁止不应继续的路径解析 candidate。"""

        raise AssertionError(f"path must not resolve candidate: {candidate_key}")


class _CandidateSource:
    """只按 exact key 返回一个 immutable configured candidate。"""

    def __init__(self, candidate) -> None:
        self._candidate = candidate
        self.calls: list[str] = []

    def get(self, candidate_key: str):
        """未知 key 返回 None，不提供 fuzzy/latest fallback。"""

        self.calls.append(candidate_key)
        if candidate_key != self._candidate.candidate_key:
            return None
        return self._candidate


class _Probe:
    """返回固定 fresh Host observation，并校验 controller 请求的是配置文档。"""

    def __init__(self, observation: RevitContextObservation) -> None:
        self._observation = observation
        self.calls: list[tuple[str, str]] = []

    def discover(self, *, command_id: str, document_id: str) -> RevitContextObservation:
        """记录 discovery，并返回已验证的 fresh runtime/document evidence。"""

        self.calls.append((command_id, document_id))
        assert document_id == self._observation.document_id
        return self._observation


class _ProbeFactory:
    """按 transport locator 创建一次 probe；locator 仅用于连接定位。"""

    def __init__(self, observation: RevitContextObservation) -> None:
        self._observation = observation
        self.calls: list[str] = []
        self.probes: list[_Probe] = []

    def __call__(self, transport_locator: str) -> _Probe:
        """记录 locator 并返回 fresh probe。"""

        self.calls.append(transport_locator)
        probe = _Probe(self._observation)
        self.probes.append(probe)
        return probe


def _forbidden_probe_factory(*args, **kwargs):
    """clarification/frozen replay 路径不得创建或调用 Host probe。"""

    del args, kwargs
    raise AssertionError("path must not create a Host probe")


def _forbidden_identity_factory() -> str:
    """clarification/frozen replay 路径不得分配 task_id/session_ref。"""

    raise AssertionError("path must not allocate business identity")


class _FixedIdentityFactory:
    """返回固定 tentative identity，并记录实际分配次数。"""

    def __init__(self, value: str) -> None:
        self._value = value
        self.calls = 0

    def __call__(self) -> str:
        """返回本 controller 的 tentative identity。"""

        self.calls += 1
        return self._value


def _candidate(
    *,
    native_target_unique_id: str = "wall-native-001",
    semantic_target_id: str = "WALL-001",
):
    """构造通过 Task 3 canonical hash 校验的 Revit candidate。"""

    fields = {
        "candidate_key": "primary-revit",
        "project_id": "project-001",
        "transport_locator": "revit-pipe-001",
        "document_id": r"C:\DSP\fixtures\front-door.rvt",
        "semantic_target_id": semantic_target_id,
        "native_target_unique_id": native_target_unique_id,
    }
    return front_door.ConfiguredRevitCandidate(
        **fields,
        candidate_hash=canonical_hash(
            front_door.configured_revit_candidate_hash_body(**fields)
        ),
    )


def _observation(*, native_target_unique_id: str = "wall-native-001") -> RevitContextObservation:
    """构造恰好选中一个 configured Wall 的 fresh Host evidence。"""

    return RevitContextObservation(
        document_id=r"C:\DSP\fixtures\front-door.rvt",
        document_title="front-door.rvt",
        host_instance_id="revit-runtime-001",
        revision=17,
        selected_elements=(
            RevitSelectedElement(
                unique_id=native_target_unique_id,
                native_kind="Wall",
            ),
        ),
    )


def _controller(
    *,
    store,
    interpreter,
    candidate,
    observation: RevitContextObservation,
    session_ref: str,
    task_id: str,
):
    """组装一个完整 deterministic controller 测试实例。"""

    controller_type, _ = _controller_types()
    session_factory = _FixedIdentityFactory(session_ref)
    task_factory = _FixedIdentityFactory(task_id)
    probe_factory = _ProbeFactory(observation)
    controller = controller_type(
        state_store=store,
        agent_interpreter=interpreter,
        candidate_source=_CandidateSource(candidate),
        context_probe_factory=probe_factory,
        session_ref_factory=session_factory,
        task_id_factory=task_factory,
    )
    return controller, session_factory, task_factory, probe_factory


def test_clarification_keeps_correlation_unfrozen_and_allocates_no_business_identity(
    tmp_path: Path,
) -> None:
    """CLARIFICATION_REQUIRED 只返回问题；不发布 binding/request，也不进入 delivery。"""

    controller_type, clarification_type = _controller_types()
    store = front_door.SqliteFrontDoorStateStore(str(tmp_path / "front-door.sqlite3"))
    interpreter = _ClarifyingInterpreter(clarification_type)
    controller = controller_type(
        state_store=store,
        agent_interpreter=interpreter,
        candidate_source=_ForbiddenCandidateSource(),
        context_probe_factory=_forbidden_probe_factory,
        session_ref_factory=_forbidden_identity_factory,
        task_id_factory=_forbidden_identity_factory,
    )
    utterance = "把墙改厚一点。"

    try:
        result = controller.prepare_submission(
            client_submission_ref="clarify-001",
            utterance=utterance,
        )

        assert isinstance(result, clarification_type)
        assert result.question == "请确认要修改哪一个已配置的 Revit 候选？"
        assert interpreter.calls == [("clarify-001", utterance)]

        record = store.get_submission("clarify-001")
        assert record is not None
        assert record.utterance == utterance
        assert record.state is front_door.SubmissionState.UNFROZEN
        assert record.frozen is None
        assert store.get_frozen_submission("clarify-001") is None
    finally:
        store.close()


def test_clarified_text_requires_new_explicit_correlation_instead_of_mutating_old_one(
    tmp_path: Path,
) -> None:
    """v1 澄清后的新 utterance 必须使用新 correlation；旧 correlation 的原始文本不可改写。"""

    controller_type, clarification_type = _controller_types()
    store = front_door.SqliteFrontDoorStateStore(str(tmp_path / "front-door.sqlite3"))
    interpreter = _ClarifyingInterpreter(clarification_type)
    controller = controller_type(
        state_store=store,
        agent_interpreter=interpreter,
        candidate_source=_ForbiddenCandidateSource(),
        context_probe_factory=_forbidden_probe_factory,
        session_ref_factory=_forbidden_identity_factory,
        task_id_factory=_forbidden_identity_factory,
    )

    try:
        controller.prepare_submission(
            client_submission_ref="clarify-original",
            utterance="把墙改厚一点。",
        )

        with pytest.raises(ValueError, match="FRONT_DOOR_CORRELATION_CONFLICT"):
            controller.prepare_submission(
                client_submission_ref="clarify-original",
                utterance="把 primary-revit 里的墙改成 300mm。",
            )

        original = store.get_submission("clarify-original")
        assert original is not None
        assert original.utterance == "把墙改厚一点。"
        assert original.state is front_door.SubmissionState.UNFROZEN
        assert original.frozen is None
    finally:
        store.close()


def test_same_correlation_replay_after_freeze_returns_exact_winner_without_new_work(
    tmp_path: Path,
) -> None:
    """冻结后的 callback 必须先读 winner，禁止重新解释、探测或分配 identity。"""

    proposal_type, frozen_type, _ = _freeze_types()
    db_path = tmp_path / "front-door.sqlite3"
    first_store = front_door.SqliteFrontDoorStateStore(str(db_path))
    proposal = proposal_type(
        candidate_key="primary-revit",
        thickness_value=300.0,
        thickness_unit="mm",
    )
    first_controller, _, _, _ = _controller(
        store=first_store,
        interpreter=_ProposalInterpreter(proposal),
        candidate=_candidate(),
        observation=_observation(),
        session_ref="session-winner",
        task_id="task-winner",
    )
    utterance = "把 primary-revit 当前选中的墙改成 300mm。"

    try:
        winner = first_controller.prepare_submission(
            client_submission_ref="replay-001",
            utterance=utterance,
        )
        assert isinstance(winner, frozen_type)
        assert winner.delivery_state == "DELIVERY_PENDING"
    finally:
        first_store.close()

    reopened = front_door.SqliteFrontDoorStateStore(str(db_path))
    controller_type, _ = _controller_types()
    replay_controller = controller_type(
        state_store=reopened,
        agent_interpreter=_ForbiddenInterpreter(),
        candidate_source=_ForbiddenCandidateSource(),
        context_probe_factory=_forbidden_probe_factory,
        session_ref_factory=_forbidden_identity_factory,
        task_id_factory=_forbidden_identity_factory,
    )
    try:
        replayed = replay_controller.prepare_submission(
            client_submission_ref="replay-001",
            utterance=utterance,
        )
        assert replayed == winner
        assert replayed.request.task_id == "task-winner"
        assert replayed.session_binding.session_ref == "session-winner"
    finally:
        reopened.close()


def test_two_sqlite_controllers_same_proposal_converge_on_one_frozen_winner(
    tmp_path: Path,
) -> None:
    """两个连接同时完成同一 proposal 时只发布一个 binding/request，loser 重读 winner。"""

    proposal_type, frozen_type, reader_type = _freeze_types()
    db_path = tmp_path / "front-door.sqlite3"
    bootstrap = front_door.SqliteFrontDoorStateStore(str(db_path))
    bootstrap.close()

    barrier = threading.Barrier(2)
    proposal = proposal_type(
        candidate_key="primary-revit",
        thickness_value=300.0,
        thickness_unit="mm",
    )
    results: list[object] = []
    errors: list[BaseException] = []

    def worker(label: str) -> None:
        """每个线程创建自己的 SQLite 连接，模拟两个独立 controller 进程。"""

        store = front_door.SqliteFrontDoorStateStore(str(db_path))
        try:
            controller, _, _, _ = _controller(
                store=store,
                interpreter=_ProposalInterpreter(proposal, barrier),
                candidate=_candidate(),
                observation=_observation(),
                session_ref=f"session-{label}",
                task_id=f"task-{label}",
            )
            results.append(
                controller.prepare_submission(
                    client_submission_ref="race-same-001",
                    utterance="把墙改成 300mm。",
                )
            )
        except BaseException as exc:  # noqa: BLE001 - 测试需要保留线程中的真实失败。
            errors.append(exc)
        finally:
            store.close()

    threads = [threading.Thread(target=worker, args=(label,)) for label in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    assert len(results) == 2
    assert all(isinstance(result, frozen_type) for result in results)
    assert results[0] == results[1]

    winner = results[0]
    assert winner.request.task_id in {"task-A", "task-B"}
    assert winner.session_binding.session_ref in {"session-A", "session-B"}

    reader = reader_type(str(db_path))
    try:
        resolved = [
            reader.resolve_session("session-A"),
            reader.resolve_session("session-B"),
        ]
        assert sum(binding is not None for binding in resolved) == 1
        assert winner.session_binding in resolved
    finally:
        reader.close()


def test_two_sqlite_controllers_conflicting_proposals_allow_one_winner_and_one_conflict(
    tmp_path: Path,
) -> None:
    """同一 correlation 的不同厚度 proposal 只能有一个 winner，另一方必须 correlation conflict。"""

    proposal_type, frozen_type, reader_type = _freeze_types()
    db_path = tmp_path / "front-door.sqlite3"
    bootstrap = front_door.SqliteFrontDoorStateStore(str(db_path))
    bootstrap.close()

    barrier = threading.Barrier(2)
    results: list[object] = []
    errors: list[BaseException] = []

    def worker(label: str, thickness: float) -> None:
        """两个独立连接使用不同 normalized proposal 竞争同一 correlation。"""

        store = front_door.SqliteFrontDoorStateStore(str(db_path))
        proposal = proposal_type(
            candidate_key="primary-revit",
            thickness_value=thickness,
            thickness_unit="mm",
        )
        try:
            controller, _, _, _ = _controller(
                store=store,
                interpreter=_ProposalInterpreter(proposal, barrier),
                candidate=_candidate(),
                observation=_observation(),
                session_ref=f"session-{label}",
                task_id=f"task-{label}",
            )
            results.append(
                controller.prepare_submission(
                    client_submission_ref="race-conflict-001",
                    utterance="按本次模型解析修改墙厚。",
                )
            )
        except BaseException as exc:  # noqa: BLE001 - 测试需要收集竞争 loser 的稳定冲突。
            errors.append(exc)
        finally:
            store.close()

    threads = [
        threading.Thread(target=worker, args=("A", 300.0)),
        threading.Thread(target=worker, args=("B", 350.0)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert len(results) == 1
    assert isinstance(results[0], frozen_type)
    assert len(errors) == 1
    assert "FRONT_DOOR_CORRELATION_CONFLICT" in str(errors[0])

    winner = results[0]
    reader = reader_type(str(db_path))
    try:
        assert sum(
            reader.resolve_session(session_ref) is not None
            for session_ref in ("session-A", "session-B")
        ) == 1
        assert reader.resolve_session(winner.session_binding.session_ref) == winner.session_binding
    finally:
        reader.close()


def test_candidate_hash_drift_under_same_key_is_a_freeze_conflict(
    tmp_path: Path,
) -> None:
    """candidate_key 相同但配置 body/hash 漂移时不能被当作同一 callback。"""

    proposal_type, _, reader_type = _freeze_types()
    db_path = tmp_path / "front-door.sqlite3"
    bootstrap = front_door.SqliteFrontDoorStateStore(str(db_path))
    bootstrap.close()

    barrier = threading.Barrier(2)
    proposal = proposal_type(
        candidate_key="primary-revit",
        thickness_value=300.0,
        thickness_unit="mm",
    )
    results: list[object] = []
    errors: list[BaseException] = []

    def worker(label: str, native_target_unique_id: str) -> None:
        """模拟同一 key 在两个 callback 观察到不同 immutable candidate 配置。"""

        store = front_door.SqliteFrontDoorStateStore(str(db_path))
        try:
            controller, _, _, _ = _controller(
                store=store,
                interpreter=_ProposalInterpreter(proposal, barrier),
                candidate=_candidate(native_target_unique_id=native_target_unique_id),
                observation=_observation(native_target_unique_id=native_target_unique_id),
                session_ref=f"session-{label}",
                task_id=f"task-{label}",
            )
            results.append(
                controller.prepare_submission(
                    client_submission_ref="race-config-drift-001",
                    utterance="把墙改成 300mm。",
                )
            )
        except BaseException as exc:  # noqa: BLE001 - 测试需要捕获配置漂移 loser 的稳定冲突。
            errors.append(exc)
        finally:
            store.close()

    threads = [
        threading.Thread(target=worker, args=("A", "wall-native-001")),
        threading.Thread(target=worker, args=("B", "wall-native-002")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert len(results) == 1
    assert len(errors) == 1
    assert "FRONT_DOOR_CORRELATION_CONFLICT" in str(errors[0])

    winner = results[0]
    reader = reader_type(str(db_path))
    try:
        assert reader.resolve_session(winner.session_binding.session_ref) == winner.session_binding
        losing_ref = (
            "session-B"
            if winner.session_binding.session_ref == "session-A"
            else "session-A"
        )
        assert reader.resolve_session(losing_ref) is None
    finally:
        reader.close()


def test_crash_reopen_after_freeze_recovers_exact_request_binding_and_pending_delivery(
    tmp_path: Path,
) -> None:
    """freeze commit 后进程退出，重启必须读回 byte-equivalent authority 与 DELIVERY_PENDING。"""

    proposal_type, frozen_type, reader_type = _freeze_types()
    db_path = tmp_path / "front-door.sqlite3"
    store = front_door.SqliteFrontDoorStateStore(str(db_path))
    proposal = proposal_type(
        candidate_key="primary-revit",
        thickness_value=300.0,
        thickness_unit="mm",
    )
    controller, _, _, _ = _controller(
        store=store,
        interpreter=_ProposalInterpreter(proposal),
        candidate=_candidate(),
        observation=_observation(),
        session_ref="session-restart",
        task_id="task-restart",
    )
    winner = controller.prepare_submission(
        client_submission_ref="restart-after-freeze-001",
        utterance="把墙改成 300mm。",
    )
    assert isinstance(winner, frozen_type)
    store.close()

    reopened = front_door.SqliteFrontDoorStateStore(str(db_path))
    reader = reader_type(str(db_path))
    try:
        recovered = reopened.get_frozen_submission("restart-after-freeze-001")
        record = reopened.get_submission("restart-after-freeze-001")

        assert recovered == winner
        assert record is not None
        assert record.state is front_door.SubmissionState.FROZEN
        assert record.frozen == winner
        assert recovered.delivery_state == "DELIVERY_PENDING"
        assert recovered.request == winner.request
        assert recovered.request.request_hash == winner.request.request_hash
        assert recovered.session_binding == winner.session_binding
        assert recovered.session_binding.binding_hash == winner.session_binding.binding_hash
        assert reader.resolve_session("session-restart") == winner.session_binding
    finally:
        reader.close()
        reopened.close()
