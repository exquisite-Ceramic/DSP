"""HostCommandResult: outcome of a host command."""

from __future__ import annotations

from dataclasses import dataclass, field

from host_contracts.error import ErrorShape

RESULT_STATUSES = ("OK", "PENDING", "ERROR")


@dataclass(slots=True)
class HostCommandResult:
    command_id: str = ""
    status: str = "OK"
    payload: dict | None = None
    error: ErrorShape | None = None
    revision_after: int | None = None
    verification: dict | None = None
    replayed: bool = False  # served from idempotency cache instead of re-executing

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.command_id:
            errors.append("command_id is required")
        if self.status not in RESULT_STATUSES:
            errors.append(f"invalid status: {self.status!r}")
        if self.status == "ERROR" and self.error is None:
            errors.append("status=ERROR requires error (ErrorShape)")
        if self.error is not None and self.status != "ERROR":
            errors.append("error is only allowed when status=ERROR")
        return errors

    @classmethod
    def from_dict(cls, data: dict) -> "HostCommandResult":
        error = data.get("error")
        return cls(
            command_id=data.get("command_id", ""),
            status=data.get("status", "OK"),
            payload=data.get("payload"),
            error=ErrorShape.from_dict(error) if error else None,
            revision_after=data.get("revision_after"),
            verification=data.get("verification"),
            replayed=data.get("replayed", False),
        )

    def to_dict(self) -> dict:
        d: dict = {"command_id": self.command_id, "status": self.status}
        for key, value in (
            ("payload", self.payload),
            ("error", self.error.to_dict() if self.error else None),
            ("revision_after", self.revision_after),
            ("verification", self.verification),
        ):
            if value is not None:
                d[key] = value
        if self.replayed:
            d["replayed"] = True
        return d
