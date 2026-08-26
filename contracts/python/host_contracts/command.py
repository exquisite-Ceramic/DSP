"""HostCommand (spec A.4).

First-phase modes: READ / VIEW / EXECUTE / VERIFY. Mutating modes
(EXECUTE, ROLLBACK) MUST carry an idempotency_key (spec §15.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from host_contracts.entity_ref import HostEntityRef
from host_contracts.envelope import is_valid_utc

MODES = ("READ", "VIEW", "EXECUTE", "VERIFY", "PREVIEW", "ROLLBACK", "INTERACTION")
MUTATING_MODES = ("EXECUTE", "ROLLBACK")


@dataclass(slots=True)
class HostCommand:
    command_id: str = ""
    document_id: str = ""
    mode: str = "READ"
    operation: str = ""
    target_native_refs: list[HostEntityRef] = field(default_factory=list)
    arguments: dict | None = None
    preconditions: list[dict] | None = None
    idempotency_key: str | None = None
    deadline_at: str | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.command_id:
            errors.append("command_id is required")
        if not self.operation:
            errors.append("operation is required")
        if self.mode not in MODES:
            errors.append(f"invalid mode: {self.mode!r}")
        if self.mode in MUTATING_MODES and not self.idempotency_key:
            errors.append(f"mode {self.mode} requires idempotency_key")
        if self.deadline_at is not None and not is_valid_utc(self.deadline_at):
            errors.append(f"deadline_at must be absolute UTC: {self.deadline_at!r}")
        return errors

    @classmethod
    def from_dict(cls, data: dict) -> "HostCommand":
        return cls(
            command_id=data.get("command_id", ""),
            document_id=data.get("document_id", ""),
            mode=data.get("mode", "READ"),
            operation=data.get("operation", ""),
            target_native_refs=[
                HostEntityRef.from_dict(r) for r in data.get("target_native_refs", [])
            ],
            arguments=data.get("arguments"),
            preconditions=data.get("preconditions"),
            idempotency_key=data.get("idempotency_key"),
            deadline_at=data.get("deadline_at"),
        )

    def to_dict(self) -> dict:
        d: dict = {
            "command_id": self.command_id,
            "document_id": self.document_id,
            "mode": self.mode,
            "operation": self.operation,
            "target_native_refs": [r.to_dict() for r in self.target_native_refs],
        }
        for key, value in (
            ("arguments", self.arguments),
            ("preconditions", self.preconditions),
            ("idempotency_key", self.idempotency_key),
            ("deadline_at", self.deadline_at),
        ):
            if value is not None:
                d[key] = value
        return d
