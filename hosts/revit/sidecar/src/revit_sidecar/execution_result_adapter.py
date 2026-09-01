"""Translate Revit Host evidence into provider-neutral execution results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from design_approval_scope import CanonicalAspect
from design_execution_coordination import HostCommitted, HostFailed, HostFailurePhase
from design_execution_reconciliation import (
    ActualChange,
    ActualChangeKind,
    ActualDelta,
    compute_actual_change_hash,
    compute_actual_delta_hash,
)
from design_gateway_authorization import AdmittedExecutionAuthority


class RevitExecutionResultAdapterError(ValueError):
    """Stable fail-closed error for malformed or unsupported Host evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _text(code, "code")


class CommittedEffectUnnormalizableError(RevitExecutionResultAdapterError):
    """Known commit whose wider effects cannot be truthfully normalized."""

    STABLE_CODE = "COMMITTED_EFFECT_UNNORMALIZABLE"

    def __init__(self, message: str = "Committed Revit effects cannot be normalized truthfully.") -> None:
        super().__init__(self.STABLE_CODE, message)


class RevitExecutionResultAdapter:
    """Project a Revit Host result onto existing Step33/Step37 contracts."""

    @staticmethod
    def adapt(
        *,
        admitted_authority: AdmittedExecutionAuthority,
        document_ref: str,
        approved_semantic_wall_id: str,
        host_result: Mapping[str, Any],
        occurred_at: str,
    ) -> HostCommitted | HostFailed:
        if not isinstance(admitted_authority, AdmittedExecutionAuthority):
            raise TypeError("admitted_authority must be AdmittedExecutionAuthority")

        document_ref = _text(document_ref, "document_ref")
        approved_semantic_wall_id = _text(
            approved_semantic_wall_id,
            "approved_semantic_wall_id",
        )
        occurred_at = _text(occurred_at, "occurred_at")
        result = _mapping(host_result, "host_result")
        status = _text(result.get("status"), "host_result.status")

        if status == "ERROR":
            return RevitExecutionResultAdapter._adapt_error(result, occurred_at)
        if status != "OK":
            raise RevitExecutionResultAdapterError(
                "REVIT_HOST_RESULT_INVALID",
                f"Unsupported Revit Host result status: {status!r}.",
            )

        verification = _mapping(result.get("verification"), "host_result.verification")
        RevitExecutionResultAdapter._require_success_invariants(verification)

        revision_before = _revision(
            verification.get("revision_before"),
            "host_result.verification.revision_before",
        )
        verification_revision_after = _revision(
            verification.get("revision_after"),
            "host_result.verification.revision_after",
        )
        revision_after = _revision(
            result.get("revision_after"),
            "host_result.revision_after",
        )
        if verification_revision_after != revision_after:
            raise RevitExecutionResultAdapterError(
                "REVIT_HOST_RESULT_INVALID",
                "Top-level revision_after does not match verification revision_after.",
            )
        if revision_after <= revision_before:
            raise RevitExecutionResultAdapterError(
                "REVIT_HOST_RESULT_INVALID",
                "Successful Revit evidence requires revision_after > revision_before.",
            )

        changes = [
            _signed_modify_change(
                semantic_id=approved_semantic_wall_id,
                canonical_kind="ifc:IfcWall",
                changed_aspects=(CanonicalAspect.PROPERTIES,),
            )
        ]
        changes.extend(
            RevitExecutionResultAdapter._normalized_wider_changes(
                verification,
                base_semantic_id=approved_semantic_wall_id,
            )
        )

        command_id = _text(result.get("command_id"), "host_result.command_id")
        draft = ActualDelta(
            actual_delta_id=f"AD-REVIT-{command_id}",
            grant_hash=admitted_authority.grant_hash,
            binding_set_hash=admitted_authority.binding_set_hash,
            execution_slice_hash=admitted_authority.execution_slice_hash,
            changeset_hash=admitted_authority.changeset_hash,
            approved_scope_hash=admitted_authority.approved_scope_hash,
            host_instance_id=admitted_authority.host_instance_id,
            document_ref=document_ref,
            revision_before=revision_before,
            revision_after=revision_after,
            changes=tuple(changes),
            actual_delta_hash="0" * 64,
        )
        signed_delta = replace(
            draft,
            actual_delta_hash=compute_actual_delta_hash(draft),
        )
        return HostCommitted(actual_delta=signed_delta, committed_at=occurred_at)

    @staticmethod
    def _adapt_error(
        host_result: Mapping[str, Any],
        occurred_at: str,
    ) -> HostFailed:
        error = _mapping(host_result.get("error"), "host_result.error")
        code = _text(error.get("code"), "host_result.error.code")
        commit_state = _text(
            error.get("commit_state"),
            "host_result.error.commit_state",
        )

        if commit_state == "BEFORE_COMMIT":
            return HostFailed(
                phase=HostFailurePhase.BEFORE_COMMIT,
                failure_ref=code,
                failed_at=occurred_at,
            )
        if commit_state == "COMMIT_STATE_UNKNOWN":
            if code != "REVIT_COMMIT_STATE_UNKNOWN":
                raise RevitExecutionResultAdapterError(
                    "REVIT_HOST_RESULT_INVALID",
                    "COMMIT_STATE_UNKNOWN must use REVIT_COMMIT_STATE_UNKNOWN.",
                )
            return HostFailed(
                phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
                failure_ref=code,
                failed_at=occurred_at,
            )
        if commit_state == "KNOWN_COMMITTED":
            message = error.get("message")
            detail = (
                _text(message, "host_result.error.message")
                if message is not None
                else "Committed Revit effects cannot be normalized truthfully."
            )
            raise CommittedEffectUnnormalizableError(detail)

        raise RevitExecutionResultAdapterError(
            "REVIT_HOST_RESULT_INVALID",
            f"Unknown Revit commit state: {commit_state!r}.",
        )

    @staticmethod
    def _require_success_invariants(verification: Mapping[str, Any]) -> None:
        for field_name in (
            "identity_invariant_proven",
            "location_invariant_proven",
            "relationship_invariant_proven",
            "document_change_observed",
        ):
            value = verification.get(field_name)
            if value is not True:
                raise RevitExecutionResultAdapterError(
                    "REVIT_HOST_RESULT_INVALID",
                    f"Successful Revit evidence requires {field_name}=true.",
                )

    @staticmethod
    def _normalized_wider_changes(
        verification: Mapping[str, Any],
        *,
        base_semantic_id: str,
    ) -> tuple[ActualChange, ...]:
        raw_effects = verification.get("normalized_wider_effects", ())
        if raw_effects is None:
            raw_effects = ()
        if isinstance(raw_effects, (str, bytes, Mapping)):
            raise RevitExecutionResultAdapterError(
                "REVIT_HOST_RESULT_INVALID",
                "normalized_wider_effects must be a sequence of mappings.",
            )
        try:
            effects = tuple(raw_effects)
        except TypeError as exc:
            raise RevitExecutionResultAdapterError(
                "REVIT_HOST_RESULT_INVALID",
                "normalized_wider_effects must be iterable.",
            ) from exc

        normalized: dict[
            tuple[str, str, tuple[CanonicalAspect, ...]],
            ActualChange,
        ] = {}
        base_key = (
            base_semantic_id,
            "ifc:IfcWall",
            (CanonicalAspect.PROPERTIES,),
        )

        for index, raw in enumerate(effects):
            effect = _mapping(raw, f"normalized_wider_effects[{index}]")
            semantic_id = _text(
                effect.get("semantic_id"),
                f"normalized_wider_effects[{index}].semantic_id",
            )
            canonical_kind = _text(
                effect.get("canonical_kind"),
                f"normalized_wider_effects[{index}].canonical_kind",
            )
            aspects = _canonical_aspects(
                effect.get("changed_aspects"),
                f"normalized_wider_effects[{index}].changed_aspects",
            )
            key = (semantic_id, canonical_kind, aspects)
            if key == base_key:
                continue
            normalized[key] = _signed_modify_change(
                semantic_id=semantic_id,
                canonical_kind=canonical_kind,
                changed_aspects=aspects,
            )

        return tuple(
            normalized[key]
            for key in sorted(
                normalized,
                key=lambda item: (
                    item[0],
                    item[1],
                    tuple(aspect.value for aspect in item[2]),
                ),
            )
        )


