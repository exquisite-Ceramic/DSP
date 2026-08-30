"""Immutable provider-neutral contracts for Step32 Gateway authorization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class GatewayAuthorizationError(ValueError):
    """Stable Step32 domain error with optional structured upstream detail."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        upstream_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = _text(code, "code")
        self.upstream_code = (
            None if upstream_code is None else _text(upstream_code, "upstream_code")
        )


class ApprovalState(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class GrantState(str, Enum):
    ACTIVE = "ACTIVE"
    ADMITTED = "ADMITTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: object | None, field_name: str) -> str | None:
    return None if value is None else _text(value, field_name)


def _digest(value: object, field_name: str) -> str:
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _enum(value: object, enum_type: type[Enum], field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


def _texts(values, field_name: str, *, required: bool = False) -> tuple[str, ...]:
    normalized = tuple(sorted({_text(value, field_name) for value in values}))
    if required and not normalized:
        raise ValueError(f"{field_name} requires at least one value")
    return normalized


def _utc_timestamp(value: object, field_name: str) -> str:
    normalized = _text(value, field_name)
    raw = f"{normalized[:-1]}+00:00" if normalized.endswith("Z") else normalized
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    canonical = parsed.isoformat()
    if canonical.endswith("+00:00"):
        canonical = f"{canonical[:-6]}Z"
    return canonical


def _optional_utc_timestamp(value: object | None, field_name: str) -> str | None:
    return None if value is None else _utc_timestamp(value, field_name)


@dataclass(frozen=True, slots=True)
class ApprovalAdmission:
    admission_id: str
    changeset_hash: str
    approved_scope_hash: str
    semantic_environment_ref: Any
    approver: str
    policy_snapshot_hash: str
    policy_allowed_operations: tuple[str, ...]
    approved_at: str
    expires_at: str
    admission_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "admission_id", _text(self.admission_id, "admission_id"))
        object.__setattr__(self, "changeset_hash", _digest(self.changeset_hash, "changeset_hash"))
        object.__setattr__(
            self,
            "approved_scope_hash",
            _digest(self.approved_scope_hash, "approved_scope_hash"),
        )
        object.__setattr__(self, "approver", _text(self.approver, "approver"))
        object.__setattr__(
            self,
            "policy_snapshot_hash",
            _digest(self.policy_snapshot_hash, "policy_snapshot_hash"),
        )
        object.__setattr__(
            self,
            "policy_allowed_operations",
            _texts(
                self.policy_allowed_operations,
                "policy_allowed_operation",
                required=True,
            ),
        )
        object.__setattr__(self, "approved_at", _utc_timestamp(self.approved_at, "approved_at"))
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        object.__setattr__(
            self,
            "admission_fingerprint",
            _digest(self.admission_fingerprint, "admission_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class ApprovalConsumptionRequest:
    admission: ApprovalAdmission
    canonical_changeset: Any
    approval_scope_boundary: Any
    consumed_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.admission, ApprovalAdmission):
            raise TypeError("admission must be ApprovalAdmission")
        object.__setattr__(self, "consumed_at", _utc_timestamp(self.consumed_at, "consumed_at"))


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    approval_id: str
    admission_id: str
    admission_fingerprint: str
    changeset_hash: str
    approved_scope_hash: str
    semantic_environment_ref: Any
    approver: str
    policy_snapshot_hash: str
    allowed_operations: tuple[str, ...]
    approved_at: str
    consumed_at: str
    approval_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", _text(self.approval_id, "approval_id"))
        object.__setattr__(self, "admission_id", _text(self.admission_id, "admission_id"))
        object.__setattr__(
            self,
            "admission_fingerprint",
            _digest(self.admission_fingerprint, "admission_fingerprint"),
        )
        for field_name in (
            "changeset_hash",
            "approved_scope_hash",
            "policy_snapshot_hash",
            "approval_hash",
        ):
            object.__setattr__(self, field_name, _digest(getattr(self, field_name), field_name))
        object.__setattr__(self, "approver", _text(self.approver, "approver"))
        object.__setattr__(
            self,
            "allowed_operations",
            _texts(self.allowed_operations, "allowed_operation", required=True),
        )
        object.__setattr__(self, "approved_at", _utc_timestamp(self.approved_at, "approved_at"))
        object.__setattr__(self, "consumed_at", _utc_timestamp(self.consumed_at, "consumed_at"))


@dataclass(frozen=True, slots=True)
class ApprovalLifecycle:
    state: ApprovalState | str
    revoked_at: str | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", _enum(self.state, ApprovalState, "approval state"))
        object.__setattr__(
            self,
            "revoked_at",
            _optional_utc_timestamp(self.revoked_at, "revoked_at"),
        )
        object.__setattr__(
            self,
            "revocation_reason",
            _optional_text(self.revocation_reason, "revocation_reason"),
        )


@dataclass(frozen=True, slots=True)
class StoredApproval:
    record: ApprovalRecord
    lifecycle: ApprovalLifecycle

    def __post_init__(self) -> None:
        if not isinstance(self.record, ApprovalRecord):
            raise TypeError("record must be ApprovalRecord")
        if not isinstance(self.lifecycle, ApprovalLifecycle):
            raise TypeError("lifecycle must be ApprovalLifecycle")


@dataclass(frozen=True, slots=True)
class ExecutionGrantRequest:
    approval_id: str
    execution_slice: Any
    provider_binding_set: Any
    issued_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", _text(self.approval_id, "approval_id"))
        object.__setattr__(self, "issued_at", _utc_timestamp(self.issued_at, "issued_at"))


@dataclass(frozen=True, slots=True)
class ExecutionGrant:
    grant_id: str
    approval_id: str
    approval_hash: str
    changeset_hash: str
    approved_scope_hash: str
    execution_slice_id: str
    execution_slice_hash: str
    binding_set_hash: str
    host_instance_id: str
    allowed_operations: tuple[str, ...]
    issued_at: str
    expires_at: str
    grant_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_id", _text(self.grant_id, "grant_id"))
        object.__setattr__(self, "approval_id", _text(self.approval_id, "approval_id"))
        object.__setattr__(
            self,
            "execution_slice_id",
            _text(self.execution_slice_id, "execution_slice_id"),
        )
        object.__setattr__(
            self,
            "host_instance_id",
            _text(self.host_instance_id, "host_instance_id"),
        )
        for field_name in (
            "approval_hash",
            "changeset_hash",
            "approved_scope_hash",
            "execution_slice_hash",
            "binding_set_hash",
            "grant_hash",
        ):
            object.__setattr__(self, field_name, _digest(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "allowed_operations",
            _texts(self.allowed_operations, "allowed_operation", required=True),
        )
        object.__setattr__(self, "issued_at", _utc_timestamp(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))


@dataclass(frozen=True, slots=True)
class GrantLifecycle:
    state: GrantState | str
    admitted_at: str | None = None
    revoked_at: str | None = None
    revocation_reason: str | None = None
    superseded_by_grant_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", _enum(self.state, GrantState, "grant state"))
        object.__setattr__(
            self,
            "admitted_at",
            _optional_utc_timestamp(self.admitted_at, "admitted_at"),
        )
        object.__setattr__(
            self,
            "revoked_at",
            _optional_utc_timestamp(self.revoked_at, "revoked_at"),
        )
        object.__setattr__(
            self,
            "revocation_reason",
            _optional_text(self.revocation_reason, "revocation_reason"),
        )
        object.__setattr__(
            self,
            "superseded_by_grant_id",
            _optional_text(self.superseded_by_grant_id, "superseded_by_grant_id"),
        )


@dataclass(frozen=True, slots=True)
class StoredGrant:
    grant: ExecutionGrant
    lifecycle: GrantLifecycle

    def __post_init__(self) -> None:
        if not isinstance(self.grant, ExecutionGrant):
            raise TypeError("grant must be ExecutionGrant")
        if not isinstance(self.lifecycle, GrantLifecycle):
            raise TypeError("lifecycle must be GrantLifecycle")


@dataclass(frozen=True, slots=True)
class AdmittedExecutionAuthority:
    approval_hash: str
    grant_hash: str
    changeset_hash: str
    approved_scope_hash: str
    execution_slice_hash: str
    binding_set_hash: str
    host_instance_id: str
    admitted_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "approval_hash",
            "grant_hash",
            "changeset_hash",
            "approved_scope_hash",
            "execution_slice_hash",
            "binding_set_hash",
        ):
            object.__setattr__(self, field_name, _digest(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "host_instance_id",
            _text(self.host_instance_id, "host_instance_id"),
        )
        object.__setattr__(
            self,
            "admitted_at",
            _utc_timestamp(self.admitted_at, "admitted_at"),
        )


__all__ = [
    "AdmittedExecutionAuthority",
    "ApprovalAdmission",
    "ApprovalConsumptionRequest",
    "ApprovalLifecycle",
    "ApprovalRecord",
    "ApprovalState",
    "ExecutionGrant",
    "ExecutionGrantRequest",
    "GatewayAuthorizationError",
    "GrantLifecycle",
    "GrantState",
    "StoredApproval",
    "StoredGrant",
]
