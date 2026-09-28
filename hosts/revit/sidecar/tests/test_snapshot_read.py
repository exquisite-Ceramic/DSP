"""Revit 墙厚独立 snapshot READ port 的严格 correlation 契约。"""

from __future__ import annotations

from copy import deepcopy

import pytest
import revit_sidecar


class _Transport:
    """记录 HostCommand，并返回测试提供的 Host response。"""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.commands = []

    def request(self, command):
        self.commands.append(command)
        return deepcopy(self.response)


def _port_type():
    """把“能力尚未实现”表现为 RED assertion，而不是 collection error。"""
    port_type = getattr(revit_sidecar, "RevitWallThicknessSnapshotReadPort", None)
    assert port_type is not None, "RevitWallThicknessSnapshotReadPort is not implemented"
    return port_type


def _response(
    *,
    document_id: str = "DOC-REVIT-1",
    host_instance_id: str = "revit-runtime-1",
    wall_unique_id: str = "WALL-UNIQUE-1",
    revision_before: int = 42,
    revision_after: int = 42,
    top_level_revision: int = 42,
    wall_thickness_mm: float = 300.0,
) -> dict:
    return {
        "command_id": "SNAP-1",
        "status": "OK",
        "payload": {
            "document_id": document_id,
            "host_instance_id": host_instance_id,
            "wall_unique_id": wall_unique_id,
            "wall_type_unique_id": "WALL-TYPE-UNIQUE-1",
            "native_kind": "Wall",
            "builtin_category": "OST_Walls",
            "wall_thickness_mm": wall_thickness_mm,
            "location_signature": "Line|0|0|0|10|0|0",
            "relationship_signature": (
                "same-type=;inserts=;join-0=;join-1=;unsupported=;associativity=True"
            ),
            "revision_before": revision_before,
            "revision_after": revision_after,
        },
        "error": None,
        "revision_after": top_level_revision,
        "verification": None,
        "replayed": False,
    }


def _read(port):
    return port.read(
        command_id="SNAP-1",
        document_id="DOC-REVIT-1",
        host_instance_id="revit-runtime-1",
        wall_unique_id="WALL-UNIQUE-1",
        expected_revision=42,
    )


def test_snapshot_read_builds_narrow_read_only_command_and_returns_evidence() -> None:
    """独立 READ 只携带 exact document/Wall target，不携带 mutation shape。"""
    transport = _Transport(_response())
    port = _port_type()(transport)

    evidence = _read(port)

    assert len(transport.commands) == 1
    command = transport.commands[0]
    assert command.command_id == "SNAP-1"
    assert command.document_id == "DOC-REVIT-1"
    assert command.mode == "READ"
    assert command.operation == "read_wall_thickness_snapshot"
    assert len(command.target_native_refs) == 1
    assert command.target_native_refs[0].document_id == "DOC-REVIT-1"
    assert command.target_native_refs[0].native_id == "WALL-UNIQUE-1"
    assert command.target_native_refs[0].native_type == "Wall"
    assert command.arguments == {}
    assert command.preconditions == []
    assert command.idempotency_key is None

    assert evidence.document_id == "DOC-REVIT-1"
    assert evidence.host_instance_id == "revit-runtime-1"
    assert evidence.wall_unique_id == "WALL-UNIQUE-1"
    assert evidence.wall_type_unique_id == "WALL-TYPE-UNIQUE-1"
    assert evidence.native_kind == "Wall"
    assert evidence.builtin_category == "OST_Walls"
    assert evidence.wall_thickness_mm == pytest.approx(300.0, abs=1e-6)
    assert evidence.revision_before == 42
    assert evidence.revision_after == 42
    assert evidence.location_signature
    assert evidence.relationship_signature


@pytest.mark.parametrize(
    ("response_kwargs", "expected_code"),
    [
        ({"document_id": "DOC-OTHER"}, "REVIT_SNAPSHOT_DOCUMENT_MISMATCH"),
        ({"host_instance_id": "revit-runtime-other"}, "REVIT_SNAPSHOT_HOST_MISMATCH"),
        ({"wall_unique_id": "WALL-OTHER"}, "REVIT_SNAPSHOT_TARGET_MISMATCH"),
    ],
)
def test_snapshot_read_rejects_identity_mismatch(
    response_kwargs: dict,
    expected_code: str,
) -> None:
    """verification evidence 必须绑定 exact document/host/native target。"""
    port = _port_type()(_Transport(_response(**response_kwargs)))

    with pytest.raises(ValueError, match=expected_code):
        _read(port)


@pytest.mark.parametrize(
    "response_kwargs",
    [
        {"revision_before": 41},
        {"revision_after": 43},
        {"top_level_revision": 43},
    ],
)
def test_snapshot_read_requires_exact_committed_revision_window(
    response_kwargs: dict,
) -> None:
    """READ before/after 与 HostResult 顶层 revision 必须都等于 expected_revision。"""
    port = _port_type()(_Transport(_response(**response_kwargs)))

    with pytest.raises(ValueError, match="REVIT_SNAPSHOT_REVISION_MISMATCH"):
        _read(port)


@pytest.mark.parametrize("expected_revision", [-1, True, 1.5, "42"])
def test_snapshot_read_rejects_invalid_expected_revision(expected_revision) -> None:
    """调用方必须提供真实非负 committed revision，不能隐式转换。"""
    port = _port_type()(_Transport(_response()))

    with pytest.raises(ValueError, match="REVIT_SNAPSHOT_EXPECTED_REVISION_INVALID"):
        port.read(
            command_id="SNAP-1",
            document_id="DOC-REVIT-1",
            host_instance_id="revit-runtime-1",
            wall_unique_id="WALL-UNIQUE-1",
            expected_revision=expected_revision,
        )


@pytest.mark.parametrize("wall_thickness_mm", [0.0, -1.0, float("inf"), float("nan")])
def test_snapshot_read_rejects_invalid_wall_thickness(wall_thickness_mm: float) -> None:
    """Host evidence 中的墙厚必须是有限正 mm 值。"""
    port = _port_type()(
        _Transport(_response(wall_thickness_mm=wall_thickness_mm))
    )

    with pytest.raises(ValueError, match="REVIT_SNAPSHOT_THICKNESS_INVALID"):
        _read(port)
