"""Platform-owned canonical operation contracts for the LLM action space.

Provider MCP ``inputSchema`` values describe provider execution interfaces.
These definitions describe Host-independent semantic arguments selected by the
LLM. Translation between the two belongs to later ProviderBinding/input-adapter
logic, not to D4 Operation Resolution.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any


_VALID_CATEGORIES = frozenset({"MODEL_OPERATION", "INTERACTION", "VIEW", "CONTEXT"})


class SlotBindingClass(str, Enum):
    """Owner/source class for one canonical action input slot."""

    INTENT = "INTENT"
    CONTEXT = "CONTEXT"
    CANONICAL_DEFAULT = "CANONICAL_DEFAULT"
    DERIVED = "DERIVED"
    PROVIDER = "PROVIDER"


def _copy_mapping_sequence(
    value: tuple[dict[str, Any], ...],
    *,
    field_name: str,
) -> tuple[dict[str, Any], ...]:
    copied: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field_name} entries must be objects")
        copied.append(deepcopy(dict(item)))
    return tuple(copied)


@dataclass(frozen=True, slots=True)
class CanonicalOperationDefinition:
    """Platform-owned contract for one canonical semantic operation."""

    canonical_operation: str
    version: str
    title: str
    description: str
    category: str
    input_schema: dict[str, Any]
    slot_binding_policy: Mapping[str, SlotBindingClass | str]
    verification_contract: dict[str, Any]
    canonical_entity_constraints: tuple[str, ...] = ()
    context_freshness_requirements: tuple[dict[str, Any], ...] = ()
    operation_freshness_requirements: tuple[dict[str, Any], ...] = ()
    coverage_requirements: tuple[dict[str, Any], ...] = ()
    assurance_requirements: tuple[dict[str, Any], ...] = ()
    effects: tuple[Any, ...] = ()

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

        normalized_slot_policy = MappingProxyType(
            {
                str(slot): (
                    value
                    if isinstance(value, SlotBindingClass)
                    else SlotBindingClass(str(value))
                )
                for slot, value in self.slot_binding_policy.items()
            }
        )

        object.__setattr__(self, "canonical_operation", canonical_operation)
        object.__setattr__(self, "version", self.version.strip())
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "input_schema", deepcopy(self.input_schema))
        object.__setattr__(self, "slot_binding_policy", normalized_slot_policy)
        object.__setattr__(
            self,
            "verification_contract",
            deepcopy(self.verification_contract),
        )
        object.__setattr__(
            self,
            "canonical_entity_constraints",
            tuple(str(item) for item in self.canonical_entity_constraints),
        )
        object.__setattr__(
            self,
            "context_freshness_requirements",
            _copy_mapping_sequence(
                self.context_freshness_requirements,
                field_name="context_freshness_requirements",
            ),
        )
        object.__setattr__(
            self,
            "operation_freshness_requirements",
            _copy_mapping_sequence(
                self.operation_freshness_requirements,
                field_name="operation_freshness_requirements",
            ),
        )
        object.__setattr__(
            self,
            "coverage_requirements",
            _copy_mapping_sequence(
                self.coverage_requirements,
                field_name="coverage_requirements",
            ),
        )
        object.__setattr__(
            self,
            "assurance_requirements",
            _copy_mapping_sequence(
                self.assurance_requirements,
                field_name="assurance_requirements",
            ),
        )
        object.__setattr__(
            self,
            "effects",
            tuple(deepcopy(item) for item in self.effects),
        )


MOVE_V1 = CanonicalOperationDefinition(
    canonical_operation="move.v1",
    version="1.0.0",
    title="Move entities",
    description="Move the selected canonical design entities by a displacement vector.",
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
    slot_binding_policy={
        "targets": SlotBindingClass.CONTEXT,
        "displacement": SlotBindingClass.INTENT,
    },
    canonical_entity_constraints=(),
    operation_freshness_requirements=(
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    ),
    coverage_requirements=(),
    assurance_requirements=(),
    effects=("PLACEMENT", "GEOMETRY"),
    verification_contract={"type": "HOST_READ_BACK"},
)


MVP_CANONICAL_OPERATIONS: tuple[CanonicalOperationDefinition, ...] = (MOVE_V1,)
