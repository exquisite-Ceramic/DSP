"""HostCommand tests (spec A.4)."""

import json

from host_contracts.command import HostCommand
from host_contracts.entity_ref import HostEntityRef


def _roundtrip(obj):
    return type(obj).from_dict(json.loads(json.dumps(obj.to_dict())))


def test_move_command_round_trips_all_fields():  # TC-C02
    cmd = HostCommand(
        command_id="cmd-001",
        document_id="drawing-001",
        mode="EXECUTE",
        operation="move.v1",
        target_native_refs=[HostEntityRef(document_id="drawing-001", native_id="2AF")],
        arguments={"displacement": {"x": 500, "y": 0, "z": 0}},
        preconditions=[{"type": "revision", "expected": 100}],
        idempotency_key="move-task-001-unit-001",
        deadline_at="2026-08-26T15:00:00Z",
    )
    restored = _roundtrip(cmd)
    assert restored == cmd
    assert restored.validate() == []


def test_execute_requires_idempotency_key():  # TC-C03
    cmd = HostCommand(command_id="c1", mode="EXECUTE", operation="move.v1")
    errors = cmd.validate()
    assert any("idempotency_key" in e for e in errors)


def test_read_does_not_require_idempotency_key():  # TC-C04
    cmd = HostCommand(command_id="c2", mode="READ", operation="context.current_selection")
    assert cmd.validate() == []


def test_view_does_not_require_idempotency_key():
    cmd = HostCommand(command_id="c3", mode="VIEW", operation="view.fit_entities")
    assert cmd.validate() == []


def test_verify_does_not_require_idempotency_key():
    cmd = HostCommand(command_id="c4", mode="VERIFY", operation="verify.move.v1")
    assert cmd.validate() == []


def test_execute_with_idempotency_key_is_valid():
    cmd = HostCommand(
        command_id="c5", mode="EXECUTE", operation="move.v1", idempotency_key="k-1"
    )
    assert cmd.validate() == []


def test_invalid_mode_is_rejected():
    cmd = HostCommand(command_id="c6", mode="NONSENSE", operation="move.v1")
    assert any("mode" in e for e in cmd.validate())


def test_unknown_field_in_command_is_ignored():
    cmd = HostCommand.from_dict(
        {
            "command_id": "c7",
            "document_id": "drawing-001",
            "mode": "READ",
            "operation": "context.current_document",
            "future_field": 42,
        }
    )
    assert "future_field" not in cmd.to_dict()
