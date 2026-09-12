"""Provider-neutral canonical convergence 公共 API。"""

from .contracts import (
    CanonicalFieldEvidence,
    ConvergenceEvidenceSet,
    ConvergenceResult,
    ConvergenceStatus,
    ConvergenceVerificationError,
    MaterializationCanonicalEvidence,
)
from .evidence import (
    build_convergence_evidence_set,
    build_materialization_canonical_evidence,
)
from .hashing import (
    compute_convergence_evidence_set_hash,
    compute_convergence_profile_hash,
    compute_convergence_result_hash,
    compute_materialization_canonical_evidence_hash,
)
from .profile import (
    ConvergenceComparisonMode,
    ConvergenceComparisonProfile,
    ConvergenceFieldRule,
    ConvergenceProfileBuildRequest,
    ConvergenceProfileError,
    build_convergence_profile,
)
from .verifier import CrossHostConvergenceVerifier

__all__ = [
    "CanonicalFieldEvidence",
    "ConvergenceComparisonMode",
    "ConvergenceComparisonProfile",
    "ConvergenceEvidenceSet",
    "ConvergenceFieldRule",
    "ConvergenceProfileBuildRequest",
    "ConvergenceProfileError",
    "ConvergenceResult",
    "ConvergenceStatus",
    "ConvergenceVerificationError",
    "CrossHostConvergenceVerifier",
    "MaterializationCanonicalEvidence",
    "build_convergence_evidence_set",
    "build_convergence_profile",
    "build_materialization_canonical_evidence",
    "compute_convergence_evidence_set_hash",
    "compute_convergence_profile_hash",
    "compute_convergence_result_hash",
    "compute_materialization_canonical_evidence_hash",
]
