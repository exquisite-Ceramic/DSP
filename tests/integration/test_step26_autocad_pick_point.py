from __future__ import annotations

from pathlib import Path

import pytest

from host_contracts.result import HostCommandResult

from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from autocad_sidecar.mcp_server import build_tool_definitions


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "hosts" / "autocad" / "plugin" / "AutoCAD.AgentHost"


class FakeInteractionHost:
    def __init__(self) -> None:
        self.commands = []
        self.prompt_count = 0

    async def send_command(self, command):
        self.commands.append(command)
        if command.operation == "context.current_document":
            return HostCommandResult(
                command_id=command.command_id,
                status="OK",
                payload={"documentId": "drawing-01", "revision": 7},
            )
        if command.operation == "interaction.pick_point":
            self.prompt_count += 1
            return HostCommandResult(
                command_id=command.command_id,
                status="OK",
                payload={"point": [100.0, 200.0, 0.0]},
            )
        raise AssertionError(f"unexpected operation: {command.operation}")


def test_autocad_provider_catalog_exposes_pick_point_as_interaction() -> None:
    definitions = {item["name"]: item for item in build_tool_definitions()}

    tool = definitions["interaction.pick_point"]
    assert tool["_meta"]["com.company.design/category"] == "INTERACTION"
    assert tool["_meta"]["com.company.design/operation"] == "interaction.pick_point.v1"
    assert "idempotency_key" in tool["inputSchema"]["properties"]
    assert tool["inputSchema"]["required"] == ["idempotency_key"]


@pytest.mark.asyncio
async def test_dispatcher_sends_interaction_host_command_with_stable_idempotency_key() -> None:
    host = FakeInteractionHost()
    dispatcher = CommandDispatcher(host=host)

    result = await dispatcher.pick_point(
        idempotency_key="task-26:pick-point:point",
        prompt="Pick a point",
    )

    assert result.ok
    assert result.payload == {"point": [100.0, 200.0, 0.0]}
    command = [c for c in host.commands if c.operation == "interaction.pick_point"][0]
    assert command.mode == "INTERACTION"
    assert command.document_id == "drawing-01"
    assert command.idempotency_key == "task-26:pick-point:point"
    assert command.arguments == {"prompt": "Pick a point"}


@pytest.mark.asyncio
async def test_same_pick_point_key_replays_without_second_native_prompt() -> None:
    host = FakeInteractionHost()
    dispatcher = CommandDispatcher(host=host)

    first = await dispatcher.pick_point(
        idempotency_key="task-26:pick-point:point",
        prompt="Pick a point",
    )
    second = await dispatcher.pick_point(
        idempotency_key="task-26:pick-point:point",
        prompt="Pick a point",
    )

    assert first.ok and second.ok
    assert host.prompt_count == 1
    assert second.payload == {"point": [100.0, 200.0, 0.0]}


def test_pick_point_plugin_handler_is_registered_and_respects_native_boundary() -> None:
    registry = (
        PLUGIN / "Commands" / "HostCommandHandler.cs"
    ).read_text(encoding="utf-8")
    handler_path = PLUGIN / "Commands" / "Interaction" / "PickPointHandler.cs"
    native_path = PLUGIN / "Native" / "AutoCADInteractionApi.cs"

    assert handler_path.is_file()
    assert native_path.is_file()
    handler = handler_path.read_text(encoding="utf-8")
    native = native_path.read_text(encoding="utf-8")

    assert "Register(new Interaction.PickPointHandler())" in registry
    assert 'CommandType => "interaction.pick_point"' in handler
    assert "Autodesk." not in handler
    assert "using Autodesk.AutoCAD" in native
    assert "GetPoint" in native
    assert "point = new[]" in handler
