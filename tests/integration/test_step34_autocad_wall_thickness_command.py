from __future__ import annotations

import json

import pytest

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher


class WallThicknessTransport:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []
        self.opened = False

    async def open(self) -> None:
        self.opened = True

    async def exchange(self, payload: bytes, *, timeout_s: float | None = None) -> bytes:
        request = json.loads(payload)
        command = request["payload"]
        self.payloads.append(command)

        if command["operation"] == "context.current_document":
            result = {
                "command_id": command["command_id"],
                "status": "OK",
                "payload": {
                    "documentId": "Drawing1.dwg",
                    "documentName": "Drawing1.dwg",
                    "revision": 7,
                },
                "revision_after": 7,
            }
        elif command["operation"] == "set_wall_thickness.v1":
            result = {
                "command_id": command["command_id"],
                "status": "OK",
                "payload": {
                    "updated": 1,
                    "thickness": {
                        "A31": {"value": 300.0, "unit": "mm"},
                    },
                },
                "revision_after": 8,
                "verification": {
                    "ok": True,
                    "message": "all entities verified",
                    "details": {},
                },
            }
        else:  # pragma: no cover - test must not emit another operation
            raise AssertionError(f"unexpected operation: {command['operation']}")

        return json.dumps(
            {
                "request_id": request["request_id"],
                "status": "OK",
                "result": result,
            }
        ).encode()

    async def close(self) -> None:
        self.opened = False


@pytest.mark.asyncio
async def test_dispatcher_emits_exact_wall_thickness_host_command_without_step32_authority() -> None:
    transport = WallThicknessTransport()
    dispatcher = CommandDispatcher(HostAdapter(transport=transport))

    result = await dispatcher.set_wall_thickness(
        ["A31"],
        300.0,
        idempotency_key="step34-key",
        revision=7,
    )

    assert result.ok
    assert result.revision_after == 8
    assert result.verification is not None
    assert result.verification["ok"] is True

    command = transport.payloads[-1]
    assert command["mode"] == "EXECUTE"
    assert command["operation"] == "set_wall_thickness.v1"
    assert command["document_id"] == "Drawing1.dwg"
    assert command["target_native_refs"] == [
        {"document_id": "Drawing1.dwg", "native_id": "A31"}
    ]
    assert command["arguments"] == {
        "thickness": {"value": 300.0, "unit": "mm"}
    }
    assert command["preconditions"] == [{"type": "revision", "expected": 7}]
    assert command["idempotency_key"] == "step34-key"

    serialized = json.dumps(command, sort_keys=True)
    assert "grant_hash" not in serialized
    assert "approved_scope_hash" not in serialized
    assert "execution_slice_hash" not in serialized
    assert "ConstantWidth" not in serialized


@pytest.mark.asyncio
async def test_dispatcher_replays_successful_wall_thickness_by_idempotency_key() -> None:
    transport = WallThicknessTransport()
    dispatcher = CommandDispatcher(HostAdapter(transport=transport))

    first = await dispatcher.set_wall_thickness(
        ["A31"],
        300.0,
        idempotency_key="same-key",
        revision=7,
    )
    second = await dispatcher.set_wall_thickness(
        ["A31"],
        300.0,
        idempotency_key="same-key",
        revision=7,
    )

    assert first.ok
    assert second.ok
    assert first.replayed is False
    assert second.replayed is True
    assert second.command_id == first.command_id
    assert second.status == first.status
    assert second.payload == first.payload
    assert second.error == first.error
    assert second.revision_after == first.revision_after
    assert second.verification == first.verification
    assert [payload["operation"] for payload in transport.payloads] == [
        "context.current_document",
        "set_wall_thickness.v1",
    ]
