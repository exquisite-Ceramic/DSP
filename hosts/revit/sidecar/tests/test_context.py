"""Revit 当前上下文 READ port 的严格 transport/evidence 契约。"""

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
    port_type = getattr(revit_sidecar, "RevitContextReadPort", None)
    assert port_type is not None, "RevitContextReadPort is not implemented"
    return port_type


def _response(
    *,
    document_id: str = "DOC-REVIT-1",
    host_instance_id: str = "revit-runtime-1",
    revision: int = 41,
    selected_elements: list[dict] | None = None,
) -> dict:
    return {
        "command_id": "CTX-1",
        "status": "OK",
        "payload": {
            "document_id": document_id,
            "document_title": "Wall Fixture",
            "host_instance_id": host_instance_id,
            "selected_elements": selected_elements
            if selected_elements is not None
            else [{"unique_id": "WALL-UNIQUE-1", "native_kind": "Wall"}],
        },
        "error": None,
        "revision_after": revision,
        "verification": None,
        "replayed": False,
    }


def test_context_read_builds_read_only_command_and_returns_exact_evidence() -> None:
    """context.current_selection 只返回 Host evidence，不夹带 semantic mapping。"""
    transport = _Transport(_response())
    port = _port_type()(transport)

    observation = port.read(
        command_id="CTX-1",
        document_id="DOC-REVIT-1",
        host_instance_id="revit-runtime-1",
    )

    assert len(transport.commands) == 1
    command = transport.commands[0]
    assert command.command_id == "CTX-1"
    assert command.document_id == "DOC-REVIT-1"
    assert command.mode == "READ"
    assert command.operation == "context.current_selection"
    assert command.target_native_refs == []
    assert command.arguments == {}
    assert command.preconditions == []
    assert command.idempotency_key is None

    assert observation.document_id == "DOC-REVIT-1"
    assert observation.host_instance_id == "revit-runtime-1"
    assert observation.document_title == "Wall Fixture"
    assert observation.revision == 41
    assert len(observation.selected_elements) == 1
    assert observation.selected_elements[0].unique_id == "WALL-UNIQUE-1"
    assert observation.selected_elements[0].native_kind == "Wall"


@pytest.mark.parametrize(
    ("response_patch", "expected_code"),
    [
        ({"document_id": "DOC-OTHER"}, "REVIT_CONTEXT_DOCUMENT_MISMATCH"),
        ({"host_instance_id": "revit-runtime-other"}, "REVIT_CONTEXT_HOST_MISMATCH"),
    ],
)
def test_context_read_rejects_document_or_host_identity_mismatch(
    response_patch: dict[str, str],
    expected_code: str,
) -> None:
    """调用方冻结的 document/host identity 必须与 Host response 精确一致。"""
    response = _response(
        document_id=response_patch.get("document_id", "DOC-REVIT-1"),
        host_instance_id=response_patch.get("host_instance_id", "revit-runtime-1"),
    )
    port = _port_type()(_Transport(response))

    with pytest.raises(ValueError, match=expected_code):
        port.read(
            command_id="CTX-1",
            document_id="DOC-REVIT-1",
            host_instance_id="revit-runtime-1",
        )


@pytest.mark.parametrize("revision", [-1, True, "41", None])
def test_context_read_requires_real_non_negative_top_level_revision(revision) -> None:
    """context evidence 的 revision 只能来自 HostResultEnvelope 顶层 revision_after。"""
    port = _port_type()(_Transport(_response(revision=revision)))

    with pytest.raises(ValueError, match="REVIT_CONTEXT_REVISION_INVALID"):
        port.read(
            command_id="CTX-1",
            document_id="DOC-REVIT-1",
            host_instance_id="revit-runtime-1",
        )


@pytest.mark.parametrize(
    "selected_elements",
    [
        [{"native_kind": "Wall"}],
        [{"unique_id": "WALL-UNIQUE-1"}],
        [{"unique_id": "", "native_kind": "Wall"}],
        "not-a-list",
    ],
)
def test_context_read_rejects_malformed_selected_native_identity(selected_elements) -> None:
    """sidecar 只验证 native identity 结构；exactly-one product rule 留给上层 Task 5。"""
    port = _port_type()(
        _Transport(_response(selected_elements=selected_elements))
    )

    with pytest.raises(ValueError, match="REVIT_CONTEXT_SELECTION_INVALID"):
        port.read(
            command_id="CTX-1",
            document_id="DOC-REVIT-1",
            host_instance_id="revit-runtime-1",
        )
