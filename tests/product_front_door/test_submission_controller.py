"""Task 4：SubmissionController correlation / clarification / atomic freeze 契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import design_product_front_door as front_door


def _controller_types():
    """延迟取得 Task 4 controller/agent 类型，使尚未实现时形成明确 RED。"""

    controller_type = getattr(front_door, "SubmissionController", None)
    clarification_type = getattr(front_door, "AgentClarificationRequired", None)
    assert controller_type is not None, "SubmissionController 尚未实现"
    assert clarification_type is not None, "AgentClarificationRequired 尚未实现"
    return controller_type, clarification_type


class _ClarifyingInterpreter:
    """只返回澄清问题，并记录 controller 实际传入的 durable utterance。"""

    def __init__(self, clarification_type) -> None:
        self._clarification_type = clarification_type
        self.calls: list[tuple[str, str]] = []

    def interpret(self, *, client_submission_ref: str, utterance: str):
        """返回用户可见澄清，不生成 proposal 或业务 identity。"""

        self.calls.append((client_submission_ref, utterance))
        return self._clarification_type(question="请确认要修改哪一个已配置的 Revit 候选？")


class _ForbiddenCandidateSource:
    """clarification 路径若访问 candidate authority，测试必须立即失败。"""

    def get(self, candidate_key: str):
        """禁止 clarification 后继续 candidate resolution。"""

        raise AssertionError(f"clarification path must not resolve candidate: {candidate_key}")


def _forbidden_probe_factory(*args, **kwargs):
    """clarification 路径不得创建或调用 Host probe。"""

    del args, kwargs
    raise AssertionError("clarification path must not create a Host probe")


def _forbidden_identity_factory() -> str:
    """clarification 路径不得分配 task_id/session_ref。"""

    raise AssertionError("clarification path must not allocate business identity")


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
