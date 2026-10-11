"""Offline contracts for exact, single-use controlled Host stage handoffs."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.integration.cross_host_product_live_stages import (
    STAGE_DEADLINE_SECONDS,
    require_all_ready,
    require_autocad_committed_delta,
    stage_budget_seconds,
    stage_hash,
    stage_identity,
    validate_native_stage_failure,
    validate_partial_event_order,
    validate_stage_completion,
    validate_stage_release,
    wait_for_stage_release,
)


def _case():
    return {
        "case_id": "partial_commit-case",
        "scenario": "partial_commit",
        "implementation_head": "a" * 40,
    }


def _command():
    return SimpleNamespace(
        to_dict=lambda: {
            "command_id": "dispatch-revit-1",
            "document_id": "fixture.rvt",
            "mode": "EXECUTE",
            "operation": "set_wall_thickness",
            "target_native_refs": [
                {"document_id": "fixture.rvt", "native_id": "wall-1", "native_type": "Wall"}
            ],
            "preconditions": [{"revision": 8}],
        }
    )


def test_stage_deadline_precedes_sdk_timeout():
    assert 0 < STAGE_DEADLINE_SECONDS < 300
    assert 0 < stage_budget_seconds(
        (datetime.now(UTC) - timedelta(seconds=100)).isoformat()
    ) < STAGE_DEADLINE_SECONDS
    with pytest.raises(ValueError, match="STAGE_TIMEOUT"):
        stage_budget_seconds((datetime.now(UTC) - timedelta(seconds=275)).isoformat())


def test_stage_identity_requires_exact_command_and_frozen_lineage():
    pending = stage_identity(
        _case(),
        {"task_id": "task-1", "request_hash": "r", "session_binding_hash": "b"},
        {"host_instance_id": "revit-1", "document_id": "fixture.rvt", "native_target_id": "wall-1"},
        _command(),
        prerequisite_hashes={"all_ready": "h"},
    )
    assert pending["original_command_id"] == "dispatch-revit-1"
    assert pending["expected_revision"] == 8
    assert pending["prerequisite_hashes"] == {"all_ready": "h"}
    with pytest.raises(ValueError, match="STAGE_COMMAND"):
        stage_identity(
            _case(),
            {"task_id": "task-1", "request_hash": "r", "session_binding_hash": "b"},
            {"host_instance_id": "revit-1", "document_id": "fixture.rvt",
             "native_target_id": "other-wall"},
            _command(),
            prerequisite_hashes={"all_ready": "h"},
        )


def test_stage_completion_and_release_reject_other_stage_or_duplicate():
    pending = {"stage_id": "stage-1", "case_id": "case-1", "task_id": "task-1",
               "scenario": "unavailable",
               "original_command_id": "cmd-1", "pending_hash": "hash-1",
               "published_at": datetime.now(UTC).isoformat()}
    completion = {"stage_id": "stage-1", "pending_hash": "hash-1",
                  "case_id": "case-1", "task_id": "task-1",
                  "original_command_id": "cmd-1",
                  "operator": "human", "completed_at": datetime.now(UTC).isoformat(),
                  "action": "REVIT_DOCUMENT_CLOSED_UNSAVED",
                  "authorization_ref": "separate-operator-action-1"}
    validate_stage_completion(pending, completion)
    with pytest.raises(ValueError, match="STAGE_RELEASE"):
        validate_stage_completion(pending, {**completion, "pending_hash": "wrong"})
    release = {"stage_id": "stage-1", "pending_hash": "hash-1",
               "case_id": "case-1", "task_id": "task-1",
               "original_command_id": "cmd-1",
               "completion_hash": "done-1", "proof_hash": "proof-1"}
    validate_stage_release(pending, release, completion_hash="done-1", proof_hash="proof-1")
    with pytest.raises(ValueError, match="STAGE_RELEASE"):
        validate_stage_release(pending, {**release, "stage_id": "other"},
                               completion_hash="done-1", proof_hash="proof-1")


def test_original_native_error_is_required_for_both_stages():
    unavailable = {"status": "ERROR", "revision_after": 0,
                   "error": {"code": "REVIT_ACTIVE_DOCUMENT_UNAVAILABLE"}}
    conflict = {"status": "ERROR", "error": {
        "code": "REVISION_CONFLICT", "commit_state": "BEFORE_COMMIT"}}
    assert validate_native_stage_failure("unavailable", unavailable) is unavailable
    assert validate_native_stage_failure("partial_commit", conflict) is conflict
    for scenario, damaged in (
        ("unavailable", {**unavailable, "revision_after": 1}),
        ("partial_commit", {**conflict, "error": {
            "code": "REVISION_CONFLICT", "commit_state": "COMMIT_STATE_UNKNOWN"}}),
    ):
        with pytest.raises(ValueError, match="STAGE_NATIVE_ERROR"):
            validate_native_stage_failure(scenario, damaged)


def test_partial_stage_rejects_missing_all_ready_and_durable_auto_delta():
    with pytest.raises(ValueError, match="all-required READY absent"):
        require_all_ready([], object(), [], [], execution_plan=object())
    with pytest.raises(ValueError, match="AutoCAD durable delta absent"):
        require_autocad_committed_delta({}, "auto-host", "slice-hash")


def test_partial_event_order_preserves_four_actual_timestamps():
    origin = datetime.now(UTC)
    ordered = [(origin + timedelta(seconds=index)).isoformat() for index in range(4)]
    names, times = validate_partial_event_order(ordered)
    assert names == ["ALL_REQUIRED_READY", "AUTOCAD_PRODUCT_COMMITTED",
                     "INDEPENDENT_REVIT_EDIT_201MM", "REVIT_PRODUCT_REVISION_CONFLICT"]
    assert list(times.values()) == ordered
    with pytest.raises(ValueError, match="STAGE_EVENT_ORDER"):
        validate_partial_event_order([ordered[0], ordered[2], ordered[1], ordered[3]])
    with pytest.raises(ValueError, match="STAGE_EVENT_ORDER"):
        validate_partial_event_order(ordered[:3])


def test_stage_release_is_single_use_and_requires_exact_pending(tmp_path):
    from tests.integration.cross_host_product_live_driver import write_once

    pending = {
        "stage_id": "stage-1", "pending_hash": "p" * 64,
        "case_id": "case-1", "task_id": "task-1", "original_command_id": "cmd-1",
        "published_at": datetime.now(UTC).isoformat(),
        "deadline_seconds": 180,
        "scenario": "unavailable",
    }
    completion = {
        "stage_id": pending["stage_id"], "pending_hash": pending["pending_hash"],
        "case_id": pending["case_id"], "task_id": pending["task_id"],
        "original_command_id": pending["original_command_id"],
        "operator": "operator-1", "completed_at": datetime.now(UTC).isoformat(),
        "action": "REVIT_DOCUMENT_CLOSED_UNSAVED",
        "authorization_ref": "operator-authorization-unavailable-1",
    }
    release = {
        "stage_id": pending["stage_id"], "pending_hash": pending["pending_hash"],
        "case_id": pending["case_id"], "task_id": pending["task_id"],
        "original_command_id": pending["original_command_id"],
        "completion_hash": stage_hash(completion), "proof_hash": "proof",
    }
    write_once(tmp_path / "stage-controller-completion.json", completion)
    write_once(tmp_path / "stage-release.json", release)
    wait_for_stage_release(tmp_path, pending, proof_hash="proof", check_head=lambda: None)
    with pytest.raises(ValueError, match="STAGE_RELEASE_DUPLICATE"):
        wait_for_stage_release(tmp_path, pending, proof_hash="proof", check_head=lambda: None)


def test_early_or_mismatched_release_never_consumed(tmp_path):
    from tests.integration.cross_host_product_live_driver import write_once

    pending = {"stage_id": "stage-1", "pending_hash": "p" * 64,
               "case_id": "case-1", "task_id": "task-1", "original_command_id": "cmd-1",
               "published_at": datetime.now(UTC).isoformat(), "deadline_seconds": 180}
    completion = {"stage_id": "wrong-stage", "pending_hash": pending["pending_hash"],
                  "case_id": pending["case_id"], "task_id": pending["task_id"],
                  "original_command_id": pending["original_command_id"],
                  "operator": "operator-1", "completed_at": datetime.now(UTC).isoformat()}
    write_once(tmp_path / "stage-controller-completion.json", completion)
    write_once(tmp_path / "stage-release.json", {
        "stage_id": pending["stage_id"], "pending_hash": pending["pending_hash"],
        "case_id": pending["case_id"], "task_id": pending["task_id"],
        "original_command_id": pending["original_command_id"],
        "completion_hash": stage_hash(completion), "proof_hash": "proof",
    })
    with pytest.raises(ValueError, match="STAGE_RELEASE"):
        wait_for_stage_release(tmp_path, pending, proof_hash="proof", check_head=lambda: None)
    assert not (tmp_path / "stage-release-consumed.json").exists()


def _stage_release_fixture(directory, *, scenario="unavailable", completion_damage=None):
    """离线构造尚未 consumed 的 stage；真实发送端必须自行复核业务动作。"""

    from tests.integration.cross_host_product_live_driver import write_once

    pending = {
        "stage_id": "stg-review-1",
        "pending_hash": "p" * 64,
        "case_id": "case-review-1",
        "task_id": "task-review-1",
        "original_command_id": "product-revit-1",
        "host_kind": "REVIT",
        "host_instance_id": "revit-host-1",
        "document_id": "original.rvt",
        "native_target_id": "wall-original",
        "expected_revision": 7,
        "scenario": scenario,
        "published_at": datetime.now(UTC).isoformat(),
        "deadline_seconds": 1,
    }
    completion = {
        "stage_id": pending["stage_id"],
        "pending_hash": pending["pending_hash"],
        "case_id": pending["case_id"],
        "task_id": pending["task_id"],
        "original_command_id": pending["original_command_id"],
        "operator": "authorized-person",
        "completed_at": datetime.now(UTC).isoformat(),
        "action": (
            "REVIT_DOCUMENT_CLOSED_UNSAVED" if scenario == "unavailable"
            else "REVIT_NATIVE_UI_EDIT_201MM"
        ),
        "authorization_ref": "independent-approval-1",
    }
    if scenario == "partial_commit":
        completion["native_edit_command_id"] = "external-edit-1"
    if completion_damage:
        completion_damage(completion)
    release = {
        "stage_id": pending["stage_id"],
        "pending_hash": pending["pending_hash"],
        "case_id": pending["case_id"],
        "task_id": pending["task_id"],
        "original_command_id": pending["original_command_id"],
        "completion_hash": stage_hash(completion),
        "proof_hash": "prerequisites-1",
    }
    write_once(directory / "stage-controller-completion.json", completion)
    write_once(directory / "stage-release.json", release)
    return pending


@pytest.mark.parametrize(
    "damage",
    [
        lambda body: body.pop("action"),
        lambda body: body.update(action="REVIT_NATIVE_UI_EDIT_201MM"),
        lambda body: body.pop("authorization_ref"),
        lambda body: body.update(authorization_ref=""),
    ],
)
def test_send_side_rejects_matching_release_without_authorized_action(
    tmp_path, damage
):
    """release hash 正确也不得替缺失动作背书，必须在 consumed/attempt 前失败。"""

    pending = _stage_release_fixture(
        tmp_path, scenario="unavailable", completion_damage=damage
    )
    delegate_calls = []
    with pytest.raises(ValueError, match="LIVE_STAGE_RELEASE_INVALID"):
        wait_for_stage_release(
            tmp_path,
            pending,
            proof_hash="prerequisites-1",
            check_head=lambda: None,
        )
        delegate_calls.append("actual_transport_called")
    assert delegate_calls == []
    assert not (tmp_path / "stage-release-consumed.json").exists()
    assert not (tmp_path / "stage-send-attempt.json").exists()


@pytest.mark.parametrize(
    "damage",
    [
        lambda body: body.pop("native_edit_command_id"),
        lambda body: body.update(native_edit_command_id="product-revit-1"),
        lambda body: body.update(action="REVIT_DOCUMENT_CLOSED_UNSAVED"),
    ],
)
def test_partial_sender_never_accepts_incomplete_independent_edit(tmp_path, damage):
    """外部编辑身份必须独立于 Product EXECUTE 且 scenario action 精确匹配。"""

    pending = _stage_release_fixture(
        tmp_path, scenario="partial_commit", completion_damage=damage
    )
    with pytest.raises(ValueError, match="LIVE_STAGE_RELEASE_INVALID"):
        wait_for_stage_release(
            tmp_path,
            pending,
            proof_hash="prerequisites-1",
            check_head=lambda: None,
        )
    assert not (tmp_path / "stage-release-consumed.json").exists()


def test_partial_sender_needs_actual_independent_201mm_read_before_consuming(
    tmp_path,
):
    """只有人工 completion 和匹配 release 但没有真实 READ，不允许 Revit 执行。"""

    pending = _stage_release_fixture(tmp_path, scenario="partial_commit")
    with pytest.raises(ValueError, match="LIVE_STAGE_EDIT_INVALID"):
        wait_for_stage_release(
            tmp_path,
            pending,
            proof_hash="prerequisites-1",
            check_head=lambda: None,
        )
    assert not (tmp_path / "stage-release-consumed.json").exists()
    assert not (tmp_path / "stage-send-attempt.json").exists()


def _audited_partial_read(directory, pending, *, width=201, revision=8):
    """用两条 Host 边界审计记录构造可验证的独立 READ，并返回记录。"""

    from tests.integration.cross_host_product_live_composition import append_audit
    from tests.integration.cross_host_product_live_driver import write_once

    command_id = pending["stage_id"] + ":independent-edit-read"
    command = {
        "command_id": command_id,
        "mode": "READ",
        "operation": "read_wall_thickness_snapshot",
        "document_id": pending["document_id"],
    }
    response = {
        "status": "OK",
        "payload": {
            "host_instance_id": pending["host_instance_id"],
            "document_id": pending["document_id"],
            "wall_unique_id": pending["native_target_id"],
            "revision_before": revision,
            "revision_after": revision,
            "wall_thickness_mm": width,
        },
    }
    for phase in ("SEND", "RECEIVE"):
        row = {
            "host_kind": "REVIT",
            "stage": "INDEPENDENT_EDIT_READ",
            "phase": phase,
            "command": command,
        }
        if phase == "RECEIVE":
            row["response"] = response
        append_audit(directory / "host-commands.jsonl", row)
    observation = {
        "host_kind": "REVIT",
        "host_instance_id": pending["host_instance_id"],
        "document_id": pending["document_id"],
        "native_target_id": pending["native_target_id"],
        "command_id": command_id,
        "normalized_thickness_mm": width,
        "host_revision": revision,
    }
    write_once(directory / "independent-edit-observation.json", observation)
    return response


def test_partial_sender_allows_unique_authentic_audited_read_only_once(tmp_path):
    """有效 completion、审计 READ 和 release 只允许消费一次。"""

    pending = _stage_release_fixture(tmp_path, scenario="partial_commit")
    _audited_partial_read(tmp_path, pending)
    wait_for_stage_release(
        tmp_path, pending, proof_hash="prerequisites-1", check_head=lambda: None
    )
    assert (tmp_path / "stage-release-consumed.json").is_file()
    with pytest.raises(ValueError, match="LIVE_STAGE_RELEASE_DUPLICATE"):
        wait_for_stage_release(
            tmp_path, pending, proof_hash="prerequisites-1", check_head=lambda: None
        )


@pytest.mark.parametrize(
    "damage",
    [
        "wrong_width",
        "stale_revision",
        "wrong_observation_host",
        "wrong_observation_document",
        "wrong_observation_target",
        "wrong_observation_command",
        "wrong_raw_width",
        "wrong_raw_revision",
        "wrong_raw_host",
        "wrong_raw_document",
        "wrong_raw_target",
    ],
)
def test_partial_sender_rejects_independent_read_identity_or_value_drift(
    tmp_path, damage
):
    """不允许只凭 observation 摘要、假 command 或旧 revision 释放 Revit EXECUTE。"""

    from tests.integration.cross_host_product_live_driver import read_json, write_once

    pending = _stage_release_fixture(tmp_path, scenario="partial_commit")
    _audited_partial_read(tmp_path, pending)
    if damage.startswith("wrong_observation") or damage in {
        "wrong_width", "stale_revision"
    }:
        path = tmp_path / "independent-edit-observation.json"
        body = read_json(path)
        changes = {
            "wrong_width": ("normalized_thickness_mm", 200),
            "stale_revision": ("host_revision", 7),
            "wrong_observation_host": ("host_instance_id", "another-host"),
            "wrong_observation_document": ("document_id", "other.rvt"),
            "wrong_observation_target": ("native_target_id", "other-wall"),
            "wrong_observation_command": ("command_id", "other-command"),
        }
        field, value = changes[damage]
        body[field] = value
        path.unlink()
        write_once(path, body)
    else:
        path = tmp_path / "host-commands.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        response = rows[1]["response"]["payload"]
        changes = {
            "wrong_raw_width": ("wall_thickness_mm", 200),
            "wrong_raw_revision": ("revision_after", 9),
            "wrong_raw_host": ("host_instance_id", "another-host"),
            "wrong_raw_document": ("document_id", "other.rvt"),
            "wrong_raw_target": ("wall_unique_id", "other-wall"),
        }
        field, value = changes[damage]
        response[field] = value
        path.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
    with pytest.raises(ValueError, match="LIVE_STAGE_EDIT_INVALID|LIVE_HOST_EVIDENCE_INVALID"):
        wait_for_stage_release(
            tmp_path, pending, proof_hash="prerequisites-1", check_head=lambda: None
        )
    assert not (tmp_path / "stage-release-consumed.json").exists()
    assert not (tmp_path / "stage-send-attempt.json").exists()


def test_real_stage_controller_does_not_publish_invalid_operator_action(
    tmp_path,
):
    """调用实际 controller，不允许缺少授权的 completion 发布 release。"""

    from tests.integration.cross_host_product_live_driver import (
        run_stage_controller,
        write_once,
    )

    pending = _stage_release_fixture(
        tmp_path,
        scenario="unavailable",
        completion_damage=lambda completion: completion.pop("authorization_ref"),
    )
    write_once(tmp_path / "pending-stage.json", pending)
    with pytest.raises(ValueError, match="LIVE_STAGE_RELEASE_INVALID"):
        run_stage_controller(
            None, tmp_path, None, check_head=lambda: None
        )
    assert not (tmp_path / "stage-release-consumed.json").exists()
    # 上面 fixture 预先放置的 release 来自故意伪造的输入；controller 绝不能覆写它。
    assert json.loads((tmp_path / "stage-release.json").read_text())["proof_hash"] == (
        "prerequisites-1"
    )


@pytest.mark.parametrize(
    "damage", [
        "missing_action", "missing_authorization", "good",
        "timeout_during_validation", "timeout_before_transport",
    ],
)
def test_real_audited_revit_send_seam_never_delegates_invalid_stage(
    monkeypatch, tmp_path, damage
):
    """穿过实际受审 Revit transport wrapper，而非只测试校验 helper。

    completion 在 pending 公开之后才出现；合法发送仅一次，缺授权时
    超出发送门槛绝不调用原始 transport，也不记录任何 SEND/attempt。
    """

    from types import SimpleNamespace

    from revit_sidecar.named_pipe import NamedPipeTransport

    from tests.integration import cross_host_product_live_composition as composition
    from tests.integration import cross_host_product_live_driver as driver

    case = {
        "case_id": "audited-case-1",
        "scenario": "unavailable",
        "implementation_head": "a" * 40,
    }
    frozen = {
        "session_binding": {
            "binding_hash": "b" * 64,
            "members": [
                {
                    "host_kind": "REVIT",
                    "host_instance_id": "revit-1",
                    "document_id": "original.rvt",
                    "native_target_id": "wall-1",
                }
            ],
        },
        "request": {
            "task_id": "task-1",
            "request_hash": "r" * 64,
        },
    }
    driver.write_once(tmp_path / "case.json", case)
    driver.write_once(tmp_path / "frozen-submission.json", frozen)
    driver.write_once(tmp_path / "resume-attempt.json", {
        "timestamp": datetime.now(UTC).isoformat()
    })
    monkeypatch.setattr(
        driver,
        "stage_prerequisites",
        lambda *_args, **_kwargs: {"expected_revision": 0, "readiness": "valid"},
    )
    sends = []

    def native_request(_self, _command):
        """只要经过真正 delegate，严格记录唯一发送。"""

        sends.append("native_transport_called")
        return {"status": "ERROR", "revision_after": 0, "error": {
            "code": "REVIT_ACTIVE_DOCUMENT_UNAVAILABLE"
        }}

    monkeypatch.setattr(NamedPipeTransport, "request", native_request)

    if damage.startswith("timeout_"):
        from tests.integration import cross_host_product_live_stages as stages

        # 受控替身把 stage 预算固定在 1 秒，避免真实 sleep；时钟只在
        # 原始发送入口调用期间向前跳跃，复现校验耗时和发送前耗时两种窗口。
        original_stage_identity = stages.stage_identity
        def one_second_stage(*args, **kwargs):
            pending = original_stage_identity(*args, **kwargs)
            pending["deadline_seconds"] = 1
            pending["pending_hash"] = stage_hash({
                key: value for key, value in pending.items() if key != "pending_hash"
            })
            return pending

        clock = {"seconds": 0.0}
        monkeypatch.setattr(stages, "stage_identity", one_second_stage)
        monkeypatch.setattr(stages.time, "monotonic", lambda: clock["seconds"])
        if damage == "timeout_during_validation":
            original_action = stages.validate_stage_action_evidence
            def delayed_action(*args, **kwargs):
                result = original_action(*args, **kwargs)
                clock["seconds"] = 2.0
                return result
            monkeypatch.setattr(stages, "validate_stage_action_evidence", delayed_action)

    original_write_once = composition.write_once

    def publish_and_complete(path, body):
        """pending 正式落盘之后才模拟外部人员发布 completion。"""

        original_write_once(path, body)
        if damage == "timeout_before_transport" and path.name == "stage-send-attempt.json":
            # send-attempt 已占位，但 deadline 耗尽不得调用原 transport。
            clock["seconds"] = 2.0
        if path.name != "pending-stage.json":
            return
        completion = {
            "stage_id": body["stage_id"],
            "pending_hash": body["pending_hash"],
            "case_id": body["case_id"],
            "task_id": body["task_id"],
            "original_command_id": body["original_command_id"],
            "operator": "reviewer",
            "completed_at": datetime.now(UTC).isoformat(),
            "action": "REVIT_DOCUMENT_CLOSED_UNSAVED",
            "authorization_ref": "case-specific-operator-ref",
        }
        if damage == "missing_action":
            completion.pop("action")
        elif damage == "missing_authorization":
            completion.pop("authorization_ref")
        original_write_once(tmp_path / "stage-controller-completion.json", completion)
        release = {
            "stage_id": body["stage_id"],
            "pending_hash": body["pending_hash"],
            "case_id": body["case_id"],
            "task_id": body["task_id"],
            "original_command_id": body["original_command_id"],
            "completion_hash": stage_hash(completion),
            "proof_hash": stage_hash(body["prerequisite_hashes"]),
        }
        original_write_once(tmp_path / "stage-release.json", release)

    monkeypatch.setattr(composition, "write_once", publish_and_complete)
    config = SimpleNamespace(
        autocad_endpoint="unused-autocad-pipe",
        revit_pipe="reviewed-revit-pipe",
        autocad_host_instance_id="auto-1",
        revit_host_instance_id="revit-1",
    )
    command = SimpleNamespace(
        mode="READ",
        operation="check_wall_thickness_readiness",
        command_id="product-revit-read-1",
        to_dict=lambda: {
            "mode": "READ",
            "operation": "check_wall_thickness_readiness",
            "command_id": "product-revit-read-1",
            "document_id": "original.rvt",
            "target_native_refs": [{
                "document_id": "original.rvt",
                "native_id": "wall-1",
                "native_type": "Wall",
            }],
            "preconditions": [],
        },
    )
    factory = composition.audited_host_factories(
        config, tmp_path, check_head=lambda: None, stage="MCP"
    )[1]
    if damage == "good":
        assert factory(config.revit_pipe).request(command)["status"] == "ERROR"
        assert sends == ["native_transport_called"]
        assert (tmp_path / "stage-send-attempt.json").is_file()
        with pytest.raises((ValueError, FileExistsError)):
            factory(config.revit_pipe).request(command)
        assert sends == ["native_transport_called"]
    elif damage.startswith("timeout_"):
        with pytest.raises(ValueError, match="LIVE_STAGE_TIMEOUT"):
            factory(config.revit_pipe).request(command)
        assert sends == []
        assert not (tmp_path / "host-commands.jsonl").exists()
    else:
        with pytest.raises(ValueError, match="LIVE_STAGE_RELEASE_INVALID"):
            factory(config.revit_pipe).request(command)
        assert sends == []
        assert not (tmp_path / "stage-send-attempt.json").exists()
        assert not (tmp_path / "stage-release-consumed.json").exists()


@pytest.mark.parametrize(
    "damage",
    ["duplicate_autocad", "missing_revit", "extra_slice", "wrong_document", "wrong_materialization"],
)
def test_required_ready_receipts_are_exact_unique_required_slices(damage):
    """真实 readiness DTO/hash 可以有效但不覆盖 REQUIRED 双端：验收 gate 必须拒绝。

    复用生产 CrossHostReadinessBarrier 与签名回执，不靠虚构的 SimpleNamespace/hash。
    """

    from dataclasses import replace

    from design_execution_coordination import compute_readiness_receipt_hash

    from tests.execution_coordination._support import barrier, phase_i_readiness_inputs

    ctx = phase_i_readiness_inputs()
    original = barrier()[0].check_all(
        ctx.materialization_plan, ctx.execution_plan, ctx.binding_sets, ctx.authorities
    )
    auto, revit = original.receipts
    if damage == "duplicate_autocad":
        receipts = (auto, auto)
    elif damage == "missing_revit":
        receipts = (auto,)
    elif damage == "extra_slice":
        receipts = (auto, revit, revit)
    else:
        mismatched = (
            replace(
                revit,
                host_runtime_ref=replace(revit.host_runtime_ref, document_ref="wrong.rvt"),
            )
            if damage == "wrong_document"
            else replace(revit, materialization_id="foreign-materialization")
        )
        mismatched = replace(
            mismatched, receipt_hash=compute_readiness_receipt_hash(mismatched)
        )
        receipts = (auto, mismatched)
    result = replace(original, receipts=receipts)
    observations = [
        {
            "host_kind": receipt.host_runtime_ref.host_type.upper(),
            "host_instance_id": receipt.host_runtime_ref.host_instance_id,
            "host_revision": receipt.observed_revision,
            "document_id": receipt.host_runtime_ref.document_ref,
        }
        for receipt in original.receipts
    ]
    with pytest.raises(ValueError, match="LIVE_STAGE_PREREQUISITE_INVALID"):
        require_all_ready(
            [result], ctx.materialization_plan, ctx.authorities, observations,
            execution_plan=ctx.execution_plan,
        )


def test_required_ready_valid_real_dual_host_receipts_remain_accepted():
    """合法生产 AutoCAD/Revit READY 回执必须仍可通过，顺序不被重排。"""

    from tests.execution_coordination._support import barrier, phase_i_readiness_inputs

    ctx = phase_i_readiness_inputs()
    result = barrier()[0].check_all(
        ctx.materialization_plan, ctx.execution_plan, ctx.binding_sets, ctx.authorities
    )
    observations = [
        {
            "host_kind": receipt.host_runtime_ref.host_type.upper(),
            "host_instance_id": receipt.host_runtime_ref.host_instance_id,
            "host_revision": receipt.observed_revision,
            "document_id": receipt.host_runtime_ref.document_ref,
        }
        for receipt in result.receipts
    ]
    assert require_all_ready(
        [result], ctx.materialization_plan, ctx.authorities, observations,
        execution_plan=ctx.execution_plan,
    ) == tuple(receipt.receipt_hash for receipt in result.receipts)
