"""Public provider-neutral Step33 execution reconciliation API."""

from .contracts import (
    ActualChange,
    ActualChangeKind,
    ActualDelta,
    ReconciliationError,
    ScopeComparisonRequest,
    ScopeComparisonResult,
    ScopeComparisonStatus,
    ScopeMatch,
    ScopeViolation,
    SemanticVerificationRequest,
    SemanticVerificationResult,
    ValidationTaskResult,
    VerificationContractEvidence,
    VerificationEvidenceBundle,
    VerificationStatus,
    VerificationSubjectEvidence,
)
from .hashing import (
    compute_actual_change_hash,
    compute_actual_delta_hash,
    compute_execution_saga_definition_hash,
    compute_scope_comparison_hash,
    compute_semantic_verification_hash,
    compute_validation_task_result_hash,
    compute_verification_evidence_bundle_hash,
    validate_actual_delta_integrity,
    validate_verification_evidence_bundle_integrity,
)
from .saga import ExecutionSagaBuilder
from .saga_contracts import (
    ExecutionSagaDefinition,
    SliceDependency,
    SliceValidationAssignment,
)
from .scope_comparator import ScopeComparator
from .verifier import SemanticVerifier

__all__ = [
    "ActualChange",
    "ActualChangeKind",
    "ActualDelta",
    "ExecutionSagaBuilder",
    "ExecutionSagaDefinition",
    "ReconciliationError",
    "ScopeComparator",
    "ScopeComparisonRequest",
    "ScopeComparisonResult",
    "ScopeComparisonStatus",
    "ScopeMatch",
    "ScopeViolation",
    "SemanticVerificationRequest",
    "SemanticVerificationResult",
    "SemanticVerifier",
    "SliceDependency",
    "SliceValidationAssignment",
    "ValidationTaskResult",
    "VerificationContractEvidence",
    "VerificationEvidenceBundle",
    "VerificationStatus",
    "VerificationSubjectEvidence",
    "compute_actual_change_hash",
    "compute_actual_delta_hash",
    "compute_execution_saga_definition_hash",
    "compute_scope_comparison_hash",
    "compute_semantic_verification_hash",
    "compute_validation_task_result_hash",
    "compute_verification_evidence_bundle_hash",
    "validate_actual_delta_integrity",
    "validate_verification_evidence_bundle_integrity",
]
