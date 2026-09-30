"""Task 9：Front Door durable recovery 与独立实例竞争验收。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import design_product_front_door as front_door
import pytest
from design_changeset import canonical_hash
from revit_sidecar import RevitContextObservation, RevitSelectedElement


class _ProposalInterpreter:
    """返回固定 wall-thickness proposal，并记录模型是否被重新调用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def interpret(self, *, client_submission_ref: str, utterance: str):
        """记录 exact correlation/utterance，不接收任何 transport 或 authority metadata。"""

        self.calls.append((client_submission_ref, utterance))
        return front_door.AgentProposal(
            candidate_key="primary-revit",
            thickness_value=300.0,
            thickness_unit="mm",
        )


class _ForbiddenInterpreter:
    """已冻结 correlation rebuild 后若重新调用模型则立即失败。"""

    def interpret(self, *, client_submission_ref: str, utterance: str):
        """禁止 frozen recovery 重新解释自然语言。"""

        raise AssertionError(
            f"frozen recovery must not reinterpret {client_submission_ref=} {utterance=}"
        )


class _CandidateSource:
    """只按 exact configured candidate key 返回一个 candidate。"""

    def __init__(self, candidate) -> None:
        self._candidate = candidate

    def get(self, candidate_key: str):
        """未知 key 返回 None；不提供 latest/fuzzy fallback。"""

        if candidate_key != self._candidate.candidate_key:
            return None
        return self._candidate


class _ForbiddenCandidateSource:
    """frozen recovery 不得重新解析 candidate authority。"""

    def get(self, candidate_key: str):
        """任何访问都代表 recovery 从 durable winner 回退。"""

        raise AssertionError(f"must not resolve candidate after freeze: {candidate_key}")


class _Probe:
    """返回固定 fresh Revit document/runtime/selection evidence。"""

    def __init__(self, observation: RevitContextObservation) -> None:
        self._observation = observation

    def discover(self, *, command_id: str, document_id: str):
        """要求 controller 仍以 configured document 做 fresh discovery。"""

        assert command_id
        assert document_id == self._observation.document_id
        return self._observation


class _ProbeFactory:
    """为一个 configured locator 创建窄 context probe。"""

    def __init__(self, *, locator: str, observation: RevitContextObservation) -> None:
        self._locator = locator
        self._observation = observation

    def __call__(self, transport_locator: str):
        """locator 只用于连接定位，不承担 runtime identity authority。"""

        assert transport_locator == self._locator
        return _Probe(self._observation)


def _forbidden_probe_factory(*args, **kwargs):
    """已冻结 rebuild 后不得访问 Host。"""

    del args, kwargs
    raise AssertionError("frozen recovery must not create a Host probe")


def _forbidden_identity_factory() -> str:
    """已冻结 rebuild 后不得重新分配 task/session identity。"""

    raise AssertionError("frozen recovery must not allocate a new identity")


class _FixedFactory:
    """为竞争测试返回调用方指定的 opaque identity。"""

    def __init__(self, value: str) -> None:
        self._value = value

    def __call__(self) -> str:
        """返回固定 identity。"""

        return self._value


def _candidate(*, target_suffix: str = "001"):
    """构造带 canonical hash 的 configured Revit candidate。"""

    fields = {
        "candidate_key": "primary-revit",
        "project_id": "project-001",
        "transport_locator": f"revit-pipe-{target_suffix}",
        "document_id": rf"C:\\DSP\\fixtures\\front-door-{target_suffix}.rvt",
        "semantic_target_id": f"WALL-{target_suffix}",
        "native_target_unique_id": f"wall-native-{target_suffix}",
    }
    return front_door.ConfiguredRevitCandidate(
        **fields,
        candidate_hash=canonical_hash(
            front_door.configured_revit_candidate_hash_body(**fields)
        ),
    )


def _observation(candidate) -> RevitContextObservation:
    """构造与 candidate exact document/target 对齐的 fresh Host evidence。"""

    return RevitContextObservation(
        document_id=candidate.document_id,
        document_title=candidate.document_id.rsplit("\\", 1)[-1],
        host_instance_id=f"runtime-{candidate.native_target_unique_id}",
        revision=41,
        selected_elements=(
            RevitSelectedElement(
                unique_id=candidate.native_target_unique_id,
                native_kind="Wall",
            ),
        ),
    )


