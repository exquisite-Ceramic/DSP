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
import re
from types import MappingProxyType
from typing import Any


_VALID_CATEGORIES = frozenset({"MODEL_OPERATION", "INTERACTION", "VIEW", "CONTEXT"})
_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class SlotBindingClass(str, Enum):
    """Owner/source class for one canonical action input slot."""

    INTENT = "INTENT"
    CONTEXT = "CONTEXT"
    CANONICAL_DEFAULT = "CANONICAL_DEFAULT"
    DERIVED = "DERIVED"
    PROVIDER = "PROVIDER"


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


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
        canonical_operation = _required_text(
            self.canonical_operation,
            field_name="canonical_operation",
        )
        version = _required_text(self.version, field_name="version")
        if _VERSION_PATTERN.fullmatch(version) is None:
            raise ValueError("version must use numeric MAJOR.MINOR.PATCH")
        title = _required_text(self.title, field_name="title")
        description = _required_text(self.description, field_name="description")

        if self.category not in _VALID_CATEGORIES:
            raise ValueError(f"invalid canonical operation category: {self.category!r}")
        if not isinstance(self.input_schema, dict):
            raise ValueError("canonical input_schema must be an object")
        if not isinstance(self.verification_contract, dict):
            raise ValueError("canonical verification_contract must be an object")

        properties = self.input_schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError("canonical input_schema properties must be an object")
        property_names = {str(name) for name in properties}

        required = self.input_schema.get("required", [])
        if not isinstance(required, list) or any(
            not isinstance(name, str) for name in required
        ):
            raise ValueError("canonical input_schema required must be an array of strings")
        unknown_required = sorted(set(required) - property_names)
        if unknown_required:
            raise ValueError(
                "canonical input_schema required references unknown properties: "
                f"{unknown_required}"
            )

        if not isinstance(self.slot_binding_policy, Mapping):
            raise ValueError("slot_binding_policy must be an object")
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
        policy_names = set(normalized_slot_policy)
        missing_policy = sorted(property_names - policy_names)
        if missing_policy:
            raise ValueError(f"missing slot binding policy: {missing_policy}")
        unknown_policy = sorted(policy_names - property_names)
        if unknown_policy:
            raise ValueError(
                "slot binding policy references unknown canonical slot: "
                f"{unknown_policy}"
            )

        object.__setattr__(self, "canonical_operation", canonical_operation)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "description", description)
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

    def intent_input_schema(self) -> dict[str, Any]:
        """Project the canonical schema to only LLM/user intent-owned slots."""

        schema = deepcopy(self.input_schema)
        properties = schema.get("properties", {})
        visible_names = [
            name
            for name in properties
            if self.slot_binding_policy[name] is SlotBindingClass.INTENT
        ]
        schema["properties"] = {
            name: deepcopy(properties[name]) for name in visible_names
        }
        if "required" in schema:
            visible = set(visible_names)
            schema["required"] = [
                name for name in schema["required"] if name in visible
            ]
        return schema


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
