"""Public API for Step28 approval effect scope."""

from .contracts import (
    ApprovalScopeBoundary,
    ApprovalScopeDefinition,
    ApprovalScopeError,
    ApprovalScopePlanRequest,
    CanonicalAspect,
    CanonicalEffectEvidence,
    CreationRule,
    DeletionRule,
    DirectEntityEffect,
    EntityPredicate,
    EntitySelector,
    ExecutionSliceScopeRule,
    ExistingEntityRule,
    PredicateField,
    PredicateOperator,
    PredicateTerm,
    ScopeEffectRecipe,
)
from .hashing import (
    bind_changeset,
    compute_scope_body_hash,
    validate_approval_scope_boundary,
)
from .planner import ApprovalScopePlanner, direct_existing_rule_id, recipe_existing_rule_id

__all__ = [
    "ApprovalScopeBoundary",
    "ApprovalScopeDefinition",
    "ApprovalScopeError",
    "ApprovalScopePlanRequest",
    "ApprovalScopePlanner",
    "CanonicalAspect",
    "CanonicalEffectEvidence",
    "CreationRule",
    "DeletionRule",
    "DirectEntityEffect",
    "EntityPredicate",
    "EntitySelector",
    "ExecutionSliceScopeRule",
    "ExistingEntityRule",
    "PredicateField",
    "PredicateOperator",
    "PredicateTerm",
    "ScopeEffectRecipe",
    "bind_changeset",
    "compute_scope_body_hash",
    "direct_existing_rule_id",
    "recipe_existing_rule_id",
    "validate_approval_scope_boundary",
]
