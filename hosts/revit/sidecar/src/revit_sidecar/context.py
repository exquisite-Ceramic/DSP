"""Revit 当前上下文的严格只读 transport/evidence 适配器；locator 不承担 Host 身份证明。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from host_contracts import HostCommand


def _fail(code: str, message: str) -> None:
    """以稳定错误码拒绝不能作为权威上下文证据的 Host response。"""

    raise ValueError(f"{code}: {message}")


def _mapping(value: object, *, code: str, field_name: str) -> Mapping:
    """要求 Host response 的结构字段保持 mapping 形状。"""

    if not isinstance(value, Mapping):
        _fail(code, f"{field_name} must be a mapping")
    return value


def _non_empty_string(value: object, *, code: str, field_name: str) -> str:
    """读取并规范化 Host 返回的非空字符串 identity 字段。"""

    if not isinstance(value, str) or not value.strip():
        _fail(code, f"{field_name} must be a non-empty string")
    return value.strip()


def _revision(response: Mapping) -> int:
    """只接受 HostResultEnvelope 顶层真实非负 revision_after。"""

    value = response.get("revision_after")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _fail(
            "REVIT_CONTEXT_REVISION_INVALID",
            "response.revision_after must be a real non-negative integer",
        )
    return value


@dataclass(frozen=True, slots=True)
class RevitSelectedElement:
    """Host context 中一个原生选择实体的最小 identity evidence。"""

    unique_id: str
    native_kind: str


@dataclass(frozen=True, slots=True)
class RevitContextObservation:
    """一次 context.current_selection READ 的已验证 Host evidence。"""

    document_id: str
    document_title: str
    host_instance_id: str
    revision: int
    selected_elements: tuple[RevitSelectedElement, ...]


def _context_command(*, command_id: str, document_id: str) -> HostCommand:
    """构造既有 context.current_selection READ，不为 discovery 发明第二套 Host 命令。"""

    normalized_command_id = _non_empty_string(
        command_id,
        code="REVIT_CONTEXT_REQUEST_INVALID",
        field_name="command_id",
    )
    normalized_document_id = _non_empty_string(
        document_id,
        code="REVIT_CONTEXT_REQUEST_INVALID",
        field_name="document_id",
    )
    command = HostCommand(
        command_id=normalized_command_id,
        document_id=normalized_document_id,
        mode="READ",
        operation="context.current_selection",
        target_native_refs=[],
        arguments={},
        preconditions=[],
        idempotency_key=None,
    )
    validation_errors = command.validate()
    if validation_errors:
        _fail(
            "REVIT_CONTEXT_REQUEST_INVALID",
            f"HostCommand invalid: {validation_errors}",
        )
    return command


def _parse_context_response(
    raw_response: object,
    *,
    document_id: str,
    expected_host_instance_id: str | None,
) -> RevitContextObservation:
    """共享解析 Host context evidence；strict read 与 discovery 只在 host 预期值上不同。"""

    response = _mapping(
        raw_response,
        code="REVIT_CONTEXT_READ_FAILED",
        field_name="response",
    )
    if response.get("status") != "OK":
        _fail(
            "REVIT_CONTEXT_READ_FAILED",
            f"unsupported Host status: {response.get('status')!r}",
        )

    payload = _mapping(
        response.get("payload"),
        code="REVIT_CONTEXT_READ_FAILED",
        field_name="response.payload",
    )
    actual_document_id = _non_empty_string(
        payload.get("document_id"),
        code="REVIT_CONTEXT_DOCUMENT_MISMATCH",
        field_name="payload.document_id",
    )
    if actual_document_id != document_id:
        _fail(
            "REVIT_CONTEXT_DOCUMENT_MISMATCH",
            "Host document_id does not match the requested document",
        )

    actual_host_instance_id = _non_empty_string(
        payload.get("host_instance_id"),
        code="REVIT_CONTEXT_HOST_MISMATCH",
        field_name="payload.host_instance_id",
    )
    if (
        expected_host_instance_id is not None
        and actual_host_instance_id != expected_host_instance_id
    ):
        _fail(
            "REVIT_CONTEXT_HOST_MISMATCH",
            "Host runtime identity does not match the requested runtime",
        )

    document_title = payload.get("document_title")
    if not isinstance(document_title, str):
        _fail(
            "REVIT_CONTEXT_READ_FAILED",
            "payload.document_title must be a string",
        )
    selected = payload.get("selected_elements")
    if not isinstance(selected, list):
        _fail(
            "REVIT_CONTEXT_SELECTION_INVALID",
            "payload.selected_elements must be a list",
        )

    observations: list[RevitSelectedElement] = []
    for index, item in enumerate(selected):
        if not isinstance(item, Mapping):
            _fail(
                "REVIT_CONTEXT_SELECTION_INVALID",
                f"selected_elements[{index}] must be a mapping",
            )
        unique_id = _non_empty_string(
            item.get("unique_id"),
            code="REVIT_CONTEXT_SELECTION_INVALID",
            field_name=f"selected_elements[{index}].unique_id",
        )
        native_kind = _non_empty_string(
            item.get("native_kind"),
            code="REVIT_CONTEXT_SELECTION_INVALID",
            field_name=f"selected_elements[{index}].native_kind",
        )
        observations.append(
            RevitSelectedElement(
                unique_id=unique_id,
                native_kind=native_kind,
            )
        )

    return RevitContextObservation(
        document_id=actual_document_id,
        document_title=document_title,
        host_instance_id=actual_host_instance_id,
        revision=_revision(response),
        selected_elements=tuple(observations),
    )


def _request_context(transport, command: HostCommand) -> object:
    """通过既有 transport 执行只读命令，并把 transport 失败稳定映射到 context 错误。"""

    try:
        return transport.request(command)
    except (ConnectionError, OSError, TypeError, ValueError) as exc:
        _fail("REVIT_CONTEXT_READ_FAILED", f"transport failed: {exc}")


class RevitContextReadPort:
    """通过现有 named-pipe HostCommand 路径读取并验证 Revit 当前上下文。"""

    def __init__(self, transport) -> None:
        if transport is None or not callable(getattr(transport, "request", None)):
            raise TypeError("transport must provide request")
        self._transport = transport

    def read(
        self,
        *,
        command_id: str,
        document_id: str,
        host_instance_id: str,
    ) -> RevitContextObservation:
        """读取当前选择，并继续要求调用方已经冻结的 runtime identity 精确匹配。"""

        expected_host_instance_id = _non_empty_string(
            host_instance_id,
            code="REVIT_CONTEXT_REQUEST_INVALID",
            field_name="host_instance_id",
        )
        command = _context_command(command_id=command_id, document_id=document_id)
        raw_response = _request_context(self._transport, command)
        return _parse_context_response(
            raw_response,
            document_id=command.document_id,
            expected_host_instance_id=expected_host_instance_id,
        )


class RevitCurrentContextProbe:
    """按 configured document 发现 fresh Revit runtime identity，不预设 Host instance。"""

    def __init__(self, transport) -> None:
        if transport is None or not callable(getattr(transport, "request", None)):
            raise TypeError("transport must provide request")
        self._transport = transport

    def discover(
        self,
        *,
        command_id: str,
        document_id: str,
    ) -> RevitContextObservation:
        """读取 configured document，并接受本次 response 中经过校验的 fresh runtime id。"""

        command = _context_command(command_id=command_id, document_id=document_id)
        raw_response = _request_context(self._transport, command)
        return _parse_context_response(
            raw_response,
            document_id=command.document_id,
            expected_host_instance_id=None,
        )


__all__ = [
    "RevitContextObservation",
    "RevitContextReadPort",
    "RevitCurrentContextProbe",
    "RevitSelectedElement",
]
