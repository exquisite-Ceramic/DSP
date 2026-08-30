"""Public provider-neutral Step33 execution reconciliation API."""

from .compensation import (
    CompensationExecutionRef,
    CompensationProposal,
    CompensationProposalRequest,
    ExecutionSagaPlanner,
    compute_compensation_proposal_hash,
    validate_compensation_proposal_integrity,
)
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
from .failure_store import InMemoryExecutionSagaStore
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
from .saga_state import (
    ExecutionSagaStatus,
    SliceReconciliationState,
    SliceReconciliationStatus,
    StoredExecutionSaga,
)
from .scope_comparator import ScopeComparator
from .store import ExecutionSagaStore
from .verifier import SemanticVerifier

__all__ = [
    "ActualChange",
    "ActualChangeKind",
    "ActualDelta",
    "CompensationExecutionRef",
    "CompensationProposal",
    "CompensationProposalRequest",
    "ExecutionSagaBuilder",
    "ExecutionSagaDefinition",
    "ExecutionSagaPlanner",
    "ExecutionSagaStatus",
    "ExecutionSagaStore",
    "InMemoryExecutionSagaStore",
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
    "SliceReconciliationState",
    "SliceReconciliationStatus",
    "SliceValidationAssignment",
    "StoredExecutionSaga",
    "ValidationTaskResult",
    "VerificationContractEvidence",
    "VerificationEvidenceBundle",
    "VerificationStatus",
    "VerificationSubjectEvidence",
    "compute_actual_change_hash",
    "compute_actual_delta_hash",
    "compute_compensation_proposal_hash",
    "compute_execution_saga_definition_hash",
    "compute_scope_comparison_hash",
    "compute_semantic_verification_hash",
    "compute_validation_task_result_hash",
    "compute_verification_evidence_bundle_hash",
    "validate_actual_delta_integrity",
    "validate_compensation_proposal_integrity",
    "validate_verification_evidence_bundle_integrity",
]