def _signed_modify_change(
    *,
    semantic_id: str,
    canonical_kind: str,
    changed_aspects: tuple[CanonicalAspect, ...],
) -> ActualChange:
    draft = ActualChange(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id=semantic_id,
        canonical_kind=canonical_kind,
        changed_aspects=changed_aspects,
        actual_change_hash="0" * 64,
    )
    return replace(
        draft,
        actual_change_hash=compute_actual_change_hash(draft),
    )


def _canonical_aspects(value: Any, field_name: str) -> tuple[CanonicalAspect, ...]:
    if isinstance(value, (str, bytes)) or value is None:
        raise RevitExecutionResultAdapterError(
            "REVIT_HOST_RESULT_INVALID",
            f"{field_name} must be a non-empty sequence.",
        )
    try:
        raw = tuple(value)
    except TypeError as exc:
        raise RevitExecutionResultAdapterError(
            "REVIT_HOST_RESULT_INVALID",
            f"{field_name} must be iterable.",
        ) from exc
    if not raw:
        raise RevitExecutionResultAdapterError(
            "REVIT_HOST_RESULT_INVALID",
            f"{field_name} must not be empty.",
        )

    aspects: set[CanonicalAspect] = set()
    for item in raw:
        try:
            aspects.add(item if isinstance(item, CanonicalAspect) else CanonicalAspect(str(item)))
        except ValueError as exc:
            raise RevitExecutionResultAdapterError(
                "REVIT_HOST_RESULT_INVALID",
                f"{field_name} contains unsupported canonical aspect {item!r}.",
            ) from exc
    return tuple(sorted(aspects, key=lambda aspect: aspect.value))


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RevitExecutionResultAdapterError(
            "REVIT_HOST_RESULT_INVALID",
            f"{field_name} must be a mapping.",
        )
    return value


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RevitExecutionResultAdapterError(
            "REVIT_HOST_RESULT_INVALID",
            f"{field_name} is required.",
        )
    return value.strip()


def _revision(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RevitExecutionResultAdapterError(
            "REVIT_HOST_RESULT_INVALID",
            f"{field_name} must be a non-negative integer.",
        )
    return value


__all__ = [
    "CommittedEffectUnnormalizableError",
    "RevitExecutionResultAdapter",
    "RevitExecutionResultAdapterError",
]
