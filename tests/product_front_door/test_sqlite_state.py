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


def _v2_binding_and_request():
    """构造 SQLite V2 freeze 所需 exact binding/request。"""

    member_type = getattr(front_door, "SessionBindingMemberV2", None)
    binding_type = getattr(front_door, "SessionBindingV2", None)
    assert member_type is not None and binding_type is not None
    revit = member_type(
        host_kind="REVIT",
        role="INITIATOR",
        configured_reference_id="primary-revit",
        configured_reference_hash="1" * 64,
        transport_locator="revit-pipe-v2",
        host_instance_id="revit-runtime-v2",
        document_id=r"C:\DSP\fixtures\cross-host.rvt",
        native_target_id="revit-wall-001",
        host_binding_fingerprint="5" * 64,
    )
    autocad = member_type(
        host_kind="AUTOCAD",
        role="BOUND_REQUIRED",
        configured_reference_id="primary-autocad",
        configured_reference_hash="2" * 64,
        transport_locator="autocad-pipe-v2",
        host_instance_id="autocad-runtime-v2",
        document_id=r"C:\DSP\fixtures\cross-host.dwg",
        native_target_id="autocad-wall-001",
        host_binding_fingerprint="6" * 64,
    )
    binding = binding_type.create(
        session_ref="session-cross-host-sqlite",
        project_id="project-001",
        semantic_target_id="WALL-001",
        semantic_environment_id="SEM-ENV-1",
        semantic_environment_hash="3" * 64,
        topology_environment_id="TOPOLOGY-1",
        topology_revision=7,
        topology_snapshot_hash="4" * 64,
        initiating_host_kind="REVIT",
        members=(revit, autocad),
    )
    request_type = getattr(__import__("design_product_runtime", fromlist=["ProductTaskRequestV2"]), "ProductTaskRequestV2")
    request = request_type.create(
        task_id="task-cross-host-sqlite",
        project_id="project-001",
        initiating_host_kind="REVIT",
        session_ref=binding.session_ref,
        session_binding_hash=binding.binding_hash,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )
    return binding, request


def test_v2_freeze_atomically_persists_request_and_two_member_binding(tmp_path: Path) -> None:
    """V2 client durable owner 必须在一个 freeze winner 中保存完整 request + binding。"""

    frozen_type = getattr(front_door, "FrozenSubmissionV2", None)
    assert frozen_type is not None, "FrozenSubmissionV2 尚未实现"
    db_path = tmp_path / "front-door-v2.sqlite3"
    store = _store(db_path)
    binding, request = _v2_binding_and_request()
    try:
        store.create_submission_v2("client-v2-001", "把两端墙厚改为 300mm")
        frozen = store.freeze_submission_v2(
            client_submission_ref="client-v2-001",
            reviewed_configuration_hash="7" * 64,
            binding=binding,
            request=request,
        )
        assert isinstance(frozen, frozen_type)
        assert frozen.session_binding == binding
        assert frozen.request == request
        assert frozen.delivery_state == "DELIVERY_PENDING"
    finally:
        store.close()

    reopened = _store(db_path)
    try:
        recovered = reopened.get_frozen_submission_v2("client-v2-001")
        assert recovered == frozen
        assert reopened.resolve_session_v2(binding.session_ref) == binding
    finally:
        reopened.close()


def test_v2_freeze_replay_rejects_different_binding_or_request(tmp_path: Path) -> None:
    """同一 V2 correlation 只能拥有一个 immutable request/binding winner。"""

    store = _store(tmp_path / "front-door-v2-conflict.sqlite3")
    binding, request = _v2_binding_and_request()
    try:
        store.create_submission_v2("client-v2-conflict", "双端改为 300mm")
        winner = store.freeze_submission_v2(
            client_submission_ref="client-v2-conflict",
            reviewed_configuration_hash="7" * 64,
            binding=binding,
            request=request,
        )
        replay = store.freeze_submission_v2(
            client_submission_ref="client-v2-conflict",
            reviewed_configuration_hash="7" * 64,
            binding=binding,
            request=request,
        )
        assert replay == winner

        other = type(request).create(
            task_id="task-cross-host-other",
            project_id=request.project_id,
            initiating_host_kind=request.initiating_host_kind,
            session_ref=request.session_ref,
            session_binding_hash=request.session_binding_hash,
            requested_action=request.requested_action,
            intent_arguments=request.intent_arguments,
        )
        with pytest.raises(ValueError, match="FRONT_DOOR_CORRELATION_CONFLICT"):
            store.freeze_submission_v2(
                client_submission_ref="client-v2-conflict",
                reviewed_configuration_hash="7" * 64,
                binding=binding,
                request=other,
            )
    finally:
        store.close()
