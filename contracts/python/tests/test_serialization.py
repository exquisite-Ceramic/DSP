"""JSON serialization tests shared by all DTOs."""

import json

from host_contracts.command import HostCommand
from host_contracts.delta import HostDelta
from host_contracts.entity_ref import HostEntityRef
from host_contracts.envelope import RequestEnvelope
from host_contracts.error import ErrorShape
from host_contracts.result import HostCommandResult

SAMPLE_OBJECTS = [
    RequestEnvelope(
        request_id="req-001",
        task_id="task-001",
        idempotency_key="k-1",
        payload={"command_id": "cmd-001"},
    ),
    HostCommand(
        command_id="cmd-001",
        document_id="drawing-001",
        mode="EXECUTE",
        operation="move.v1",
        target_native_refs=[HostEntityRef(document_id="drawing-001", native_id="2AF")],
        arguments={"displacement": {"x": 500, "y": 0, "z": 0}},
        idempotency_key="k-1",
    ),
    HostCommandResult(command_id="cmd-001", status="OK", revision_after=101),
    HostCommandResult(
        command_id="cmd-002",
        status="ERROR",
        error=ErrorShape(error_code="REVISION_CONFLICT", category="CONSISTENCY"),
    ),
    HostDelta(
        revision_before=100,
        revision_after=101,
        modified=[HostEntityRef(document_id="drawing-001", native_id="2AF")],
    ),
    ErrorShape(error_code="REVISION_CONFLICT", category="CONSISTENCY", retryable="AFTER_RECONSTRUCT"),
]


def test_all_dtos_round_trip_through_json():
    for obj in SAMPLE_OBJECTS:
        restored = type(obj).from_dict(json.loads(json.dumps(obj.to_dict())))
        assert restored == obj


def test_mode_serializes_as_string_not_number():
    cmd = HostCommand(command_id="c", mode="EXECUTE", operation="move.v1")
    raw = json.dumps(cmd.to_dict())
    assert '"mode": "EXECUTE"' in raw
    assert '"mode": 2' not in raw


def test_optional_fields_are_omitted_when_unset():
    cmd = HostCommand(command_id="c", mode="READ", operation="context.current_document")
    d = cmd.to_dict()
    assert "idempotency_key" not in d
    assert "deadline_at" not in d
    assert "arguments" not in d
    assert "preconditions" not in d


def test_error_round_trip_via_result():
    result = HostCommandResult(
        command_id="c",
        status="ERROR",
        error=ErrorShape(
            error_code="REVISION_CONFLICT",
            category="CONSISTENCY",
            retryable="AFTER_RECONSTRUCT",
        ),
    )
    restored = HostCommandResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert restored == result
    assert not restored.ok
    assert restored.error.error_code == "REVISION_CONFLICT"


def test_ok_result_round_trip():
    result = HostCommandResult(
        command_id="c",
        status="OK",
        payload={"moved": 1},
        revision_after=101,
        verification={"ok": True},
    )
    restored = HostCommandResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert restored == result
    assert restored.ok
