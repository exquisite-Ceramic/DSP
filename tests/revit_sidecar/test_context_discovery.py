"""Task 3：Revit runtime discovery 的配置 document / fresh Host identity 契约测试。"""

from __future__ import annotations

from copy import deepcopy

import pytest
import revit_sidecar


class _Transport:
    """记录 discovery 发出的 HostCommand，并返回调用方提供的 Host response。"""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.commands = []

    def request(self, command):
        """保存 exact READ command，返回隔离副本避免测试之间共享可变状态。"""

        self.commands.append(command)
        return deepcopy(self.response)


def _probe_type():
    """把尚未实现的新 discovery adapter 表现为明确 TDD RED，而非 collection error。"""

    probe_type = getattr(revit_sidecar, "RevitCurrentContextProbe", None)
    assert probe_type is not None, "RevitCurrentContextProbe 尚未实现"
    return probe_type


def _response(
    *,
    status: str = "OK",
    document_id: object = "DOC-CONFIGURED-1",
    host_instance_id: object = "revit-runtime-fresh-7",
    selected_elements: object | None = None,
) -> dict:
    """构造既有 HostResultEnvelope 形状，不给 discovery 额外发明 transport contract。"""

    return {
        "command_id": "DISCOVER-CTX-1",
        "status": status,
        "payload": {
            "document_id": document_id,
            "document_title": "Configured Wall Fixture",
            "host_instance_id": host_instance_id,
            "selected_elements": (
                [{"unique_id": "WALL-UNIQUE-1", "native_kind": "Wall"}]
                if selected_elements is None
                else selected_elements
            ),
        },
        "error": None if status == "OK" else {"code": "REVIT_HOST_ERROR"},
        "revision_after": 51,
        "verification": None,
        "replayed": False,
    }


def test_discovery_sends_existing_read_and_accepts_fresh_host_instance_identity() -> None:
    """discovery 只冻结 configured document；runtime id 必须来自本次 Host observation。"""

    transport = _Transport(_response())
    probe = _probe_type()(transport)

    observation = probe.discover(
        command_id="DISCOVER-CTX-1",
        document_id="DOC-CONFIGURED-1",
    )

    assert len(transport.commands) == 1
    command = transport.commands[0]
    assert command.command_id == "DISCOVER-CTX-1"
    assert command.document_id == "DOC-CONFIGURED-1"
    assert command.mode == "READ"
    assert command.operation == "context.current_selection"
    assert command.target_native_refs == []
    assert command.arguments == {}
    assert command.preconditions == []
    assert command.idempotency_key is None

    assert observation.document_id == "DOC-CONFIGURED-1"
    assert observation.host_instance_id == "revit-runtime-fresh-7"
    assert observation.document_title == "Configured Wall Fixture"
    assert observation.revision == 51
    assert observation.selected_elements[0].unique_id == "WALL-UNIQUE-1"


def test_discovery_rejects_host_error_without_accepting_payload_identity() -> None:
    """Host status 非 OK 时 payload 即使看似完整也不能成为 session authority。"""

    probe = _probe_type()(_Transport(_response(status="ERROR")))

    with pytest.raises(ValueError, match="REVIT_CONTEXT_READ_FAILED"):
        probe.discover(
            command_id="DISCOVER-CTX-1",
            document_id="DOC-CONFIGURED-1",
        )


def test_discovery_rejects_document_mismatch_against_configured_document() -> None:
    """transport locator 不能替代 document identity；Host 返回必须与配置 document 精确一致。"""

    probe = _probe_type()(
        _Transport(_response(document_id="DOC-OTHER"))
    )

    with pytest.raises(ValueError, match="REVIT_CONTEXT_DOCUMENT_MISMATCH"):
        probe.discover(
            command_id="DISCOVER-CTX-1",
            document_id="DOC-CONFIGURED-1",
        )


@pytest.mark.parametrize(
    ("host_instance_id", "selected_elements", "expected_code"),
    [
        ("", None, "REVIT_CONTEXT_HOST_MISMATCH"),
        (None, None, "REVIT_CONTEXT_HOST_MISMATCH"),
        (
            "revit-runtime-fresh-7",
            [{"native_kind": "Wall"}],
            "REVIT_CONTEXT_SELECTION_INVALID",
        ),
        (
            "revit-runtime-fresh-7",
            [{"unique_id": "WALL-UNIQUE-1"}],
            "REVIT_CONTEXT_SELECTION_INVALID",
        ),
    ],
)
def test_discovery_rejects_malformed_runtime_or_selected_native_identity(
    host_instance_id: object,
    selected_elements: object | None,
    expected_code: str,
) -> None:
    """fresh identity 允许未知，但一旦 Host 返回就必须满足与 strict read 相同的结构校验。"""

    probe = _probe_type()(
        _Transport(
            _response(
                host_instance_id=host_instance_id,
                selected_elements=selected_elements,
            )
        )
    )

    with pytest.raises(ValueError, match=expected_code):
        probe.discover(
            command_id="DISCOVER-CTX-1",
            document_id="DOC-CONFIGURED-1",
        )
