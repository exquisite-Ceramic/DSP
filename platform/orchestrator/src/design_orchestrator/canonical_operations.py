"""Platform-owned canonical operation contracts for the LLM action space.

Provider MCP ``inputSchema`` values describe provider execution interfaces.
These definitions describe Host-independent semantic arguments selected by the
LLM. Translation between the two belongs to later ProviderBinding/input-adapter
logic, not to D4 Operation Resolution.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


_VALID_CATEGORIES = frozenset({"MODEL_OPERATION", "INTERACTION", "VIEW", "CONTEXT"})


@dataclass(frozen=True, slots=True)
class CanonicalOperationDefinition:
    """Platform-owned contract for one canonical semantic operation."""

    canonical_operation: str
    category: str
    input_schema: dict[str, Any]
    verification_contract: dict[str, Any]
    context_freshness_requirements: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        canonical_operation = self.canonical_operation.strip()
        if not canonical_operation:
            raise ValueError("canonical_operation is required")
        if self.category not in _VALID_CATEGORIES:
            raise ValueError(f"invalid canonical operation category: {self.category!r}")
        if not isinstance(self.input_schema, dict):
            raise ValueError("canonical input_schema must be an object")
        if not isinstance(self.verification_contract, dict):
            raise ValueError("canonical verification_contract must be an object")

        object.__setattr__(self, "canonical_operation", canonical_operation)
        object.__setattr__(self, "input_schema", deepcopy(self.input_schema))
        object.__setattr__(
            self,
            "verification_contract",
            deepcopy(self.verification_contract),
        )
        object.__setattr__(
            self,
            "context_freshness_requirements",
            tuple(deepcopy(item) for item in self.context_freshness_requirements),
        )


MOVE_V1 = CanonicalOperationDefinition(
    canonical_operation="move.v1",
    category="MODEL_OPERATION",
    input_schema={
        "type": "object",
        "properties": {
            "targets": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "displacement": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
        },
        "required": ["targets", "displacement"],
        "additionalProperties": False,
    },
    verification_contract={"type": "HOST_READ_BACK"},
)


MVP_CANONICAL_OPERATIONS: tuple[CanonicalOperationDefinition, ...] = (MOVE_V1,)
