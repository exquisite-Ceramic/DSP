"""Revit 当前上下文的严格只读 transport/evidence 适配器。"""

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
        """读取当前选择，只返回原生 identity/revision evidence，不做 semantic mapping。"""
        command_id = _non_empty_string(
            command_id,
            code="REVIT_CONTEXT_REQUEST_INVALID",
            field_name="command_id",
        )
        document_id = _non_empty_string(
            document_id,
            code="REVIT_CONTEXT_REQUEST_INVALID",
            field_name="document_id",
        )
        host_instance_id = _non_empty_string(
            host_instance_id,
            code="REVIT_CONTEXT_REQUEST_INVALID",
            field_name="host_instance_id",
        )
        command = HostCommand(
            command_id=command_id,
            document_id=document_id,
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

        try:
            raw_response = self._transport.request(command)
        except (ConnectionError, OSError, TypeError, ValueError) as exc:
            _fail("REVIT_CONTEXT_READ_FAILED", f"transport failed: {exc}")
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
        if actual_host_instance_id != host_instance_id:
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


__all__ = [
    "RevitContextObservation",
    "RevitContextReadPort",
    "RevitSelectedElement",
]
