"""Deterministic provider-neutral semantic verification for Step33."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from design_approval_scope import (
    ApprovalScopeError,
    CanonicalAspect,
    validate_approval_scope_boundary,
)
from design_changeset import (
    ChangeSetError,
    ValidationTask,
    ValidationTaskKind,
    validate_changeset_integrity,
)

from .contracts import (
    ReconciliationError,
    SemanticVerificationRequest,
    SemanticVerificationResult,
    ValidationTaskResult,
    VerificationStatus,
    VerificationSubjectEvidence,
)
from .hashing import (
    compute_semantic_verification_hash,
    compute_validation_task_result_hash,
    validate_actual_delta_integrity,
    validate_verification_evidence_bundle_integrity,
)

_MISSING = object()


def _lineage_error(message: str) -> None:
    raise ReconciliationError("RECONCILIATION_LINEAGE_MISMATCH", message)


def _validate_authority_delta(request: SemanticVerificationRequest) -> None:
    authority = request.admitted_execution_authority
    delta = request.actual_delta
    joins = (
        ("grant_hash", authority.grant_hash, delta.grant_hash),
        ("binding_set_hash", authority.binding_set_hash, delta.binding_set_hash),
        ("execution_slice_hash", authority.execution_slice_hash, delta.execution_slice_hash),
        ("changeset_hash", authority.changeset_hash, delta.changeset_hash),
        ("approved_scope_hash", authority.approved_scope_hash, delta.approved_scope_hash),
        ("host_instance_id", authority.host_instance_id, delta.host_instance_id),
    )
    for field_name, expected, actual in joins:
        if expected != actual:
            _lineage_error(f"Step32 authority and ActualDelta {field_name} differ")


def _validate_boundary(request: SemanticVerificationRequest) -> None:
    try:
        validate_approval_scope_boundary(request.approval_scope_boundary)
    except ApprovalScopeError as exc:
        raise ReconciliationError(
            "VERIFY_INPUT_INVALID",
            "Step28 ApprovalScopeBoundary integrity validation failed",
            upstream_code=exc.code,
        ) from exc


def _validate_changeset(request: SemanticVerificationRequest) -> None:
    try:
        validate_changeset_integrity(
            request.canonical_changeset,
            request.approval_scope_boundary,
        )
    except ChangeSetError as exc:
        raise ReconciliationError(
            "VERIFY_INPUT_INVALID",
            "Step29 CanonicalChangeSet integrity validation failed",
            upstream_code=exc.code,
        ) from exc

    authority = request.admitted_execution_authority
    changeset = request.canonical_changeset
    boundary = request.approval_scope_boundary
    if changeset.changeset_hash != authority.changeset_hash:
        _lineage_error("CanonicalChangeSet does not match admitted execution authority")
    if boundary.scope_hash != authority.approved_scope_hash:
        _lineage_error("ApprovalScopeBoundary does not match admitted approved scope")


def _validate_requested_tasks(request: SemanticVerificationRequest) -> None:
    requested = request.validation_tasks
    if not requested:
        raise ReconciliationError(
            "VERIFY_INPUT_INVALID",
            "verification requires at least one Step29 ValidationTask",
        )
    expected_by_id = {
        task.validation_task_id: task
        for task in request.canonical_changeset.validation_tasks
    }
    seen: set[str] = set()
    for task in requested:
        if task.validation_task_id in seen:
            raise ReconciliationError(
                "VERIFY_INPUT_INVALID",
                "requested ValidationTask ids must be unique",
            )
        seen.add(task.validation_task_id)
        expected = expected_by_id.get(task.validation_task_id)
        if expected is None or task != expected:
            raise ReconciliationError(
                "VERIFY_INPUT_INVALID",
                "requested ValidationTask is not an exact Step29 task",
            )


def _environment_identity(value: object) -> tuple[object, object]:
    return (
        getattr(value, "environment_id", None),
        getattr(value, "content_hash", None),
    )


def _validate_bundle_lineage(request: SemanticVerificationRequest) -> None:
    authority = request.admitted_execution_authority
    changeset = request.canonical_changeset
    boundary = request.approval_scope_boundary
    delta = request.actual_delta
    bundle = request.verification_evidence_bundle

    joins = (
        ("changeset_hash", changeset.changeset_hash, bundle.changeset_hash),
        ("execution_slice_hash", authority.execution_slice_hash, bundle.execution_slice_hash),
        ("actual_delta_hash", delta.actual_delta_hash, bundle.actual_delta_hash),
    )
    for field_name, expected, actual in joins:
        if expected != actual:
            _lineage_error(f"VerificationEvidenceBundle {field_name} does not match request")

    environment = _environment_identity(bundle.semantic_environment_ref)
    if environment != _environment_identity(changeset.semantic_environment_ref):
        _lineage_error("verification SemanticEnvironment differs from ChangeSet environment")
    if environment != _environment_identity(boundary.semantic_environment_ref):
        _lineage_error("verification SemanticEnvironment differs from approved scope environment")


def _validate_post_snapshot_lineage(request: SemanticVerificationRequest) -> None:
    delta = request.actual_delta
    bundle = request.verification_evidence_bundle
    snapshot = bundle.post_execution_snapshot_ref
    projection = bundle.post_execution_projection_ref

    if snapshot.document_ref != delta.document_ref:
        _lineage_error("post-execution snapshot document does not match ActualDelta document")
    expected_revision = str(delta.revision_after)
    if bundle.base_host_revision != expected_revision:
        _lineage_error("verification base_host_revision does not match ActualDelta revision_after")
    if snapshot.base_host_revision != expected_revision:
        _lineage_error("post-execution snapshot revision does not match ActualDelta revision_after")
    if snapshot.projection_ref != projection:
        _lineage_error("post-execution snapshot projection does not match bundle projection")
    if _environment_identity(snapshot.semantic_environment_ref) != _environment_identity(
        bundle.semantic_environment_ref
    ):
        _lineage_error("post-execution snapshot SemanticEnvironment does not match bundle")

    for subject in bundle.subject_evidence:
        if subject.snapshot_id != snapshot.snapshot_id or subject.snapshot_hash != snapshot.hash:
            _lineage_error("post-execution subject evidence is bound to another snapshot")
        if subject.projection_ref != projection:
            _lineage_error("post-execution subject evidence is bound to another projection")


def _operation_for_task(request: SemanticVerificationRequest, task: ValidationTask):
    if task.kind is not ValidationTaskKind.CANONICAL_OPERATION:
        return None
    operations = (
        request.canonical_changeset.root_operation,
        *request.canonical_changeset.derived_operations,
    )
    candidates = tuple(
        operation
        for operation in operations
        if f"{operation.canonical_operation}@{operation.canonical_operation_version}"
        == task.canonical_operation_ref
        and operation.targets == task.subject_semantic_ids
    )
    if len(candidates) != 1:
        raise ReconciliationError(
            "VERIFY_INPUT_INVALID",
            "canonical ValidationTask cannot resolve exactly one Step29 operation",
        )
    return candidates[0]


def _path_value(subject: VerificationSubjectEvidence, path: str) -> object:
    current: object = subject
    for segment in path.split("."):
        if not segment:
            return _MISSING
        if isinstance(current, Mapping):
            if segment not in current:
                return _MISSING
            current = current[segment]
        else:
            if not hasattr(current, segment):
                return _MISSING
            current = getattr(current, segment)
    return current


def _required_aspect(operator: str, path: object) -> CanonicalAspect | None:
    if operator == "RELATIONSHIP_EXISTS":
        return CanonicalAspect.RELATIONSHIPS
    if operator == "CLASSIFICATION_IS":
        return CanonicalAspect.CLASSIFICATION
    if not isinstance(path, str):
        return None
    prefix = path.split(".", 1)[0]
    return {
        "properties": CanonicalAspect.PROPERTIES,
        "placement": CanonicalAspect.PLACEMENT,
        "geometry_evidence": CanonicalAspect.GEOMETRY,
        "relationships": CanonicalAspect.RELATIONSHIPS,
        "constraints": CanonicalAspect.CONSTRAINTS,
        "classification": CanonicalAspect.CLASSIFICATION,
    }.get(prefix)


def _mapping_contains(candidate: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if key not in candidate:
            return False
        actual_value = candidate[key]
        if isinstance(expected_value, Mapping):
            if not isinstance(actual_value, Mapping):
                return False
            if not _mapping_contains(actual_value, expected_value):
                return False
        elif actual_value != expected_value:
            return False
    return True


def _resolved_subjects(assertion: Mapping[str, Any], operation) -> tuple[str, ...] | None:
    selector = assertion.get("subjects")
    if not isinstance(selector, Mapping) or set(selector) != {"from_argument"}:
        return None
    if operation is None:
        return None
    argument_name = selector.get("from_argument")
    if not isinstance(argument_name, str) or argument_name not in operation.arguments:
        return None
    raw = operation.arguments[argument_name]
    if isinstance(raw, str) or isinstance(raw, Mapping):
        return None
    try:
        subjects = tuple(raw)
    except TypeError:
        return None
    if not subjects or any(not isinstance(value, str) or not value for value in subjects):
        return None
    return tuple(subjects)


def _evaluate_assertion(
    assertion: Mapping[str, Any],
    operation,
    subjects_by_id: Mapping[str, VerificationSubjectEvidence],
) -> tuple[VerificationStatus, str | None]:
    operator = assertion.get("operator")
    if not isinstance(operator, str):
        return VerificationStatus.EVIDENCE_INSUFFICIENT, "VERIFY_CONTRACT_UNSUPPORTED"
    subjects = _resolved_subjects(assertion, operation)
    if subjects is None:
        return VerificationStatus.EVIDENCE_INSUFFICIENT, "VERIFY_CONTRACT_UNSUPPORTED"

    if operator == "DELTA_EQUALS_ARGUMENT":
        return VerificationStatus.EVIDENCE_INSUFFICIENT, "REQUIRED_BASELINE_MISSING"

    for semantic_id in subjects:
        subject = subjects_by_id.get(semantic_id)
        if subject is None:
            return VerificationStatus.EVIDENCE_INSUFFICIENT, "REQUIRED_FIELD_MISSING"
        required_aspect = _required_aspect(operator, assertion.get("path"))
        if required_aspect is not None and required_aspect not in subject.evidence_aspects:
            return VerificationStatus.EVIDENCE_INSUFFICIENT, "REQUIRED_FIELD_MISSING"

        if operator in {"EXISTS", "NOT_EXISTS", "EQUALS_LITERAL", "EQUALS_ARGUMENT"}:
            path = assertion.get("path")
            if not isinstance(path, str) or not path:
                return VerificationStatus.EVIDENCE_INSUFFICIENT, "VERIFY_CONTRACT_UNSUPPORTED"
            actual = _path_value(subject, path)
            if operator == "EXISTS":
                if actual is _MISSING:
                    return VerificationStatus.EVIDENCE_INSUFFICIENT, "REQUIRED_FIELD_MISSING"
                continue
            if operator == "NOT_EXISTS":
                if actual is not _MISSING:
                    return VerificationStatus.FAILED, "EXPECTED_VALUE_MISMATCH"
                continue
            if actual is _MISSING:
                return VerificationStatus.EVIDENCE_INSUFFICIENT, "REQUIRED_FIELD_MISSING"
            if operator == "EQUALS_LITERAL":
                if "value" not in assertion:
                    return VerificationStatus.EVIDENCE_INSUFFICIENT, "VERIFY_CONTRACT_UNSUPPORTED"
                expected = assertion["value"]
            else:
                argument_name = assertion.get("argument")
                if (
                    operation is None
                    or not isinstance(argument_name, str)
                    or argument_name not in operation.arguments
                ):
                    return VerificationStatus.EVIDENCE_INSUFFICIENT, "VERIFY_CONTRACT_UNSUPPORTED"
                expected = operation.arguments[argument_name]
            if actual != expected:
                return VerificationStatus.FAILED, "EXPECTED_VALUE_MISMATCH"
            continue

        if operator == "RELATIONSHIP_EXISTS":
            expected = assertion.get("relationship")
            if not isinstance(expected, Mapping):
                return VerificationStatus.EVIDENCE_INSUFFICIENT, "VERIFY_CONTRACT_UNSUPPORTED"
            if not any(_mapping_contains(candidate, expected) for candidate in subject.relationships):
                return VerificationStatus.FAILED, "EXPECTED_VALUE_MISMATCH"
            continue

        if operator == "CLASSIFICATION_IS":
            expected = assertion.get("value")
            if not isinstance(expected, str):
                return VerificationStatus.EVIDENCE_INSUFFICIENT, "VERIFY_CONTRACT_UNSUPPORTED"
            if expected not in subject.classification:
                return VerificationStatus.FAILED, "EXPECTED_VALUE_MISMATCH"
            continue

        return VerificationStatus.EVIDENCE_INSUFFICIENT, "VERIFY_CONTRACT_UNSUPPORTED"

    return VerificationStatus.PASSED, None


def _result_for_task(
    request: SemanticVerificationRequest,
    task: ValidationTask,
) -> ValidationTaskResult:
    bundle = request.verification_evidence_bundle
    contract_by_ref = {
        evidence.contract_ref: evidence.contract_body
        for evidence in bundle.contract_evidence
    }
    contract = contract_by_ref.get(task.contract_ref)
    if contract is None:
        status = VerificationStatus.EVIDENCE_INSUFFICIENT
        codes = ("REQUIRED_FIELD_MISSING",)
    elif contract.get("type") != "SEMANTIC_ASSERTIONS_V1":
        status = VerificationStatus.EVIDENCE_INSUFFICIENT
        codes = ("VERIFY_CONTRACT_UNSUPPORTED",)
    else:
        assertions = contract.get("assertions")
        if not isinstance(assertions, tuple):
            status = VerificationStatus.EVIDENCE_INSUFFICIENT
            codes = ("VERIFY_CONTRACT_UNSUPPORTED",)
        else:
            operation = _operation_for_task(request, task)
            subjects_by_id = {
                subject.semantic_id: subject for subject in bundle.subject_evidence
            }
            outcomes = tuple(
                _evaluate_assertion(assertion, operation, subjects_by_id)
                if isinstance(assertion, Mapping)
                else (
                    VerificationStatus.EVIDENCE_INSUFFICIENT,
                    "VERIFY_CONTRACT_UNSUPPORTED",
                )
                for assertion in assertions
            )
            failure_codes = tuple(
                sorted({code for _, code in outcomes if code is not None})
            )
            if any(state is VerificationStatus.FAILED for state, _ in outcomes):
                status = VerificationStatus.FAILED
            elif any(
                state is VerificationStatus.EVIDENCE_INSUFFICIENT
                for state, _ in outcomes
            ):
                status = VerificationStatus.EVIDENCE_INSUFFICIENT
            else:
                status = VerificationStatus.PASSED
            codes = failure_codes

    draft = ValidationTaskResult(
        validation_task_id=task.validation_task_id,
        status=status,
        observations=(),
        failure_codes=codes,
        task_result_hash="0" * 64,
    )
    return replace(
        draft,
        task_result_hash=compute_validation_task_result_hash(draft),
    )


def _aggregate(task_results: tuple[ValidationTaskResult, ...]) -> VerificationStatus:
    if any(result.status is VerificationStatus.FAILED for result in task_results):
        return VerificationStatus.FAILED
    if any(
        result.status is VerificationStatus.EVIDENCE_INSUFFICIENT
        for result in task_results
    ):
        return VerificationStatus.EVIDENCE_INSUFFICIENT
    return VerificationStatus.PASSED


class SemanticVerifier:
    """Evaluate exact Step29 validation tasks over exact snapshot-bound evidence."""

    def verify(self, request: SemanticVerificationRequest) -> SemanticVerificationResult:
        if not isinstance(request, SemanticVerificationRequest):
            raise ReconciliationError(
                "VERIFY_INPUT_INVALID",
                "request must be SemanticVerificationRequest",
            )

        # Validation precedence is normative and intentionally explicit.
        validate_actual_delta_integrity(request.actual_delta)
        _validate_authority_delta(request)
        _validate_boundary(request)
        _validate_changeset(request)
        _validate_requested_tasks(request)
        validate_verification_evidence_bundle_integrity(
            request.verification_evidence_bundle
        )
        _validate_bundle_lineage(request)
        _validate_post_snapshot_lineage(request)

        task_results = tuple(
            _result_for_task(request, task) for task in request.validation_tasks
        )
        status = _aggregate(task_results)
        bundle = request.verification_evidence_bundle
        draft = SemanticVerificationResult(
            verification_id="SVR-DRAFT",
            changeset_hash=request.canonical_changeset.changeset_hash,
            execution_slice_hash=request.admitted_execution_authority.execution_slice_hash,
            actual_delta_hash=request.actual_delta.actual_delta_hash,
            evidence_bundle_hash=bundle.evidence_bundle_hash,
            task_results=task_results,
            status=status,
            verification_hash="0" * 64,
        )
        verification_hash = compute_semantic_verification_hash(draft)
        return replace(
            draft,
            verification_id=f"SVR-{verification_hash[:12]}",
            verification_hash=verification_hash,
        )


__all__ = ["SemanticVerifier"]
