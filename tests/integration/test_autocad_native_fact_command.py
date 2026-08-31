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


def _snapshot_with_properties(properties: dict[str, object]) -> dict[str, object]:
    return {
        **SNAPSHOT,
        "entities": [
            {
                **SNAPSHOT["entities"][0],
                "properties": properties,
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
async def test_dispatcher_normalizes_lwpolyline_constant_width_as_property_fact():
    snapshot = _snapshot_with_properties(
        {
            "constantWidth": {
                "value": 200.0,
                "unit": "mm",
            }
        }
    )
    transport = NativeFactTransport(snapshot=snapshot)
    dispatcher = CommandDispatcher(HostAdapter(transport=transport))

    batch = await dispatcher.extract_design_facts(["A31"])

    properties = [fact for fact in batch.facts if fact.fact_kind is FactKind.PROPERTY]
    assert len(properties) == 1
    fact = properties[0]
    assert fact.predicate == "constant_width"
    assert fact.value == 200.0
    assert fact.unit == "mm"
    assert fact.source_scheme == "autocad.property"
    assert fact.source_code == "LWPOLYLINE.ConstantWidth"
    assert fact.subject_native_ref.native_kind == "LWPOLYLINE"


@pytest.mark.asyncio
async def test_dispatcher_rejects_non_positive_constant_width():
    snapshot = _snapshot_with_properties(
        {"constantWidth": {"value": -1.0, "unit": "mm"}}
    )
    dispatcher = CommandDispatcher(HostAdapter(transport=NativeFactTransport(snapshot=snapshot)))

    with pytest.raises(ValueError, match="constantWidth.*positive"):
        await dispatcher.extract_design_facts(["A31"])


@pytest.mark.asyncio
async def test_dispatcher_rejects_non_mm_constant_width_unit():
    snapshot = _snapshot_with_properties(
        {"constantWidth": {"value": 200.0, "unit": "m"}}
    )
    dispatcher = CommandDispatcher(HostAdapter(transport=NativeFactTransport(snapshot=snapshot)))

    with pytest.raises(ValueError, match="constantWidth.*mm"):
        await dispatcher.extract_design_facts(["A31"])


@pytest.mark.asyncio
async def test_dispatcher_rejects_unknown_native_property():
    snapshot = _snapshot_with_properties(
        {"unknown": {"value": 1.0, "unit": "mm"}}
    )
    dispatcher = CommandDispatcher(HostAdapter(transport=NativeFactTransport(snapshot=snapshot)))

    with pytest.raises(ValueError, match="properties contains unknown fields.*unknown"):
        await dispatcher.extract_design_facts(["A31"])


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
