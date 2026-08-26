"""RequestEnvelope / ResponseEnvelope / AsyncOperationRef (spec A.8, §26.1).

Wire format is snake_case JSON. Per spec §23.1 receivers MUST ignore unknown
fields, so ``from_dict`` drops keys it does not know instead of failing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from host_contracts.error import ErrorShape

CONTRACT_MAJOR = 1
CONTRACT_MINOR = 0
CONTRACT_VERSION = f"{CONTRACT_MAJOR}.{CONTRACT_MINOR}"

RESPONSE_STATUSES = ("OK", "PENDING", "ERROR")
ASYNC_REF_TYPES = ("INTERACTION_SESSION", "RECONSTRUCTION_JOB", "EXECUTION_JOB", "OTHER")


def _new_request_id() -> str:
    return str(uuid.uuid4())


def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require it to be absolute UTC."""
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise ValueError(f"must be absolute UTC, got {value!r}")
    return dt


def is_valid_utc(value: str) -> bool:
    try:
        parse_utc(value)
        return True
    except ValueError:
        return False


def deadline_within(child: str | None, parent: str | None) -> bool:
    """AR-024: a child deadline MUST NOT exceed its parent deadline."""
    if child is None or parent is None:
        return True
    return parse_utc(child) <= parse_utc(parent)


@dataclass(slots=True)
class AsyncOperationRef:
    """Typed handle for PENDING work (spec A.8, §26.1 rule 6)."""

    type: str = "OTHER"
    id: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.type not in ASYNC_REF_TYPES:
            errors.append(f"invalid async ref type: {self.type!r}")
        if not self.id:
            errors.append("async ref id is required")
        return errors

    @classmethod
    def from_dict(cls, data: dict) -> "AsyncOperationRef":
        return cls(type=data.get("type", "OTHER"), id=data.get("id", ""))

    def to_dict(self) -> dict:
        return {"type": self.type, "id": self.id}


@dataclass(slots=True)
class RequestEnvelope:
    """spec A.8. ``request_id`` is unique per transport attempt.

    ``idempotency_key`` identifies one logical side effect and MUST stay
    stable across retries of that side effect (spec §15.2 / AR-023).
    """

    request_id: str = field(default_factory=_new_request_id)
    task_id: str | None = None
    project_id: str | None = None
    actor_context: dict | None = None
    correlation_ids: list[str] | None = None
    deadline_at: str | None = None  # absolute UTC ISO-8601
    idempotency_key: str | None = None  # REQUIRED for side-effecting payloads
    payload: dict = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.request_id:
            errors.append("request_id is required")
        if self.deadline_at is not None and not is_valid_utc(self.deadline_at):
            errors.append(f"deadline_at must be absolute UTC: {self.deadline_at!r}")
        return errors

    @classmethod
    def from_dict(cls, data: dict) -> "RequestEnvelope":
        return cls(
            request_id=data.get("request_id", ""),
            task_id=data.get("task_id"),
            project_id=data.get("project_id"),
            actor_context=data.get("actor_context"),
            correlation_ids=data.get("correlation_ids"),
            deadline_at=data.get("deadline_at"),
            idempotency_key=data.get("idempotency_key"),
            payload=data.get("payload", {}),
        )

    def to_dict(self) -> dict:
        d: dict = {"request_id": self.request_id, "payload": self.payload}
        for key in (
            "task_id",
            "project_id",
            "actor_context",
            "correlation_ids",
            "deadline_at",
            "idempotency_key",
        ):
            value = getattr(self, key)
            if value is not None:
                d[key] = value
        return d


@dataclass(slots=True)
class ResponseEnvelope:
    """spec A.8. ``status=PENDING`` MUST carry an ``operation_ref``."""

    request_id: str = ""
    status: str = "OK"
    correlation_ids: list[str] | None = None
    snapshot_ref: str | None = None
    operation_ref: AsyncOperationRef | None = None
    result: dict | None = None
    error: ErrorShape | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.request_id:
            errors.append("request_id is required")
        if self.status not in RESPONSE_STATUSES:
            errors.append(f"invalid status: {self.status!r}")
        if self.status == "PENDING" and self.operation_ref is None:
            errors.append("status=PENDING requires operation_ref (AsyncOperationRef)")
        if self.status == "ERROR" and self.error is None:
            errors.append("status=ERROR requires error (ErrorShape)")
        if self.error is not None and self.status != "ERROR":
            errors.append("error is only allowed when status=ERROR")
        return errors

    @classmethod
    def from_dict(cls, data: dict) -> "ResponseEnvelope":
        op_ref = data.get("operation_ref")
        error = data.get("error")
        return cls(
            request_id=data.get("request_id", ""),
            status=data.get("status", "OK"),
            correlation_ids=data.get("correlation_ids"),
            snapshot_ref=data.get("snapshot_ref"),
            operation_ref=AsyncOperationRef.from_dict(op_ref) if op_ref else None,
            result=data.get("result"),
            error=ErrorShape.from_dict(error) if error else None,
        )

    def to_dict(self) -> dict:
        d: dict = {"request_id": self.request_id, "status": self.status}
        for key, value in (
            ("correlation_ids", self.correlation_ids),
            ("snapshot_ref", self.snapshot_ref),
            ("operation_ref", self.operation_ref.to_dict() if self.operation_ref else None),
            ("result", self.result),
            ("error", self.error.to_dict() if self.error else None),
        ):
            if value is not None:
                d[key] = value
        return d
