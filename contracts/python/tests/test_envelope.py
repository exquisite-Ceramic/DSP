"""RequestEnvelope / ResponseEnvelope tests (spec A.8, §26.1)."""

import json

from host_contracts.envelope import (
    AsyncOperationRef,
    RequestEnvelope,
    ResponseEnvelope,
    deadline_within,
    is_valid_utc,
)


def _roundtrip(obj):
    return type(obj).from_dict(json.loads(json.dumps(obj.to_dict())))


def test_request_envelope_round_trips_all_fields():  # TC-C01
    env = RequestEnvelope(
        request_id="req-001",
        task_id="task-001",
        project_id="project-001",
        actor_context={"user": "alice", "role": "designer"},
        correlation_ids=["corr-1", "corr-2"],
        deadline_at="2026-08-26T14:00:00Z",
        idempotency_key="move-abc",
        payload={"command_id": "cmd-001", "mode": "EXECUTE"},
    )
    restored = _roundtrip(env)
    assert restored == env
    assert restored.validate() == []


def test_missing_request_id_is_invalid():
    assert RequestEnvelope(request_id="").validate() != []


def test_deadline_is_utc():
    assert is_valid_utc("2026-08-26T14:00:00Z")
    assert is_valid_utc("2026-08-26T14:00:00+00:00")
    assert not is_valid_utc("2026-08-26T14:00:00+02:00")
    assert not is_valid_utc("2026-08-26T14:00:00")  # naive local time
    assert not is_valid_utc("not-a-date")


def test_deadline_round_trip_preserves_timezone_and_precision():
    deadline = "2026-08-26T14:00:00Z"
    restored = _roundtrip(RequestEnvelope(deadline_at=deadline))
    assert restored.deadline_at == deadline
    assert restored.validate() == []


def test_request_id_can_change_on_retry_while_idempotency_key_stays_stable():  # TC-C05
    first = RequestEnvelope(request_id="req-001", idempotency_key="move-abc")
    second = RequestEnvelope(request_id="req-002", idempotency_key="move-abc")
    assert first.validate() == []
    assert second.validate() == []
    assert first.request_id != second.request_id
    assert first.idempotency_key == second.idempotency_key


def test_child_deadline_within_parent():  # AR-024 helper
    assert deadline_within("2026-08-26T14:00:00Z", "2026-08-26T15:00:00Z")
    assert not deadline_within("2026-08-26T16:00:00Z", "2026-08-26T15:00:00Z")
    assert deadline_within(None, "2026-08-26T15:00:00Z")
    assert deadline_within("2026-08-26T14:00:00Z", None)


def test_response_pending_requires_operation_ref():
    assert ResponseEnvelope(request_id="req-1", status="PENDING").validate() != []
    ok = ResponseEnvelope(request_id="req-1", status="OK")
    assert ok.validate() == []
    pending_with_ref = ResponseEnvelope(
        request_id="req-1",
        status="PENDING",
        operation_ref=AsyncOperationRef(type="EXECUTION_JOB", id="job-9"),
    )
    assert pending_with_ref.validate() == []


def test_response_error_requires_error_shape():
    assert ResponseEnvelope(request_id="req-1", status="ERROR").validate() != []
    assert ResponseEnvelope(request_id="req-1", status="ERROR", error=None).validate() != []


def test_async_operation_ref_round_trips():
    ref = AsyncOperationRef(type="EXECUTION_JOB", id="job-9")
    restored = AsyncOperationRef.from_dict(ref.to_dict())
    assert restored == ref
    assert restored.validate() == []
