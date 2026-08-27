from __future__ import annotations

from pathlib import Path

import pytest

from host_contracts.result import HostCommandResult
from autocad_sidecar.adapter.context_adapter import ContextAdapter
from autocad_sidecar.adapter.model_adapter import ModelAdapter
from autocad_sidecar.adapter.view_adapter import ViewAdapter


class RecordingHost:
    def __init__(self) -> None:
        self.commands = []

    async def send_command(self, command):
        self.commands.append(command)
        return HostCommandResult(command_id=command.command_id, status="OK", payload={})


@pytest.mark.asyncio
async def test_context_adapter_emits_current_contract_fields():
    host = RecordingHost()
    adapter = ContextAdapter(host)

    await adapter.current_document()
    await adapter.current_selection()

    assert [(c.mode, c.operation) for c in host.commands] == [
        ("READ", "context.current_document"),
        ("READ", "context.current_selection"),
    ]
    assert all(c.arguments is None for c in host.commands)


@pytest.mark.asyncio
async def test_view_adapter_emits_current_contract_fields():
    host = RecordingHost()
    await ViewAdapter(host).fit(["2AF"])

    command = host.commands[-1]
    assert command.mode == "VIEW"
    assert command.operation == "view.fit_entities"
    assert command.arguments == {"handles": ["2AF"]}


@pytest.mark.asyncio
async def test_model_adapter_emits_current_contract_fields():
    host = RecordingHost()
    await ModelAdapter(host).move(
        ["2AF"], 5.0, 2.0, 1.0, idempotency_key="move-1", revision=100
    )

    command = host.commands[-1]
    assert command.mode == "EXECUTE"
    assert command.operation == "move.v1"
    assert command.arguments == {"handles": ["2AF"], "dx": 5.0, "dy": 2.0, "dz": 1.0}
    assert command.preconditions == [{"type": "revision", "expected": 100}]
    assert command.idempotency_key == "move-1"


def test_plugin_sources_use_current_contract_api_only():
    root = Path("hosts/autocad/plugin/AutoCAD.AgentHost")
    sources = {
        "serializer": (root / "Ipc/ContractSerializer.cs").read_text(encoding="utf-8"),
        "dispatcher": (root / "Ipc/RequestDispatcher.cs").read_text(encoding="utf-8"),
        "revision": (root / "Execution/RevisionGuard.cs").read_text(encoding="utf-8"),
        "document": (root / "Commands/Context/CurrentDocumentHandler.cs").read_text(encoding="utf-8"),
        "selection": (root / "Commands/Context/CurrentSelectionHandler.cs").read_text(encoding="utf-8"),
        "move": (root / "Commands/Model/MoveHandler.cs").read_text(encoding="utf-8"),
        "fit": (root / "Commands/View/FitEntitiesHandler.cs").read_text(encoding="utf-8"),
        "entities": (root / "Native/AutoCADEntityApi.cs").read_text(encoding="utf-8"),
        "resolver": (root / "Identity/HandleResolver.cs").read_text(encoding="utf-8"),
        "delta": (root / "ChangeCapture/HostDeltaBuilder.cs").read_text(encoding="utf-8"),
    }

    assert "Deserialize<RequestEnvelope>" in sources["serializer"]
    assert "ResponseEnvelope" in sources["serializer"]
    assert "command.Operation" in sources["dispatcher"]
    assert "RevisionAfter" in sources["dispatcher"]
    assert "ErrorShape" in sources["dispatcher"]
    assert "command.Preconditions" in sources["revision"]
    assert "command.Arguments" in sources["move"]
    assert "command.Arguments" in sources["fit"]
    assert "NativeId =" in sources["entities"]
    assert "NativeType =" in sources["entities"]
    assert "entityRef.NativeId" in sources["resolver"]
    assert "RevisionBefore" in sources["delta"]
    assert "RevisionAfter" in sources["delta"]

    forbidden = (
        "Deserialize<Envelope>",
        "PayloadAs<HostCommand>(envelope)",
        "command.CommandType",
        "command.Params",
        "command.Revision",
        "new HostError",
        "Ok = false",
        "Ok = true",
        "result.Revision =",
        "entityRef.Handle",
        "EntityRef = change.Value.EntityRef",
        "Revision = (int)Native.AcNative.ActiveDocumentRevision()",
    )
    combined = "\n".join(sources.values())
    for token in forbidden:
        assert token not in combined, token
