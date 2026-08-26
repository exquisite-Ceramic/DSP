"""HostEntityRef: Host-local entity reference (spec §12.2).

HostContract world identity is ``document_id + native_id``; ObjectId and
other Autodesk native types MUST NOT cross the contract boundary (AR-001).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HostEntityRef:
    document_id: str = ""
    native_id: str = ""
    native_type: str | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.document_id:
            errors.append("document_id is required")
        if not self.native_id:
            errors.append("native_id is required")
        return errors

    @classmethod
    def from_dict(cls, data: dict) -> "HostEntityRef":
        return cls(
            document_id=data.get("document_id", ""),
            native_id=data.get("native_id", ""),
            native_type=data.get("native_type"),
        )

    def to_dict(self) -> dict:
        d: dict = {"document_id": self.document_id, "native_id": self.native_id}
        if self.native_type is not None:
            d["native_type"] = self.native_type
        return d
