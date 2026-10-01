"""Task 4：Product Front Door SQLite correlation / freeze durable owner 契约测试。"""

from __future__ import annotations

from pathlib import Path

import design_product_front_door as front_door
import pytest


def _state_types():
    """延迟取得 Task 4 新类型，使尚未实现时形成明确 TDD RED。"""

    store_type = getattr(front_door, "SqliteFrontDoorStateStore", None)
    state_type = getattr(front_door, "SubmissionState", None)
    record_type = getattr(front_door, "SubmissionRecord", None)
    assert store_type is not None, "SqliteFrontDoorStateStore 尚未实现"
    assert state_type is not None, "SubmissionState 尚未实现"
    assert record_type is not None, "SubmissionRecord 尚未实现"
    return store_type, state_type, record_type


def _store(db_path: Path):
    """按单文件 durable SQLite owner 组装状态存储；每个实例持有独立连接。"""

    store_type, _, _ = _state_types()
    return store_type(str(db_path))


def test_create_submission_persists_exact_unfrozen_correlation_without_business_identity(
    tmp_path: Path,
) -> None:
    """模型调用前只持久化 correlation + 原始 utterance，绝不预分配业务身份。"""

    db_path = tmp_path / "front-door.sqlite3"
    store = _store(db_path)
    try:
        _, state_type, record_type = _state_types()
        utterance = "请把当前选中的墙厚度改成 300mm。"

        created = store.create_submission("client-submit-001", utterance)

        assert isinstance(created, record_type)
        assert created.client_submission_ref == "client-submit-001"
        assert created.utterance == utterance
        assert created.state is state_type.UNFROZEN
        assert created.frozen is None

        # UNFROZEN read model 只有 correlation 生命周期字段；不能伪造 request/session/proposal。
        assert not hasattr(created, "task_id")
        assert not hasattr(created, "session_ref")
        assert not hasattr(created, "proposal_hash")
        assert not hasattr(created, "request")
        assert not hasattr(created, "session_binding")

        persisted = store.get_submission("client-submit-001")
        assert persisted == created
        assert store.get_frozen_submission("client-submit-001") is None
    finally:
        store.close()


def test_same_correlation_and_same_utterance_is_idempotent_before_freeze(
    tmp_path: Path,
) -> None:
    """客户端在模型调用前重试同一 correlation 时只能读回同一 UNFROZEN 记录。"""

    store = _store(tmp_path / "front-door.sqlite3")
    try:
        first = store.create_submission("client-submit-002", "墙厚改为 300mm")
        replayed = store.create_submission("client-submit-002", "墙厚改为 300mm")

        assert replayed == first
        assert replayed.frozen is None
    finally:
        store.close()


def test_same_correlation_with_different_utterance_fails_closed(
    tmp_path: Path,
) -> None:
    """一个 correlation 的原始自然语言不可改写；澄清后的新表达必须使用新 correlation。"""

    store = _store(tmp_path / "front-door.sqlite3")
    try:
        original = store.create_submission("client-submit-003", "墙厚改为 300mm")

        with pytest.raises(ValueError, match="FRONT_DOOR_CORRELATION_CONFLICT"):
            store.create_submission("client-submit-003", "墙厚改为 350mm")

        assert store.get_submission("client-submit-003") == original
    finally:
        store.close()


def test_client_restart_before_freeze_recovers_exact_unfrozen_utterance(
    tmp_path: Path,
) -> None:
    """correlation 创建后、模型 freeze 前进程重启，必须仍可重新解释原始 immutable utterance。"""

    db_path = tmp_path / "front-door.sqlite3"
    utterance = "把当前墙厚改为 300mm；如果信息不足就先问我。"

    first_store = _store(db_path)
    try:
        created = first_store.create_submission("client-submit-restart", utterance)
        assert created.frozen is None
    finally:
        first_store.close()

    rebuilt_store = _store(db_path)
    try:
        _, state_type, record_type = _state_types()
        recovered = rebuilt_store.get_submission("client-submit-restart")

        assert isinstance(recovered, record_type)
        assert recovered.client_submission_ref == "client-submit-restart"
        assert recovered.utterance == utterance
        assert recovered.state is state_type.UNFROZEN
        assert recovered.frozen is None
        assert rebuilt_store.get_frozen_submission("client-submit-restart") is None

        # 重启读取仍只是 correlation truth；没有 freeze 就绝不能凭数据库状态重建业务身份。
        assert not hasattr(recovered, "task_id")
        assert not hasattr(recovered, "session_ref")
        assert not hasattr(recovered, "proposal_hash")
        assert not hasattr(recovered, "request")
        assert not hasattr(recovered, "session_binding")
    finally:
        rebuilt_store.close()
