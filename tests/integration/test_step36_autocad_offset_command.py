from __future__ import annotations

import json
import math

import pytest
from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.capability.profile import parse_design_capability
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from autocad_sidecar.mcp_server import build_tool_definitions


class OffsetTransport:
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
        elif command["operation"] == "offset.v1":
            result = {
                "command_id": command["command_id"],
                "status": "OK",
                "payload": {
                    "createdEntityRefs": [
                        {
                            "document_id": "Drawing1.dwg",
                            "native_id": "3D7",
                            "native_type": "Polyline",
                        }
                    ]
                },
                "revision_after": 8,
                "verification": {
                    "ok": True,
                    "message": "offset entity created",
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


def test_profile_defaults_legacy_existence_effects_to_empty() -> None:
    profile = parse_design_capability(
        {
            "name": "legacy.move",
            "inputSchema": {"type": "object", "properties": {}},
            "_meta": {
                "com.company.design/operation": "move.v1",
                "com.company.design/category": "MODEL_OPERATION",
                "com.company.design/entities": ["LWPOLYLINE"],
                "com.company.design/effects": ["PLACEMENT"],
            },
        },
        provider_server="autocad-local",
    )

    assert profile.existence_effects == ()


def test_offset_tool_advertises_create_claim_without_platform_authority() -> None:
    tool = next(item for item in build_tool_definitions() if item["name"] == "cad.offset")
    profile = parse_design_capability(tool, provider_server="autocad-local")

    assert profile.canonical_operation == "offset.v1"
    assert profile.entity_constraints == ("LWPOLYLINE",)
    assert profile.effects == ()
    assert profile.existence_effects == ("CREATE",)
    assert tool["_meta"]["com.company.design/existence_effects"] == ["CREATE"]

    serialized = json.dumps(tool, sort_keys=True)
    for forbidden in (
        "CreationRule",
        "grant_hash",
        "approved_scope_hash",
        "execution_slice_hash",
        "ifc:IfcWall",
        "RULE-OFFSET-WALL",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_dispatcher_emits_exact_offset_host_command_without_scope_authority() -> None:
    transport = OffsetTransport()
    dispatcher = CommandDispatcher(HostAdapter(transport=transport))

    result = await dispatcher.offset(
        ["2C6"],
        {"value": 300.0, "unit": "mm"},
        {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"},
        idempotency_key="step36-offset-1",
        revision=7,
    )

    assert result.ok
    assert result.revision_after == 8

    command = transport.payloads[-1]
    assert command["mode"] == "EXECUTE"
    assert command["operation"] == "offset.v1"
    assert command["document_id"] == "Drawing1.dwg"
    assert command["target_native_refs"] == [
        {"document_id": "Drawing1.dwg", "native_id": "2C6"}
    ]
    assert command["arguments"] == {
        "distance": {"value": 300.0, "unit": "mm"},
        "sidePoint": {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"},
    }
    assert command["preconditions"] == [{"type": "revision", "expected": 7}]
    assert command["idempotency_key"] == "step36-offset-1"

    serialized = json.dumps(command, sort_keys=True)
    for forbidden in (
        "CreationRule",
        "grant_hash",
        "approved_scope_hash",
        "execution_slice_hash",
        "ifc:IfcWall",
        "RULE-OFFSET-WALL",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_dispatcher_replays_successful_offset_by_idempotency_key() -> None:
    transport = OffsetTransport()
    dispatcher = CommandDispatcher(HostAdapter(transport=transport))
    distance = {"value": 300.0, "unit": "mm"}
    side_point = {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"}

    first = await dispatcher.offset(
        ["2C6"],
        distance,
        side_point,
        idempotency_key="same-offset-key",
        revision=7,
    )
    second = await dispatcher.offset(
        ["2C6"],
        distance,
        side_point,
        idempotency_key="same-offset-key",
        revision=7,
    )

    assert first.ok
    assert second.ok
    assert first.replayed is False
    assert second.replayed is True
    assert second.command_id == first.command_id
    assert [payload["operation"] for payload in transport.payloads] == [
        "context.current_document",
        "offset.v1",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handles", "distance", "side_point"),
    [
        ([], {"value": 300.0, "unit": "mm"}, {"x": 1.0, "y": 2.0, "z": 0.0, "unit": "mm"}),
        (["A", "B"], {"value": 300.0, "unit": "mm"}, {"x": 1.0, "y": 2.0, "z": 0.0, "unit": "mm"}),
        (["A"], {"value": 0.0, "unit": "mm"}, {"x": 1.0, "y": 2.0, "z": 0.0, "unit": "mm"}),
        (["A"], {"value": math.inf, "unit": "mm"}, {"x": 1.0, "y": 2.0, "z": 0.0, "unit": "mm"}),
        (["A"], {"value": 300.0, "unit": "m"}, {"x": 1.0, "y": 2.0, "z": 0.0, "unit": "mm"}),
        (["A"], {"value": 300.0, "unit": "mm"}, {"x": math.nan, "y": 2.0, "z": 0.0, "unit": "mm"}),
        (["A"], {"value": 300.0, "unit": "mm"}, {"x": 1.0, "y": 2.0, "z": 0.0, "unit": "m"}),
    ],
)
async def test_offset_rejects_invalid_native_arguments(handles, distance, side_point) -> None:
    transport = OffsetTransport()
    dispatcher = CommandDispatcher(HostAdapter(transport=transport))

    with pytest.raises((TypeError, ValueError)):
        await dispatcher.offset(
            handles,
            distance,
            side_point,
            idempotency_key="invalid-offset",
            revision=7,
        )

    assert transport.payloads == []
