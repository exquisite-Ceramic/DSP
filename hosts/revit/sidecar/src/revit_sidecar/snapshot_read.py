"""Revit 墙厚独立快照 READ 的严格 transport/evidence 适配器。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from host_contracts import HostCommand, HostEntityRef


def _fail(code: str, message: str) -> None:
    """以稳定错误码拒绝不能参与 post-commit verification 的 Host evidence。"""
    raise ValueError(f"{code}: {message}")


def _mapping(value: object, *, code: str, field_name: str) -> Mapping:
    """要求 Host response 的结构字段保持 mapping 形状。"""
    if not isinstance(value, Mapping):
        _fail(code, f"{field_name} must be a mapping")
    return value


def _non_empty_string(value: object, *, code: str, field_name: str) -> str:
    """读取并规范化独立快照中的非空 identity/evidence 字段。"""
    if not isinstance(value, str) or not value.strip():
        _fail(code, f"{field_name} must be a non-empty string")
    return value.strip()


def _real_revision(value: object) -> bool:
    """bool 虽是 int 子类，但不能作为 Revit revision。"""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True, slots=True)
class RevitWallThicknessSnapshotEvidence:
    """一次独立 post-commit READ 返回的已验证墙体 Host evidence。"""

    document_id: str
    host_instance_id: str
    wall_unique_id: str
    wall_type_unique_id: str
    native_kind: str
    builtin_category: str
    wall_thickness_mm: float
    location_signature: str
    relationship_signature: str
    revision_before: int
    revision_after: int


class RevitWallThicknessSnapshotReadPort:
    """读取 exact Revit Wall 的独立快照并验证 commit/revision correlation。"""

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
        wall_unique_id: str,
        expected_revision: int,
    ) -> RevitWallThicknessSnapshotEvidence:
        """读取 exact post-commit Wall evidence，不接受 mutation response 作为替代。"""
        if not _real_revision(expected_revision):
            _fail(
                "REVIT_SNAPSHOT_EXPECTED_REVISION_INVALID",
                "expected_revision must be a real non-negative integer",
            )
        command_id = _non_empty_string(
            command_id,
            code="REVIT_SNAPSHOT_REQUEST_INVALID",
            field_name="command_id",
        )
        document_id = _non_empty_string(
            document_id,
            code="REVIT_SNAPSHOT_REQUEST_INVALID",
            field_name="document_id",
        )
        host_instance_id = _non_empty_string(
            host_instance_id,
            code="REVIT_SNAPSHOT_REQUEST_INVALID",
            field_name="host_instance_id",
        )
        wall_unique_id = _non_empty_string(
            wall_unique_id,
            code="REVIT_SNAPSHOT_REQUEST_INVALID",
            field_name="wall_unique_id",
        )

        command = HostCommand(
            command_id=command_id,
            document_id=document_id,
            mode="READ",
            operation="read_wall_thickness_snapshot",
            target_native_refs=[
                HostEntityRef(
                    document_id=document_id,
                    native_id=wall_unique_id,
                    native_type="Wall",
                )
            ],
            arguments={},
            preconditions=[],
            idempotency_key=None,
        )
        validation_errors = command.validate()
        if validation_errors:
            _fail(
                "REVIT_SNAPSHOT_REQUEST_INVALID",
                f"HostCommand invalid: {validation_errors}",
            )

        try:
            raw_response = self._transport.request(command)
        except (ConnectionError, OSError, TypeError, ValueError) as exc:
            _fail("REVIT_SNAPSHOT_READ_FAILED", f"transport failed: {exc}")
        response = _mapping(
            raw_response,
            code="REVIT_SNAPSHOT_READ_FAILED",
            field_name="response",
        )
        if response.get("status") != "OK":
            _fail(
                "REVIT_SNAPSHOT_READ_FAILED",
                f"unsupported Host status: {response.get('status')!r}",
            )

        payload = _mapping(
            response.get("payload"),
            code="REVIT_SNAPSHOT_READ_FAILED",
            field_name="response.payload",
        )
        actual_document_id = _non_empty_string(
            payload.get("document_id"),
            code="REVIT_SNAPSHOT_DOCUMENT_MISMATCH",
            field_name="payload.document_id",
        )
        if actual_document_id != document_id:
            _fail(
                "REVIT_SNAPSHOT_DOCUMENT_MISMATCH",
                "snapshot document_id does not match the requested document",
            )
        actual_host_instance_id = _non_empty_string(
            payload.get("host_instance_id"),
            code="REVIT_SNAPSHOT_HOST_MISMATCH",
            field_name="payload.host_instance_id",
        )
        if actual_host_instance_id != host_instance_id:
            _fail(
                "REVIT_SNAPSHOT_HOST_MISMATCH",
                "snapshot runtime identity does not match the requested runtime",
            )
        actual_wall_unique_id = _non_empty_string(
            payload.get("wall_unique_id"),
            code="REVIT_SNAPSHOT_TARGET_MISMATCH",
            field_name="payload.wall_unique_id",
        )
        if actual_wall_unique_id != wall_unique_id:
            _fail(
                "REVIT_SNAPSHOT_TARGET_MISMATCH",
                "snapshot Wall UniqueId does not match the requested target",
            )

        native_kind = _non_empty_string(
            payload.get("native_kind"),
            code="REVIT_SNAPSHOT_TARGET_MISMATCH",
            field_name="payload.native_kind",
        )
        builtin_category = _non_empty_string(
            payload.get("builtin_category"),
            code="REVIT_SNAPSHOT_TARGET_MISMATCH",
            field_name="payload.builtin_category",
        )
        if native_kind != "Wall" or builtin_category != "OST_Walls":
            _fail(
                "REVIT_SNAPSHOT_TARGET_MISMATCH",
                "snapshot target is not the expected Revit Wall",
            )

        revision_before = payload.get("revision_before")
        revision_after = payload.get("revision_after")
        top_level_revision = response.get("revision_after")
        if (
            not _real_revision(revision_before)
            or not _real_revision(revision_after)
            or not _real_revision(top_level_revision)
            or revision_before != expected_revision
            or revision_after != expected_revision
            or top_level_revision != expected_revision
        ):
            _fail(
                "REVIT_SNAPSHOT_REVISION_MISMATCH",
                "snapshot revision window does not match the committed revision",
            )

        thickness = payload.get("wall_thickness_mm")
        if (
            isinstance(thickness, bool)
            or not isinstance(thickness, (int, float))
            or not math.isfinite(thickness)
            or thickness <= 0
        ):
            _fail(
                "REVIT_SNAPSHOT_THICKNESS_INVALID",
                "snapshot wall_thickness_mm must be finite and positive",
            )

        return RevitWallThicknessSnapshotEvidence(
            document_id=actual_document_id,
            host_instance_id=actual_host_instance_id,
            wall_unique_id=actual_wall_unique_id,
            wall_type_unique_id=_non_empty_string(
                payload.get("wall_type_unique_id"),
                code="REVIT_SNAPSHOT_READ_FAILED",
                field_name="payload.wall_type_unique_id",
            ),
            native_kind=native_kind,
            builtin_category=builtin_category,
            wall_thickness_mm=float(thickness),
            location_signature=_non_empty_string(
                payload.get("location_signature"),
                code="REVIT_SNAPSHOT_READ_FAILED",
                field_name="payload.location_signature",
            ),
            relationship_signature=_non_empty_string(
                payload.get("relationship_signature"),
                code="REVIT_SNAPSHOT_READ_FAILED",
                field_name="payload.relationship_signature",
            ),
            revision_before=revision_before,
            revision_after=revision_after,
        )


__all__ = [
    "RevitWallThicknessSnapshotEvidence",
    "RevitWallThicknessSnapshotReadPort",
]
