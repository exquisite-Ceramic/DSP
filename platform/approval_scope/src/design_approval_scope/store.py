"""Step28 owner-local immutable V2 approval-scope reference store."""

from __future__ import annotations

from .contracts import (
    ApprovalScopeBoundaryV2,
    ApprovalScopeDefinitionV2,
    ApprovalScopeError,
)
from .hashing import (
    validate_approval_scope_boundary_v2,
    validate_approval_scope_definition_v2,
)


class InMemoryApprovalScopeStore:
    """Reference in-memory lookup for authoritative Step28 V2 artifacts."""

    def __init__(self) -> None:
        self._definitions: dict[str, ApprovalScopeDefinitionV2] = {}
        self._boundaries: dict[str, ApprovalScopeBoundaryV2] = {}

    def put_definition(self, definition: ApprovalScopeDefinitionV2) -> None:
        """Store a validated V2 definition; exact replay is idempotent."""
        if not isinstance(definition, ApprovalScopeDefinitionV2):
            raise TypeError("definition must be ApprovalScopeDefinitionV2")
        existing = self._definitions.get(definition.scope_definition_id)
        if existing is not None and existing != definition:
            raise ApprovalScopeError(
                "APPROVAL_SCOPE_REFERENCE_CONFLICT",
                "approval scope definition reference conflicts with existing content",
            )
        validate_approval_scope_definition_v2(definition)
        if existing is None:
            self._definitions[definition.scope_definition_id] = definition

    def get_definition(self, scope_definition_id: str) -> ApprovalScopeDefinitionV2:
        """Resolve and revalidate one authoritative V2 definition."""
        try:
            definition = self._definitions[scope_definition_id]
        except KeyError as exc:
            raise ApprovalScopeError(
                "APPROVAL_SCOPE_REFERENCE_NOT_FOUND",
                f"approval scope definition is unresolved: {scope_definition_id}",
            ) from exc
        validate_approval_scope_definition_v2(definition)
        return definition

    def put_boundary(self, boundary: ApprovalScopeBoundaryV2) -> None:
        """Store a validated final V2 approval boundary; replay is idempotent."""
        if not isinstance(boundary, ApprovalScopeBoundaryV2):
            raise TypeError("boundary must be ApprovalScopeBoundaryV2")
        existing = self._boundaries.get(boundary.scope_id)
        if existing is not None and existing != boundary:
            raise ApprovalScopeError(
                "APPROVAL_SCOPE_REFERENCE_CONFLICT",
                "approval scope boundary reference conflicts with existing content",
            )
        validate_approval_scope_boundary_v2(boundary)
        if existing is None:
            self._boundaries[boundary.scope_id] = boundary

    def get_boundary(self, scope_id: str) -> ApprovalScopeBoundaryV2:
        """Resolve and revalidate one authoritative final V2 boundary."""
        try:
            boundary = self._boundaries[scope_id]
        except KeyError as exc:
            raise ApprovalScopeError(
                "APPROVAL_SCOPE_REFERENCE_NOT_FOUND",
                f"approval scope boundary is unresolved: {scope_id}",
            ) from exc
        validate_approval_scope_boundary_v2(boundary)
        return boundary


__all__ = ["InMemoryApprovalScopeStore"]
