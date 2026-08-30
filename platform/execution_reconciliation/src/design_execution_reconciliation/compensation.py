"""Provider-neutral compensation evidence and planning for Step33 Sagas."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from design_changeset import canonical_hash

from .contracts import ReconciliationError
from .saga_state import (
    ExecutionSagaStatus,
    SliceReconciliationStatus,
    StoredExecutionSaga,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_STATUSES = frozenset(
    {
        SliceReconciliationStatus.FAILED_BEFORE_COMMIT,
        SliceReconciliationStatus.SCOPE_BREACH,
        SliceReconciliationStatus.VERIFY_FAILED,
    }
)


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _digest(value: object, field_name: str) -> str:
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _digests(values, field_name: str) -> tuple[str, ...]:
    normalized = tuple(_digest(value, field_name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} values must be unique")
    return normalized


def _freeze(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{field_name} mapping keys must be strings")
            normalized[key] = _freeze(item, field_name)
        return MappingProxyType(normalized)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item, field_name) for item in value)
    if isinstance(value, (set, frozenset)):
        frozen = tuple(_freeze(item, field_name) for item in value)
        return tuple(sorted(frozen, key=lambda item: canonical_hash(_plain(item))))
    return deepcopy(value)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _effects(values) -> tuple[Mapping[str, Any], ...]:
    frozen: list[Mapping[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise TypeError("desired_recovery_effects must contain mappings")
        frozen.append(_freeze(value, "desired_recovery_effect"))
    if not frozen:
        raise ValueError("desired_recovery_effects requires at least one canonical effect")
    return tuple(sorted(frozen, key=lambda item: canonical_hash(_plain(item))))


@dataclass(frozen=True, slots=True)
class CompensationProposalRequest:
    source_saga_id: str
    failed_slice_hash: str
    desired_recovery_effects: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_saga_id", _text(self.source_saga_id, "source_saga_id"))
        object.__setattr__(
            self,
            "failed_slice_hash",
            _digest(self.failed_slice_hash, "failed_slice_hash"),
        )
        object.__setattr__(
            self,
            "desired_recovery_effects",
            _effects(self.desired_recovery_effects),
        )


@dataclass(frozen=True, slots=True)
class CompensationProposal:
    compensation_proposal_id: str
    source_saga_id: str
    source_changeset_hash: str
    failed_slice_hash: str
    committed_slice_hashes: tuple[str, ...]
    actual_delta_refs: tuple[str, ...]
    verification_failure_refs: tuple[str, ...]
    scope_breach_refs: tuple[str, ...]
    desired_recovery_effects: tuple[Mapping[str, Any], ...]
    proposal_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "compensation_proposal_id",
            _text(self.compensation_proposal_id, "compensation_proposal_id"),
        )
        object.__setattr__(self, "source_saga_id", _text(self.source_saga_id, "source_saga_id"))
        for field_name in ("source_changeset_hash", "failed_slice_hash", "proposal_hash"):
            object.__setattr__(self, field_name, _digest(getattr(self, field_name), field_name))
        for field_name in (
            "committed_slice_hashes",
            "actual_delta_refs",
            "verification_failure_refs",
            "scope_breach_refs",
        ):
            object.__setattr__(
                self,
                field_name,
                _digests(getattr(self, field_name), field_name[:-1]),
            )
        object.__setattr__(
            self,
            "desired_recovery_effects",
            _effects(self.desired_recovery_effects),
        )


@dataclass(frozen=True, slots=True)
class CompensationExecutionRef:
    compensation_proposal_hash: str
    compensating_changeset_hash: str
    succeeded: bool
    completed_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "compensation_proposal_hash",
            _digest(self.compensation_proposal_hash, "compensation_proposal_hash"),
        )
        object.__setattr__(
            self,
            "compensating_changeset_hash",
            _digest(self.compensating_changeset_hash, "compensating_changeset_hash"),
        )
        if not isinstance(self.succeeded, bool):
            raise TypeError("succeeded must be a bool")
        object.__setattr__(self, "completed_at", _text(self.completed_at, "completed_at"))


def compute_compensation_proposal_hash(proposal: CompensationProposal) -> str:
    """Hash durable source evidence plus caller-supplied canonical recovery effects."""
    if not isinstance(proposal, CompensationProposal):
        raise TypeError("proposal must be CompensationProposal")
    return canonical_hash(
        {
            "source_saga_id": proposal.source_saga_id,
            "source_changeset_hash": proposal.source_changeset_hash,
            "failed_slice_hash": proposal.failed_slice_hash,
            "committed_slice_hashes": list(proposal.committed_slice_hashes),
            "actual_delta_refs": list(proposal.actual_delta_refs),
            "verification_failure_refs": list(proposal.verification_failure_refs),
            "scope_breach_refs": list(proposal.scope_breach_refs),
            "desired_recovery_effects": [
                _plain(effect) for effect in proposal.desired_recovery_effects
            ],
        }
    )


def validate_compensation_proposal_integrity(proposal: CompensationProposal) -> None:
    if not isinstance(proposal, CompensationProposal):
        raise TypeError("proposal must be CompensationProposal")
    expected = compute_compensation_proposal_hash(proposal)
    if proposal.proposal_hash != expected:
        raise ReconciliationError(
            "COMPENSATION_CONFLICT",
            "CompensationProposal body does not match its committed hash",
        )
    if proposal.compensation_proposal_id != f"CP-{expected[:12]}":
        raise ReconciliationError(
            "COMPENSATION_CONFLICT",
            "CompensationProposal id does not match its committed hash",
        )


class _SagaReader(Protocol):
    def get_saga(self, saga_id: str) -> StoredExecutionSaga | None: ...


class ExecutionSagaPlanner:
    """Seal auditable compensation evidence without inferring inverse Host commands."""

    def __init__(self, store: _SagaReader) -> None:
        self._store = store

    def create_compensation_proposal(
        self,
        request: CompensationProposalRequest,
    ) -> CompensationProposal:
        if not isinstance(request, CompensationProposalRequest):
            raise TypeError("request must be CompensationProposalRequest")
        stored = self._store.get_saga(request.source_saga_id)
        if stored is None:
            raise ReconciliationError("COMPENSATION_CONFLICT", "source Saga was not found")
        if stored.status is not ExecutionSagaStatus.PARTIALLY_COMMITTED:
            raise ReconciliationError(
                "COMPENSATION_CONFLICT",
                "compensation requires a PARTIALLY_COMMITTED source Saga",
            )

        failed = tuple(
            state
            for state in stored.slice_states
            if state.execution_slice_hash == request.failed_slice_hash
        )
        if len(failed) != 1 or failed[0].status not in _FAILURE_STATUSES:
            raise ReconciliationError(
                "COMPENSATION_CONFLICT",
                "failed_slice_hash does not identify the durable failed Slice",
            )

        committed_states = tuple(
            state for state in stored.slice_states if state.actual_delta_hash is not None
        )
        committed_slice_hashes = tuple(
            state.execution_slice_hash for state in committed_states
        )
        actual_delta_refs = tuple(
            state.actual_delta_hash for state in committed_states if state.actual_delta_hash
        )
        verification_failure_refs = tuple(
            state.verification_hash
            for state in stored.slice_states
            if state.status is SliceReconciliationStatus.VERIFY_FAILED
            and state.verification_hash is not None
        )
        scope_breach_refs = tuple(
            state.scope_comparison_hash
            for state in stored.slice_states
            if state.status is SliceReconciliationStatus.SCOPE_BREACH
            and state.scope_comparison_hash is not None
        )

        draft = CompensationProposal(
            compensation_proposal_id="CP-DRAFT",
            source_saga_id=stored.definition.saga_id,
            source_changeset_hash=stored.definition.changeset_hash,
            failed_slice_hash=request.failed_slice_hash,
            committed_slice_hashes=committed_slice_hashes,
            actual_delta_refs=actual_delta_refs,
            verification_failure_refs=verification_failure_refs,
            scope_breach_refs=scope_breach_refs,
            desired_recovery_effects=request.desired_recovery_effects,
            proposal_hash="0" * 64,
        )
        proposal_hash = compute_compensation_proposal_hash(draft)
        return CompensationProposal(
            compensation_proposal_id=f"CP-{proposal_hash[:12]}",
            source_saga_id=draft.source_saga_id,
            source_changeset_hash=draft.source_changeset_hash,
            failed_slice_hash=draft.failed_slice_hash,
            committed_slice_hashes=draft.committed_slice_hashes,
            actual_delta_refs=draft.actual_delta_refs,
            verification_failure_refs=draft.verification_failure_refs,
            scope_breach_refs=draft.scope_breach_refs,
            desired_recovery_effects=draft.desired_recovery_effects,
            proposal_hash=proposal_hash,
        )


__all__ = [
    "CompensationExecutionRef",
    "CompensationProposal",
    "CompensationProposalRequest",
    "ExecutionSagaPlanner",
    "compute_compensation_proposal_hash",
    "validate_compensation_proposal_integrity",
]
