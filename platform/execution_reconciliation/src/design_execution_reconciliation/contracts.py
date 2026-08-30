"""Immutable provider-neutral value contracts for Step33 execution reconciliation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from design_approval_scope import CanonicalAspect
from host_contracts import HostEntityRef

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ReconciliationError(ValueError):
    """Stable Step33 domain error with structured upstream/detail evidence."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        upstream_code: str | None = None,
        detail_codes: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = _text(code, "code")
        self.upstream_code = (
            None if upstream_code is None else _text(upstream_code, "upstream_code")
        )
        self.detail_codes = tuple(
            sorted({_text(value, "detail_code") for value in detail_codes})
        )


class ActualChangeKind(str, Enum):
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"


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


def _optional_digest(value: object | None, field_name: str) -> str | None:
    return None if value is None else _digest(value, field_name)


def _enum(value: object, enum_type: type[Enum], field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


def _aspects(values) -> tuple[CanonicalAspect, ...]:
    try:
        raw = tuple(values)
    except TypeError as exc:
        raise TypeError("changed_aspects must be iterable") from exc
    normalized = {
        _enum(value, CanonicalAspect, "canonical aspect")
        for value in raw
    }
    return tuple(sorted(normalized, key=lambda value: value.value))


def _host_entity_ref(value: object | None) -> HostEntityRef | None:
    if value is None:
        return None
    if not isinstance(value, HostEntityRef):
        raise TypeError("host_entity_ref must be HostEntityRef")
    errors = value.validate()
    if errors:
        raise ValueError("invalid host_entity_ref: " + "; ".join(errors))
    return HostEntityRef(
        document_id=value.document_id,
        native_id=value.native_id,
        native_type=value.native_type,
    )


def _revision(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReconciliationError(
            "ACTUAL_DELTA_INPUT_INVALID",
            f"{field_name} must be an integer revision",
        )
    if value < 0:
        raise ReconciliationError(
            "ACTUAL_DELTA_INPUT_INVALID",
            f"{field_name} must be non-negative",
        )
    return value


@dataclass(frozen=True, slots=True)
class ActualChange:
    change_kind: ActualChangeKind | str
    actual_change_hash: str
    semantic_id: str | None = None
    canonical_kind: str | None = None
    changed_aspects: tuple[CanonicalAspect | str, ...] = ()
    canonical_operation: str | None = None
    source_execution_unit_hash: str | None = None
    source_semantic_id: str | None = None
    source_canonical_kind: str | None = None
    derivation_rule: str | None = None
    host_entity_ref: HostEntityRef | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "change_kind",
            _enum(self.change_kind, ActualChangeKind, "actual change kind"),
        )
        object.__setattr__(
            self,
            "actual_change_hash",
            _digest(self.actual_change_hash, "actual_change_hash"),
        )
        for field_name in (
            "semantic_id",
            "canonical_kind",
            "canonical_operation",
            "source_semantic_id",
            "source_canonical_kind",
            "derivation_rule",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "source_execution_unit_hash",
            _optional_digest(
                self.source_execution_unit_hash,
                "source_execution_unit_hash",
            ),
        )
        object.__setattr__(self, "changed_aspects", _aspects(self.changed_aspects))
        object.__setattr__(self, "host_entity_ref", _host_entity_ref(self.host_entity_ref))

        if self.change_kind is ActualChangeKind.MODIFY:
            if self.semantic_id is None:
                raise ValueError("MODIFY requires semantic_id")
            if not self.changed_aspects:
                raise ValueError("MODIFY requires at least one changed_aspect")
        elif self.change_kind is ActualChangeKind.DELETE:
            if self.semantic_id is None:
                raise ValueError("DELETE requires semantic_id")
        elif self.change_kind is ActualChangeKind.CREATE:
            if self.canonical_operation is None:
                raise ValueError("CREATE requires canonical_operation")
            if self.semantic_id is None and self.host_entity_ref is None:
                raise ValueError("CREATE requires semantic_id or host_entity_ref")


@dataclass(frozen=True, slots=True)
class ActualDelta:
    actual_delta_id: str
    grant_hash: str
    binding_set_hash: str
    execution_slice_hash: str
    changeset_hash: str
    approved_scope_hash: str
    host_instance_id: str
    document_ref: str
    revision_before: int
    revision_after: int
    changes: tuple[ActualChange, ...]
    actual_delta_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "actual_delta_id",
            _text(self.actual_delta_id, "actual_delta_id"),
        )
        for field_name in (
            "grant_hash",
            "binding_set_hash",
            "execution_slice_hash",
            "changeset_hash",
            "approved_scope_hash",
            "actual_delta_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _digest(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "host_instance_id",
            _text(self.host_instance_id, "host_instance_id"),
        )
        object.__setattr__(
            self,
            "document_ref",
            _text(self.document_ref, "document_ref"),
        )
        before = _revision(self.revision_before, "revision_before")
        after = _revision(self.revision_after, "revision_after")
        if after < before:
            raise ReconciliationError(
                "RECONCILIATION_REVISION_INVALID",
                "revision_after cannot precede revision_before",
            )
        object.__setattr__(self, "revision_before", before)
        object.__setattr__(self, "revision_after", after)

        changes = tuple(self.changes)
        if any(not isinstance(change, ActualChange) for change in changes):
            raise TypeError("changes must contain ActualChange values")
        object.__setattr__(self, "changes", changes)


__all__ = [
    "ActualChange",
    "ActualChangeKind",
    "ActualDelta",
    "ReconciliationError",
]
