"""Immutable provider-neutral value contracts for Step33 execution reconciliation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

from design_approval_scope import ApprovalScopeBoundary, CanonicalAspect
from design_changeset import canonical_hash
from design_execution_planning import ExecutionSlice
from design_gateway_authorization import AdmittedExecutionAuthority
from host_contracts import HostEntityRef
from semantic_runtime import SemanticEnvironmentRef, SemanticProjectionRef, SemanticSnapshot

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


class ScopeComparisonStatus(str, Enum):
    WITHIN_SCOPE = "WITHIN_SCOPE"
    SCOPE_BREACH = "SCOPE_BREACH"


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
    normalized = {_enum(value, CanonicalAspect, "canonical aspect") for value in raw}
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


def _typed_tuple(values, typ: type, field_name: str):
    normalized = tuple(values)
    if any(not isinstance(value, typ) for value in normalized):
        raise TypeError(f"{field_name} contains invalid values")
    return normalized


def _freeze_value(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{field_name} mapping keys must be strings")
            normalized[key] = _freeze_value(item, field_name)
        return MappingProxyType(normalized)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item, field_name) for item in value)
    if isinstance(value, (set, frozenset)):
        frozen = tuple(_freeze_value(item, field_name) for item in value)
        return tuple(sorted(frozen, key=lambda item: canonical_hash(_plain_value(item))))
    return deepcopy(value)


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    return value


def _readonly_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return _freeze_value(value, field_name)


def _optional_readonly_mapping(
    value: Mapping[str, Any] | None,
    field_name: str,
) -> Mapping[str, Any] | None:
    return None if value is None else _readonly_mapping(value, field_name)


def _mapping_tuple(values, field_name: str) -> tuple[Mapping[str, Any], ...]:
    frozen = tuple(_readonly_mapping(value, field_name) for value in values)
    return tuple(sorted(frozen, key=lambda item: canonical_hash(_plain_value(item))))


def _texts(values, field_name: str) -> tuple[str, ...]:
    return tuple(sorted({_text(value, field_name) for value in values}))


def _require_type(value: object, typ: type, field_name: str) -> None:
    if not isinstance(value, typ):
        raise TypeError(f"{field_name} must be {typ.__name__}")


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


@dataclass(frozen=True, slots=True)
class VerificationContractEvidence:
    contract_ref: str
    contract_body: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_ref", _digest(self.contract_ref, "contract_ref"))
        object.__setattr__(
            self,
            "contract_body",
            _readonly_mapping(self.contract_body, "contract_body"),
        )


@dataclass(frozen=True, slots=True)
class VerificationSubjectEvidence:
    semantic_id: str
    canonical_kind: str
    properties: Mapping[str, Any]
    placement: Mapping[str, Any] | None
    geometry_evidence: Mapping[str, Any] | None
    relationships: tuple[Mapping[str, Any], ...]
    constraints: tuple[Mapping[str, Any], ...]
    classification: tuple[str, ...]
    evidence_aspects: tuple[CanonicalAspect | str, ...]
    snapshot_id: str
    snapshot_hash: str
    projection_ref: SemanticProjectionRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantic_id", _text(self.semantic_id, "semantic_id"))
        object.__setattr__(
            self,
            "canonical_kind",
            _text(self.canonical_kind, "canonical_kind"),
        )
        object.__setattr__(
            self,
            "properties",
            _readonly_mapping(self.properties, "properties"),
        )
        object.__setattr__(
            self,
            "placement",
            _optional_readonly_mapping(self.placement, "placement"),
        )
        object.__setattr__(
            self,
            "geometry_evidence",
            _optional_readonly_mapping(self.geometry_evidence, "geometry_evidence"),
        )
        object.__setattr__(
            self,
            "relationships",
            _mapping_tuple(self.relationships, "relationships"),
        )
        object.__setattr__(
            self,
            "constraints",
            _mapping_tuple(self.constraints, "constraints"),
        )
        object.__setattr__(
            self,
            "classification",
            _texts(self.classification, "classification"),
        )
        object.__setattr__(self, "evidence_aspects", _aspects(self.evidence_aspects))
        object.__setattr__(self, "snapshot_id", _text(self.snapshot_id, "snapshot_id"))
        object.__setattr__(
            self,
            "snapshot_hash",
            _digest(self.snapshot_hash, "snapshot_hash"),
        )
        _require_type(self.projection_ref, SemanticProjectionRef, "projection_ref")


@dataclass(frozen=True, slots=True)
class VerificationEvidenceBundle:
    evidence_bundle_id: str
    changeset_hash: str
    execution_slice_hash: str
    actual_delta_hash: str
    semantic_environment_ref: SemanticEnvironmentRef
    post_execution_snapshot_ref: SemanticSnapshot
    post_execution_projection_ref: SemanticProjectionRef
    base_host_revision: str
    baseline_snapshot_ref: SemanticSnapshot | None
    baseline_projection_ref: SemanticProjectionRef | None
    contract_evidence: tuple[VerificationContractEvidence, ...]
    subject_evidence: tuple[VerificationSubjectEvidence, ...]
    baseline_subject_evidence: tuple[VerificationSubjectEvidence, ...]
    evidence_bundle_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_bundle_id",
            _text(self.evidence_bundle_id, "evidence_bundle_id"),
        )
        for field_name in (
            "changeset_hash",
            "execution_slice_hash",
            "actual_delta_hash",
            "evidence_bundle_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _digest(getattr(self, field_name), field_name),
            )
        _require_type(
            self.semantic_environment_ref,
            SemanticEnvironmentRef,
            "semantic_environment_ref",
        )
        _require_type(
            self.post_execution_snapshot_ref,
            SemanticSnapshot,
            "post_execution_snapshot_ref",
        )
        _require_type(
            self.post_execution_projection_ref,
            SemanticProjectionRef,
            "post_execution_projection_ref",
        )
        if self.baseline_snapshot_ref is not None:
            _require_type(
                self.baseline_snapshot_ref,
                SemanticSnapshot,
                "baseline_snapshot_ref",
            )
        if self.baseline_projection_ref is not None:
            _require_type(
                self.baseline_projection_ref,
                SemanticProjectionRef,
                "baseline_projection_ref",
            )
        object.__setattr__(
            self,
            "base_host_revision",
            _text(self.base_host_revision, "base_host_revision"),
        )

        contracts = _typed_tuple(
            self.contract_evidence,
            VerificationContractEvidence,
            "contract_evidence",
        )
        subjects = _typed_tuple(
            self.subject_evidence,
            VerificationSubjectEvidence,
            "subject_evidence",
        )
        baseline_subjects = _typed_tuple(
            self.baseline_subject_evidence,
            VerificationSubjectEvidence,
            "baseline_subject_evidence",
        )
        object.__setattr__(
            self,
            "contract_evidence",
            tuple(
                sorted(
                    contracts,
                    key=lambda item: (
                        item.contract_ref,
                        canonical_hash(_plain_value(item.contract_body)),
                    ),
                )
            ),
        )
        subject_key = lambda item: (item.snapshot_id, item.snapshot_hash, item.semantic_id)
        object.__setattr__(self, "subject_evidence", tuple(sorted(subjects, key=subject_key)))
        object.__setattr__(
            self,
            "baseline_subject_evidence",
            tuple(sorted(baseline_subjects, key=subject_key)),
        )


@dataclass(frozen=True, slots=True)
class ScopeMatch:
    actual_change_hash: str
    rule_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "actual_change_hash",
            _digest(self.actual_change_hash, "actual_change_hash"),
        )
        object.__setattr__(self, "rule_id", _text(self.rule_id, "rule_id"))


@dataclass(frozen=True, slots=True)
class ScopeViolation:
    code: str
    actual_change_hash: str
    rule_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _text(self.code, "code"))
        object.__setattr__(
            self,
            "actual_change_hash",
            _digest(self.actual_change_hash, "actual_change_hash"),
        )
        object.__setattr__(
            self,
            "rule_id",
            _optional_text(self.rule_id, "rule_id"),
        )


@dataclass(frozen=True, slots=True)
class ScopeComparisonRequest:
    admitted_execution_authority: AdmittedExecutionAuthority
    actual_delta: ActualDelta
    approval_scope_boundary: ApprovalScopeBoundary
    execution_slice: ExecutionSlice

    def __post_init__(self) -> None:
        if not isinstance(self.admitted_execution_authority, AdmittedExecutionAuthority):
            raise TypeError(
                "admitted_execution_authority must be AdmittedExecutionAuthority"
            )
        if not isinstance(self.actual_delta, ActualDelta):
            raise TypeError("actual_delta must be ActualDelta")
        if not isinstance(self.approval_scope_boundary, ApprovalScopeBoundary):
            raise TypeError("approval_scope_boundary must be ApprovalScopeBoundary")
        if not isinstance(self.execution_slice, ExecutionSlice):
            raise TypeError("execution_slice must be ExecutionSlice")


@dataclass(frozen=True, slots=True)
class ScopeComparisonResult:
    status: ScopeComparisonStatus | str
    actual_delta_hash: str
    approved_scope_hash: str
    execution_slice_hash: str
    matched_changes: tuple[ScopeMatch, ...]
    violations: tuple[ScopeViolation, ...]
    comparison_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _enum(self.status, ScopeComparisonStatus, "scope comparison status"),
        )
        for field_name in (
            "actual_delta_hash",
            "approved_scope_hash",
            "execution_slice_hash",
            "comparison_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _digest(getattr(self, field_name), field_name),
            )
        matches = _typed_tuple(self.matched_changes, ScopeMatch, "matched_changes")
        violations = _typed_tuple(self.violations, ScopeViolation, "violations")
        object.__setattr__(
            self,
            "matched_changes",
            tuple(sorted(matches, key=lambda item: (item.actual_change_hash, item.rule_id))),
        )
        object.__setattr__(
            self,
            "violations",
            tuple(
                sorted(
                    violations,
                    key=lambda item: (
                        item.actual_change_hash,
                        item.code,
                        item.rule_id or "",
                    ),
                )
            ),
        )


__all__ = [
    "ActualChange",
    "ActualChangeKind",
    "ActualDelta",
    "ReconciliationError",
    "ScopeComparisonRequest",
    "ScopeComparisonResult",
    "ScopeComparisonStatus",
    "ScopeMatch",
    "ScopeViolation",
    "VerificationContractEvidence",
    "VerificationEvidenceBundle",
    "VerificationSubjectEvidence",
]
