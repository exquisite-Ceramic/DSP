from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _require_non_empty(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _reject_unknown_keys(data: Mapping[str, Any], allowed: set[str], type_name: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"{type_name} contains unknown fields: {sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class DesignFactHostRef:
    host_type: str
    host_instance_id: str
    document_id: str

    def __post_init__(self) -> None:
        _require_non_empty(self.host_type, "host_type")
        _require_non_empty(self.host_instance_id, "host_instance_id")
        _require_non_empty(self.document_id, "document_id")

    def to_dict(self) -> dict[str, str]:
        return {
            "host_type": self.host_type,
            "host_instance_id": self.host_instance_id,
            "document_id": self.document_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DesignFactHostRef":
        if not isinstance(data, Mapping):
            raise ValueError("host_ref must be an object")
        _reject_unknown_keys(data, {"host_type", "host_instance_id", "document_id"}, "host_ref")
        try:
            return cls(
                host_type=data["host_type"],
                host_instance_id=data["host_instance_id"],
                document_id=data["document_id"],
            )
        except KeyError as exc:
            raise ValueError(f"host_ref missing required field: {exc.args[0]}") from exc


@dataclass(frozen=True, slots=True)
class NativeSubjectRef:
    document_id: str
    native_id: str
    native_kind: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.document_id, "document_id")
        _require_non_empty(self.native_id, "native_id")
        if self.native_kind is not None:
            _require_non_empty(self.native_kind, "native_kind")

    def to_dict(self) -> dict[str, str | None]:
        result: dict[str, str | None] = {
            "document_id": self.document_id,
            "native_id": self.native_id,
        }
        if self.native_kind is not None:
            result["native_kind"] = self.native_kind
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NativeSubjectRef":
        if not isinstance(data, Mapping):
            raise ValueError("subject_native_ref must be an object")
        _reject_unknown_keys(data, {"document_id", "native_id", "native_kind"}, "subject_native_ref")
        try:
            return cls(
                document_id=data["document_id"],
                native_id=data["native_id"],
                native_kind=data.get("native_kind"),
            )
        except KeyError as exc:
            raise ValueError(f"subject_native_ref missing required field: {exc.args[0]}") from exc