def _controller(
    *,
    store,
    interpreter,
    candidate=None,
    identity_suffix: str = "001",
    frozen_recovery: bool = False,
):
    """组装真实 SubmissionController；测试不复制 correlation/freeze 业务逻辑。"""

    if frozen_recovery:
        return front_door.SubmissionController(
            state_store=store,
            agent_interpreter=interpreter,
            candidate_source=_ForbiddenCandidateSource(),
            context_probe_factory=_forbidden_probe_factory,
            session_ref_factory=_forbidden_identity_factory,
            task_id_factory=_forbidden_identity_factory,
        )

    selected_candidate = candidate or _candidate()
    return front_door.SubmissionController(
        state_store=store,
        agent_interpreter=interpreter,
        candidate_source=_CandidateSource(selected_candidate),
        context_probe_factory=_ProbeFactory(
            locator=selected_candidate.transport_locator,
            observation=_observation(selected_candidate),
        ),
        session_ref_factory=_FixedFactory(f"session-task9-{identity_suffix}"),
        task_id_factory=_FixedFactory(f"task-task9-{identity_suffix}"),
    )


def test_rebuild_before_freeze_reuses_committed_correlation_and_utterance(tmp_path) -> None:
    """correlation 已提交但未 freeze 时，新 client 实例继续同一 durable utterance。"""

    database = tmp_path / "front-door-before-freeze.sqlite3"
    first_store = front_door.SqliteFrontDoorStateStore(str(database))
    created = first_store.create_submission(
        "submission-task9-before-freeze",
        "把当前墙厚改成 300mm",
    )
    assert created.state is front_door.SubmissionState.UNFROZEN
    assert created.frozen is None
    first_store.close()

    interpreter = _ProposalInterpreter()
    rebuilt_store = front_door.SqliteFrontDoorStateStore(str(database))
    rebuilt = _controller(store=rebuilt_store, interpreter=interpreter)
    frozen = rebuilt.prepare_submission(
        client_submission_ref="submission-task9-before-freeze",
        utterance="把当前墙厚改成 300mm",
    )

    assert interpreter.calls == [
        ("submission-task9-before-freeze", "把当前墙厚改成 300mm")
    ]
    assert frozen.request.task_id == "task-task9-001"
    assert frozen.client_submission_ref == "submission-task9-before-freeze"
    assert rebuilt_store.get_frozen_submission(frozen.client_submission_ref) == frozen
    rebuilt_store.close()


def test_rebuild_after_freeze_recovers_exact_request_without_model_or_host(tmp_path) -> None:
    """freeze 已提交后关闭旧连接；replacement client 只读 exact durable winner。"""

    database = tmp_path / "front-door-after-freeze.sqlite3"
    first_store = front_door.SqliteFrontDoorStateStore(str(database))
    first = _controller(store=first_store, interpreter=_ProposalInterpreter())
    winner = first.prepare_submission(
        client_submission_ref="submission-task9-after-freeze",
        utterance="把当前墙厚改成 300mm",
    )
    first_store.close()

    rebuilt_store = front_door.SqliteFrontDoorStateStore(str(database))
    rebuilt = _controller(
        store=rebuilt_store,
        interpreter=_ForbiddenInterpreter(),
        frozen_recovery=True,
    )
    recovered = rebuilt.prepare_submission(
        client_submission_ref="submission-task9-after-freeze",
        utterance="把当前墙厚改成 300mm",
    )

    assert recovered == winner
    assert recovered.request.task_id == winner.request.task_id
    assert recovered.request.request_hash == winner.request.request_hash
    assert recovered.session_binding == winner.session_binding
    rebuilt_store.close()


