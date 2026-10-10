"""Offline contracts for exact, single-use controlled Host stage handoffs."""

from __future__ import annotations

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
               "original_command_id": "cmd-1", "pending_hash": "hash-1",
               "published_at": datetime.now(UTC).isoformat()}
    completion = {"stage_id": "stage-1", "pending_hash": "hash-1",
                  "case_id": "case-1", "task_id": "task-1",
                  "original_command_id": "cmd-1",
                  "operator": "human", "completed_at": datetime.now(UTC).isoformat()}
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
        require_all_ready([], object(), [], [])
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
    }
    completion = {
        "stage_id": pending["stage_id"], "pending_hash": pending["pending_hash"],
        "case_id": pending["case_id"], "task_id": pending["task_id"],
        "original_command_id": pending["original_command_id"],
        "operator": "operator-1", "completed_at": datetime.now(UTC).isoformat(),
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
