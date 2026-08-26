"""Compatibility tests: forward compatibility + golden vectors (TC-C06/C08).

The golden JSON files in ``contracts/test_vectors/`` are read identically by
the Python and the .NET test suites — that is the Python <-> C# contract
compatibility guarantee.
"""

import json
from pathlib import Path

from host_contracts.command import HostCommand
from host_contracts.delta import HostDelta
from host_contracts.envelope import CONTRACT_MAJOR, CONTRACT_MINOR, RequestEnvelope, ResponseEnvelope

VECTORS = Path(__file__).resolve().parents[2] / "test_vectors"


def _load(rel: str) -> dict:
    return json.loads((VECTORS / rel).read_text(encoding="utf-8"))


def test_unknown_field_is_ignored():  # TC-C06
    raw = {"request_id": "req-1", "task_id": "task-1", "future_field": "hello"}
    env = RequestEnvelope.from_dict(raw)
    assert env.request_id == "req-1"
    assert env.task_id == "task-1"
    assert "future_field" not in env.to_dict()


def test_unknown_field_nested_in_command_is_ignored():
    raw = {
        "command_id": "c",
        "document_id": "d",
        "mode": "READ",
        "operation": "context.current_document",
        "future_nested": {"a": 1},
    }
    cmd = HostCommand.from_dict(raw)
    assert "future_nested" not in cmd.to_dict()


def test_contract_version_vector_matches_python_constant():
    vec = _load("contract-version.json")
    assert vec["major"] == CONTRACT_MAJOR
    assert vec["minor"] == CONTRACT_MINOR


def test_golden_move_json_readable_identically_to_csharp():  # TC-C08
    env = RequestEnvelope.from_dict(_load("request/move.json"))
    assert env.validate() == []

    assert env.request_id == "req-001"
    assert env.task_id == "task-001"
    assert env.project_id == "project-001"
    assert env.deadline_at == "2026-08-26T15:00:00Z"
    assert env.idempotency_key == "move-task-001-unit-001"

    cmd = HostCommand.from_dict(env.payload)
    assert cmd.command_id == "cmd-001"
    assert cmd.document_id == "drawing-001"
    assert cmd.mode == "EXECUTE"
    assert cmd.operation == "move.v1"
    assert len(cmd.target_native_refs) == 1
    ref = cmd.target_native_refs[0]
    assert ref.document_id == "drawing-001"
    assert ref.native_id == "2AF"
    assert cmd.arguments == {"displacement": {"x": 500, "y": 0, "z": 0}}

    # Python round-trip stability: serialize -> deserialize -> identical.
    again = RequestEnvelope.from_dict(json.loads(json.dumps(env.to_dict())))
    assert again == env


def test_golden_delta_and_response_vectors():
    modified = HostDelta.from_dict(_load("delta/entity_modified.json"))
    assert modified.revision_before == 100
    assert modified.revision_after == 101
    assert [r.native_id for r in modified.modified] == ["2AF"]
    assert modified.validate() == []

    created = HostDelta.from_dict(_load("delta/entity_created.json"))
    assert created.added[0].native_id == "3B1"
    assert created.added[0].native_type == "LINE"

    conflict = ResponseEnvelope.from_dict(_load("response/revision_conflict.json"))
    assert conflict.status == "ERROR"
    assert conflict.error is not None
    assert conflict.error.error_code == "REVISION_CONFLICT"
    assert conflict.error.category == "CONSISTENCY"
    assert conflict.error.retryable == "AFTER_RECONSTRUCT"
    assert conflict.error.details == [{"expected_revision": 100, "actual_revision": 101}]
    assert conflict.validate() == []

    failed = ResponseEnvelope.from_dict(_load("response/host_command_failed.json"))
    assert failed.error.error_code == "HOST_COMMAND_FAILED"
    assert failed.error.retryable == "IMMEDIATE"
