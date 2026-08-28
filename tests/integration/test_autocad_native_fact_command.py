from __future__ import annotations

import json

import pytest

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from autocad_sidecar.mcp_server import build_tool_definitions
from design_fact_contracts import FactKind


SNAPSHOT = {
    "hostInstanceId": "acad-session-1",
    "documentId": "C:/models/demo.dwg",
    "revision": 7,
    "entities": [
        {
            "nativeId": "A31",
            "nativeKind": "LWPOLYLINE",
            "layer": "A-WALL",
            "bounds": {
                "min": {"x": 0.0, "y": 1.0, "z": 0.0},
                "max": {"x": 10.0, "y": 2.0, "z": 3.0},
            },
        }
    ],
}


class NativeFactTransport:
    def __init__(self, *, snapshot=None, error_message: str | None = None):
        self.snapshot = SNAPSHOT if snapshot is None else snapshot
        self.error_message = error_message
        self.payloads: list[bytes] = []
        self.opened = False

    async def open(self) -> None:
        self.opened = True

    async def exchange(self, payload: bytes, *, timeout_s: float | None = None) -> bytes:
        self.payloads.append(payload)
        request = json.loads(payload)
        command = request["payload"]

        if self.error_message is not None:
            result = {
                "command_id": command["command_id"],
                "status": "ERROR",
                "error": {
                    "error_code": "NATIVE_READ_FAILED",
                    "category": "EXECUTION",
                    "message": self.error_message,
                    "retryable": "NEVER",
                },
            }
        else:
            result = {
                "command_id": command["command_id"],
                "status": "OK",
                "payload": self.snapshot,
            }

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
async def test_dispatcher_reads_native_snapshot_and_normalizes_design_facts():
    transport = NativeFactTransport()
    dispatcher = CommandDispatcher(HostAdapter(transport=transport))

    batch = await dispatcher.extract_design_facts(["A31"])

    sent = json.loads(transport.payloads[-1])["payload"]
    assert sent["mode"] == "READ"
    assert sent["operation"] == "design.extract_native_snapshot"
    assert sent["arguments"] == {"handles": ["A31"]}

    assert [fact.fact_kind for fact in batch.facts] == [
        FactKind.IDENTITY,
        FactKind.CLASSIFICATION,
        FactKind.BOUNDS,
    ]
    assert batch.facts[1].source_scheme == "autocad.layer"
    assert batch.facts[1].source_code == "A-WALL"


@pytest.mark.asyncio
async def test_dispatcher_preserves_host_error_message():
    transport = NativeFactTransport(error_message="unable to resolve readable AutoCAD entity handle: BAD")
    dispatcher = CommandDispatcher(HostAdapter(transport=transport))

    with pytest.raises(RuntimeError, match="unable to resolve readable AutoCAD entity handle: BAD"):
        await dispatcher.extract_design_facts(["BAD"])


@pytest.mark.asyncio
async def test_dispatcher_does_not_repair_malformed_successful_snapshot():
    transport = NativeFactTransport(snapshot={"hostInstanceId": "acad-session-1"})
    dispatcher = CommandDispatcher(HostAdapter(transport=transport))

    with pytest.raises(ValueError, match="snapshot"):
        await dispatcher.extract_design_facts(["A31"])


def test_step19_does_not_expand_host_mcp_tool_catalog():
    names = {tool["name"] for tool in build_tool_definitions()}

    assert "design.extract_native_snapshot" not in names
    assert "design.extract_facts" not in names
