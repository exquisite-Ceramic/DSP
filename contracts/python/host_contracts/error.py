"""ErrorShape: structured error object (spec §19.2).

``error_code`` is the stable machine-readable code — program decisions MUST
key on it, never on ``message``. ``retryable`` is a policy enum, not a bool.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CATEGORIES = ("PROTOCOL", "POLICY", "SEMANTIC", "EXECUTION", "CONSISTENCY")
RETRY_POLICIES = ("IMMEDIATE", "AFTER_RECONSTRUCT", "AFTER_APPROVAL", "NEVER")


@dataclass(slots=True)
class ErrorShape:
    error_code: str = ""
    category: str = "EXECUTION"
    message: str = ""
    correlation_ids: list[str] | None = None
    retryable: str = "NEVER"
    details: list[dict] | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.error_code:
            errors.append("error_code is required")
        if self.category not in CATEGORIES:
            errors.append(f"invalid category: {self.category!r}")
        if self.retryable not in RETRY_POLICIES:
            errors.append(f"invalid retryable: {self.retryable!r}")
        return errors

    @classmethod
    def from_dict(cls, data: dict) -> "ErrorShape":
        return cls(
            error_code=data.get("error_code", ""),
            category=data.get("category", "EXECUTION"),
            message=data.get("message", ""),
            correlation_ids=data.get("correlation_ids"),
            retryable=data.get("retryable", "NEVER"),
            details=data.get("details"),
        )

    def to_dict(self) -> dict:
        d: dict = {
            "error_code": self.error_code,
            "category": self.category,
            "message": self.message,
            "retryable": self.retryable,
        }
        for key, value in (
            ("correlation_ids", self.correlation_ids),
            ("details", self.details),
        ):
            if value is not None:
                d[key] = value
        return d
