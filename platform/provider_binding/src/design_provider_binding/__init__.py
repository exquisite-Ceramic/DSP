"""Public immutable Step31 provider-binding API."""

from .adapters import (
    ProviderBindingAdapter,
    ProviderBindingAdapterRegistry,
    native_constraints_satisfied,
    validate_native_constraints,
)
from .contracts import (
    EligibilityState,
    NativeConstraint,
    NativeConstraintOperator,
    NativeTargetBindingEvidence,
    ProviderBinding,
    ProviderBindingError,
    ProviderBindingMaterial,
    ProviderBindingRequest,
    ProviderBindingSet,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshot,
    ProviderPreconditionBinding,
)
from .hashing import (
    compute_binding_hash,
    compute_binding_set_hash,
    compute_candidate_fingerprint,
    compute_host_binding_fingerprint,
    compute_precondition_fingerprint,
    compute_provider_snapshot_hash,
    validate_provider_binding,
    validate_provider_binding_set_hash,
)
from .resolver import ProviderResolver

__all__ = [
    "EligibilityState",
    "NativeConstraint",
    "NativeConstraintOperator",
    "NativeTargetBindingEvidence",
    "ProviderBinding",
    "ProviderBindingAdapter",
    "ProviderBindingAdapterRegistry",
    "ProviderBindingError",
    "ProviderBindingMaterial",
    "ProviderBindingRequest",
    "ProviderBindingSet",
    "ProviderExecutionCandidate",
    "ProviderExecutionSnapshot",
    "ProviderPreconditionBinding",
    "ProviderResolver",
    "compute_binding_hash",
    "compute_binding_set_hash",
    "compute_candidate_fingerprint",
    "compute_host_binding_fingerprint",
    "compute_precondition_fingerprint",
    "compute_provider_snapshot_hash",
    "native_constraints_satisfied",
    "validate_native_constraints",
    "validate_provider_binding",
    "validate_provider_binding_set_hash",
]
