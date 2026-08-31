from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest

from revit_sidecar.model_adapter import RevitHostAdapter
from revit_sidecar.named_pipe import NamedPipeTransport


class FakePipeEndpoint:
    def __init__(self) -> None:
        self.received_packet: bytes | None = None

    def exchange(self, packet: bytes) -> bytes:
        self.received_packet = packet
        (length,) = struct.unpack("<I", packet[:4])
        request_body = packet[4:]
        assert length == len(request_body)
        request = json.loads(request_body.decode("utf-8"))
        assert request["operation"] == "set_wall_thickness"

        response_body = json.dumps(
            {"command_id": request["command_id"], "status": "OK", "revision_after": 11},
            separators=(",", ":"),
        ).encode("utf-8")
        return struct.pack("<I", len(response_body)) + response_body


def _command(*, thickness_mm: float = 300.0):
    return RevitHostAdapter.build_set_wall_thickness_command(
        command_id="CMD-REVIT-001",
        document_id="DOC-REVIT-001",
        wall_unique_id="wall-unique-id",
        expected_revision=10,
        thickness_mm=thickness_mm,
        idempotency_key="IDEMP-REVIT-001",
    )


def test_revit_adapter_builds_only_the_existing_host_command_contract() -> None:
    command = _command()

    assert command.mode == "EXECUTE"
    assert command.operation == "set_wall_thickness"
    assert command.document_id == "DOC-REVIT-001"
    assert command.idempotency_key == "IDEMP-REVIT-001"
    assert len(command.target_native_refs) == 1

    target = command.target_native_refs[0]
    assert target.document_id == "DOC-REVIT-001"
    assert target.native_id == "wall-unique-id"
    assert target.native_type == "Wall"
    assert command.arguments == {"thickness": {"value": 300.0, "unit": "mm"}}
    assert command.preconditions == [{"revision": 10}]
    assert command.validate() == []

    wire = json.dumps(command.to_dict(), sort_keys=True)
    for forbidden in (
        "ifc:IfcWall",
        "ApprovalScopeBoundary",
        "ExecutionGrant",
        "WallType",
        "CompoundStructure",
        "ElementId",
    ):
        assert forbidden not in wire


@pytest.mark.parametrize("thickness_mm", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_revit_adapter_rejects_non_positive_or_non_finite_thickness(
    thickness_mm: float,
) -> None:
    with pytest.raises(ValueError, match="thickness_mm"):
        _command(thickness_mm=thickness_mm)


def test_named_pipe_transport_uses_little_endian_length_prefixed_json() -> None:
    endpoint = FakePipeEndpoint()
    transport = NamedPipeTransport(endpoint)

    result = transport.request(_command())

    assert result == {
        "command_id": "CMD-REVIT-001",
        "status": "OK",
        "revision_after": 11,
    }
    assert endpoint.received_packet is not None
    (length,) = struct.unpack("<I", endpoint.received_packet[:4])
    body = endpoint.received_packet[4:]
    assert length == len(body)
    assert json.loads(body.decode("utf-8"))["target_native_refs"] == [
        {
            "document_id": "DOC-REVIT-001",
            "native_id": "wall-unique-id",
            "native_type": "Wall",
        }
    ]


def test_revit_sidecar_has_no_grpc_mcp_or_transport_selector_surface() -> None:
    package_root = Path(__file__).resolve().parents[1] / "src/revit_sidecar"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in package_root.rglob("*.py")
        if path.is_file()
    ).lower()

    assert "import grpc" not in source
    assert "from grpc" not in source
    assert "mcp" not in source
    assert "transport_selector" not in source