def test_two_sqlite_controllers_race_same_correlation_same_proposal_one_winner(
    tmp_path,
) -> None:
    """两个独立 SQLite connection 同时 freeze 等价 proposal，只发布一个 durable winner。"""

    database = tmp_path / "front-door-same-proposal-race.sqlite3"
    seed_store = front_door.SqliteFrontDoorStateStore(str(database))
    seed_store.create_submission(
        "submission-task9-same-race",
        "把当前墙厚改成 300mm",
    )
    seed_store.close()

    store_a = front_door.SqliteFrontDoorStateStore(str(database))
    store_b = front_door.SqliteFrontDoorStateStore(str(database))
    controller_a = _controller(
        store=store_a,
        interpreter=_ProposalInterpreter(),
        identity_suffix="race-a",
    )
    controller_b = _controller(
        store=store_b,
        interpreter=_ProposalInterpreter(),
        identity_suffix="race-b",
    )

    def _prepare(controller):
        return controller.prepare_submission(
            client_submission_ref="submission-task9-same-race",
            utterance="把当前墙厚改成 300mm",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        result_a = executor.submit(_prepare, controller_a)
        result_b = executor.submit(_prepare, controller_b)
        frozen_a = result_a.result(timeout=10)
        frozen_b = result_b.result(timeout=10)

    assert frozen_a == frozen_b
    assert frozen_a.request.task_id in {"task-task9-race-a", "task-task9-race-b"}
    assert frozen_a.session_binding.session_ref in {
        "session-task9-race-a",
        "session-task9-race-b",
    }
    assert store_a.get_frozen_submission("submission-task9-same-race") == frozen_a
    assert store_b.get_frozen_submission("submission-task9-same-race") == frozen_a
    store_a.close()
    store_b.close()


def test_two_sqlite_controllers_race_changed_candidate_one_winner_one_conflict(
    tmp_path,
) -> None:
    """同 correlation 若 candidate/target authority 不同，只允许一个 freeze winner。"""

    database = tmp_path / "front-door-conflicting-proposal-race.sqlite3"
    seed_store = front_door.SqliteFrontDoorStateStore(str(database))
    seed_store.create_submission(
        "submission-task9-conflict-race",
        "把当前墙厚改成 300mm",
    )
    seed_store.close()

    store_a = front_door.SqliteFrontDoorStateStore(str(database))
    store_b = front_door.SqliteFrontDoorStateStore(str(database))
    controller_a = _controller(
        store=store_a,
        interpreter=_ProposalInterpreter(),
        candidate=_candidate(target_suffix="race-a"),
        identity_suffix="conflict-a",
    )
    controller_b = _controller(
        store=store_b,
        interpreter=_ProposalInterpreter(),
        candidate=_candidate(target_suffix="race-b"),
        identity_suffix="conflict-b",
    )

    def _capture(controller):
        try:
            return (
                "winner",
                controller.prepare_submission(
                    client_submission_ref="submission-task9-conflict-race",
                    utterance="把当前墙厚改成 300mm",
                ),
            )
        except ValueError as exc:
            return ("conflict", str(exc))

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            executor.submit(_capture, controller_a).result(timeout=10),
            executor.submit(_capture, controller_b).result(timeout=10),
        ]

    kinds = sorted(kind for kind, _ in outcomes)
    assert kinds == ["conflict", "winner"]
    conflict = next(payload for kind, payload in outcomes if kind == "conflict")
    assert "FRONT_DOOR_CORRELATION_CONFLICT" in conflict

    winner = next(payload for kind, payload in outcomes if kind == "winner")
    assert store_a.get_frozen_submission("submission-task9-conflict-race") == winner
    assert store_b.get_frozen_submission("submission-task9-conflict-race") == winner
    store_a.close()
    store_b.close()


@pytest.mark.parametrize("changed_utterance", ["改成 350mm", "改另一面墙到 300mm"])
def test_rebuilt_unfrozen_correlation_rejects_changed_utterance(
    tmp_path,
    changed_utterance: str,
) -> None:
    """rebuild 不能把同一个 correlation 绑定到新的用户原话。"""

    database = tmp_path / "front-door-utterance-conflict.sqlite3"
    first_store = front_door.SqliteFrontDoorStateStore(str(database))
    first_store.create_submission(
        "submission-task9-utterance-conflict",
        "把当前墙厚改成 300mm",
    )
    first_store.close()

    rebuilt_store = front_door.SqliteFrontDoorStateStore(str(database))
    rebuilt = _controller(store=rebuilt_store, interpreter=_ProposalInterpreter())
    with pytest.raises(ValueError, match="FRONT_DOOR_CORRELATION_CONFLICT"):
        rebuilt.prepare_submission(
            client_submission_ref="submission-task9-utterance-conflict",
            utterance=changed_utterance,
        )
    rebuilt_store.close()
