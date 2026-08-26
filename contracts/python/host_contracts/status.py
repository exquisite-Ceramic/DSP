"""HostStatus: health / state heartbeat."""

from __future__ import annotations

from dataclasses import dataclass

STATES = ("starting", "ready", "busy", "error", "stopped")


@dataclass(slots=True)
class HostStatus:
    """Mirror of ``contracts/schemas/host-status.schema.json``."""

    state: str
    document_id: str | None = None
    document_name: str | None = None
    revision: int = 0
    uptime_ms: int = 0
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"invalid state: {self.state!r}")

    @classmethod
    def from_dict(cls, data: dict) -> "HostStatus":
        return cls(
            state=data["state"],
            document_id=data.get("documentId"),
            document_name=data.get("documentName"),
            revision=data.get("revision", 0),
            uptime_ms=data.get("uptimeMs", 0),
            detail=data.get("detail"),
        )

    def to_dict(self) -> dict:
        d: dict = {"state": self.state}
        if self.document_id is not None:
            d["documentId"] = self.document_id
        if self.document_name is not None:
            d["documentName"] = self.document_name
        if self.revision:
            d["revision"] = self.revision
        if self.uptime_ms:
            d["uptimeMs"] = self.uptime_ms
        if self.detail is not None:
            d["detail"] = self.detail
        return d
