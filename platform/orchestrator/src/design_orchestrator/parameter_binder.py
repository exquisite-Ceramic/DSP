"""Deterministic D6 binding for platform-owned canonical action slots.

This module consumes canonical operation definitions plus a small snapshot-bound
read model. It binds only platform canonical values and leaves PROVIDER-class
slots deferred to the later execution stage.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from jsonschema import SchemaError, ValidationError, validate

from design_orchestrator.canonical_operations import (
    CanonicalOperationDefinition,
    MOVE_V1,
    SET_WALL_THICKNESS_V1,
    SlotBindingClass,
)


class BindingError(ValueError):
    """Raised when deterministic canonical slot binding cannot be completed."""


class BindingResolverKind(str, Enum):
    """Explicit deterministic source used for one non-INTENT canonical slot."""

    CONTEXT_SELECTION = "CONTEXT_SELECTION"
    CONTEXT_VALUE = "CONTEXT_VALUE"
    CANONICAL_DEFAULT = "CANONICAL_DEFAULT"
    DERIVED = "DERIVED"


_UNSET = object()


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _readonly_copy(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("value must be a mapping")
    return MappingProxyType(deepcopy(dict(value)))


def _copy_requirement_tuple(
    values: Iterable[Mapping[str, Any]],
    *,
    field_name: str,
) -> tuple[dict[str, Any], ...]:
    copied: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, Mapping):
            raise TypeError(f"{field_name} entries must be mappings")
        copied.append(deepcopy(dict(item)))
    return tuple(copied)


@dataclass(frozen=True, slots=True)
class OperationProposal:
    """Canonical operation choice plus LLM/user-owned INTENT arguments only."""

    canonical_operation: str
    intent_arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_operation",
            _required_text(self.canonical_operation, field_name="canonical_operation"),
        )
        object.__setattr__(self, "intent_arguments", _readonly_copy(self.intent_arguments))


@dataclass(frozen=True, slots=True)
class ParameterBindingContext:
    """Small provider-neutral binding view tied to one planning ContextSnapshot."""

    context_snapshot_id: str
    context_snapshot_hash: str
    document_ref: str
    semantic_environment_ref: str
    selection: tuple[str, ...] = ()
    context_values: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "context_snapshot_id",
            "context_snapshot_hash",
            "document_ref",
            "semantic_environment_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )

        selection = tuple(
            _required_text(item, field_name="selection semantic_id")
            for item in self.selection
        )
        if len(set(selection)) != len(selection):
            raise ValueError("selection semantic_id values must be unique")
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "context_values", _readonly_copy(self.context_values))


@dataclass(frozen=True, slots=True)
class CanonicalOperationRef:
    canonical_operation: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_operation",
            _required_text(self.canonical_operation, field_name="canonical_operation"),
        )
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )


@dataclass(frozen=True, slots=True)
class ContextSnapshotRef:
    context_snapshot_id: str
    context_snapshot_hash: str
    document_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "context_snapshot_id",
            "context_snapshot_hash",
            "document_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )


@dataclass(frozen=True, slots=True)
class SlotBindingEvidence:
    slot: str
    binding_class: SlotBindingClass
    source: str
    source_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", _required_text(self.slot, field_name="slot"))
        if not isinstance(self.binding_class, SlotBindingClass):
            object.__setattr__(
                self,
                "binding_class",
                SlotBindingClass(str(self.binding_class)),
            )
        object.__setattr__(
            self,
            "source",
            _required_text(self.source, field_name="source"),
        )
        if self.source_ref is not None:
            object.__setattr__(
                self,
                "source_ref",
                _required_text(self.source_ref, field_name="source_ref"),
            )


@dataclass(frozen=True, slots=True)
class PlanningRequirements:
    operation_freshness_requirements: tuple[dict[str, Any], ...] = ()
    coverage_requirements: tuple[dict[str, Any], ...] = ()
    assurance_requirements: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "operation_freshness_requirements",
            "coverage_requirements",
            "assurance_requirements",
        ):
            object.__setattr__(
                self,
                field_name,
                _copy_requirement_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )


@dataclass(frozen=True, slots=True)
class BoundOperationProposal:
    operation: CanonicalOperationRef
    arguments: Mapping[str, Any]
    binding_evidence: Mapping[str, SlotBindingEvidence]
    context_snapshot_ref: ContextSnapshotRef
    planning_requirements: PlanningRequirements
    semantic_environment_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.operation, CanonicalOperationRef):
            raise TypeError("operation must be a CanonicalOperationRef")
        if not isinstance(self.context_snapshot_ref, ContextSnapshotRef):
            raise TypeError("context_snapshot_ref must be a ContextSnapshotRef")
        if not isinstance(self.planning_requirements, PlanningRequirements):
            raise TypeError("planning_requirements must be PlanningRequirements")
        object.__setattr__(self, "arguments", _readonly_copy(self.arguments))

        if not isinstance(self.binding_evidence, Mapping):
            raise TypeError("binding_evidence must be a mapping")
        evidence = dict(self.binding_evidence)
        if any(not isinstance(item, SlotBindingEvidence) for item in evidence.values()):
            raise TypeError("binding_evidence values must be SlotBindingEvidence")
        object.__setattr__(self, "binding_evidence", MappingProxyType(evidence))
        object.__setattr__(
            self,
            "semantic_environment_ref",
            _required_text(
                self.semantic_environment_ref,
                field_name="semantic_environment_ref",
            ),
        )


@dataclass(frozen=True, slots=True)
class SlotBindingRecipe:
    slot: str
    resolver_kind: BindingResolverKind
    source_key: str | None = None
    default_value: Any = _UNSET

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", _required_text(self.slot, field_name="slot"))
        if not isinstance(self.resolver_kind, BindingResolverKind):
            object.__setattr__(
                self,
                "resolver_kind",
                BindingResolverKind(str(self.resolver_kind)),
            )

        if self.resolver_kind in {
            BindingResolverKind.CONTEXT_VALUE,
            BindingResolverKind.DERIVED,
        }:
            if self.source_key is None:
                raise ValueError(f"{self.resolver_kind.value} requires source_key")
            object.__setattr__(
                self,
                "source_key",
                _required_text(self.source_key, field_name="source_key"),
            )
        elif self.source_key is not None:
            raise ValueError(f"{self.resolver_kind.value} does not accept source_key")

        if self.resolver_kind is BindingResolverKind.CANONICAL_DEFAULT:
            if self.default_value is _UNSET:
                raise ValueError("CANONICAL_DEFAULT requires an explicit default_value")
            object.__setattr__(self, "default_value", deepcopy(self.default_value))
        elif self.default_value is not _UNSET:
            raise ValueError(f"{self.resolver_kind.value} does not accept default_value")


@dataclass(frozen=True, slots=True)
class OperationBindingRecipe:
    canonical_operation: str
    slots: tuple[SlotBindingRecipe, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_operation",
            _required_text(self.canonical_operation, field_name="canonical_operation"),
        )
        slots = tuple(self.slots)
        if any(not isinstance(item, SlotBindingRecipe) for item in slots):
            raise TypeError("slots must contain SlotBindingRecipe values")
        slot_names = [item.slot for item in slots]
        if len(set(slot_names)) != len(slot_names):
            raise ValueError("operation binding recipe requires unique slot names")
        object.__setattr__(self, "slots", slots)


DerivedResolver = Callable[
    [
        CanonicalOperationDefinition,
        OperationProposal,
        ParameterBindingContext,
        Mapping[str, Any],
    ],
    Any,
]


class ParameterBinder:
    """Bind canonical slots from explicit ownership and deterministic recipes."""

    def __init__(
        self,
        definitions: Iterable[CanonicalOperationDefinition],
        recipes: Iterable[OperationBindingRecipe],
        *,
        derived_resolvers: Mapping[str, DerivedResolver] | None = None,
    ) -> None:
        definitions_by_operation: dict[str, CanonicalOperationDefinition] = {}
        for definition in definitions:
            if not isinstance(definition, CanonicalOperationDefinition):
                raise TypeError("definitions must contain CanonicalOperationDefinition values")
            if definition.canonical_operation in definitions_by_operation:
                raise BindingError(
                    f"duplicate canonical operation: {definition.canonical_operation}"
                )
            definitions_by_operation[definition.canonical_operation] = definition

        recipes_by_operation: dict[str, OperationBindingRecipe] = {}
        for recipe in recipes:
            if not isinstance(recipe, OperationBindingRecipe):
                raise TypeError("recipes must contain OperationBindingRecipe values")
            if recipe.canonical_operation in recipes_by_operation:
                raise BindingError(
                    f"duplicate operation binding recipe: {recipe.canonical_operation}"
                )
            if recipe.canonical_operation not in definitions_by_operation:
                raise BindingError(
                    f"recipe references unknown canonical operation: {recipe.canonical_operation}"
                )
            recipes_by_operation[recipe.canonical_operation] = recipe

        resolver_map: dict[str, DerivedResolver] = {}
        for resolver_id, resolver in (derived_resolvers or {}).items():
            normalized_id = _required_text(str(resolver_id), field_name="resolver_id")
            if not callable(resolver):
                raise TypeError(f"DERIVED resolver {normalized_id!r} must be callable")
            resolver_map[normalized_id] = resolver

        recipe_slots_by_operation: dict[str, Mapping[str, SlotBindingRecipe]] = {}
        for operation_id, definition in definitions_by_operation.items():
            recipe = recipes_by_operation.get(operation_id)
            recipe_slots = {} if recipe is None else {item.slot: item for item in recipe.slots}
            properties = definition.input_schema.get("properties", {})

            unknown_recipe_slots = sorted(set(recipe_slots) - set(properties))
            if unknown_recipe_slots:
                raise BindingError(
                    f"recipe references unknown canonical slot(s): {unknown_recipe_slots}"
                )

            for slot, binding_class in definition.slot_binding_policy.items():
                slot_recipe = recipe_slots.get(slot)
                if binding_class in {
                    SlotBindingClass.CONTEXT,
                    SlotBindingClass.CANONICAL_DEFAULT,
                    SlotBindingClass.DERIVED,
                }:
                    if slot_recipe is None:
                        raise BindingError(
                            f"missing deterministic recipe for {operation_id}.{slot}"
                        )
                    self._validate_recipe_match(
                        operation_id,
                        slot,
                        binding_class,
                        slot_recipe,
                    )
                    if (
                        binding_class is SlotBindingClass.DERIVED
                        and slot_recipe.source_key not in resolver_map
                    ):
                        raise BindingError(
                            "unregistered DERIVED resolver for "
                            f"{operation_id}.{slot}: {slot_recipe.source_key}"
                        )
                elif slot_recipe is not None:
                    raise BindingError(
                        f"{operation_id}.{slot} must not have a Step25 deterministic recipe"
                    )

            recipe_slots_by_operation[operation_id] = MappingProxyType(recipe_slots)

        self._definitions = MappingProxyType(definitions_by_operation)
        self._recipe_slots = MappingProxyType(recipe_slots_by_operation)
        self._derived_resolvers = MappingProxyType(resolver_map)

    @staticmethod
    def _validate_recipe_match(
        operation_id: str,
        slot: str,
        binding_class: SlotBindingClass,
        recipe: SlotBindingRecipe,
    ) -> None:
        allowed = {
            SlotBindingClass.CONTEXT: {
                BindingResolverKind.CONTEXT_SELECTION,
                BindingResolverKind.CONTEXT_VALUE,
            },
            SlotBindingClass.CANONICAL_DEFAULT: {
                BindingResolverKind.CANONICAL_DEFAULT,
            },
            SlotBindingClass.DERIVED: {
                BindingResolverKind.DERIVED,
            },
        }[binding_class]
        if recipe.resolver_kind not in allowed:
            raise BindingError(
                f"recipe for {operation_id}.{slot} does not match "
                f"canonical binding class {binding_class.value}"
            )

    def bind(
        self,
        proposal: OperationProposal,
        context: ParameterBindingContext,
    ) -> BoundOperationProposal:
        if not isinstance(proposal, OperationProposal):
            raise TypeError("proposal must be an OperationProposal")
        if not isinstance(context, ParameterBindingContext):
            raise TypeError("context must be a ParameterBindingContext")

        definition = self._definitions.get(proposal.canonical_operation)
        if definition is None:
            raise BindingError(
                f"unknown canonical operation: {proposal.canonical_operation}"
            )

        properties = definition.input_schema.get("properties", {})
        required_slots = set(definition.input_schema.get("required", ()))
        proposal_slots = set(proposal.intent_arguments)
        unknown_slots = sorted(proposal_slots - set(properties))
        if unknown_slots:
            raise BindingError(f"unknown canonical slot(s): {unknown_slots}")

        for slot in proposal_slots:
            binding_class = definition.slot_binding_policy[slot]
            if binding_class is not SlotBindingClass.INTENT:
                raise BindingError(
                    f"proposal may supply INTENT slots only; {slot} is {binding_class.value}"
                )

        for slot in required_slots:
            if (
                definition.slot_binding_policy[slot] is SlotBindingClass.INTENT
                and slot not in proposal.intent_arguments
            ):
                raise BindingError(f"required INTENT slot is missing: {slot}")

        arguments: dict[str, Any] = {
            slot: deepcopy(value) for slot, value in proposal.intent_arguments.items()
        }
        evidence: dict[str, SlotBindingEvidence] = {
            slot: SlotBindingEvidence(
                slot=slot,
                binding_class=SlotBindingClass.INTENT,
                source="OperationProposal.intent_arguments",
            )
            for slot in proposal.intent_arguments
        }

        recipe_slots = self._recipe_slots[definition.canonical_operation]
        for slot, binding_class in definition.slot_binding_policy.items():
            if binding_class not in {
                SlotBindingClass.CONTEXT,
                SlotBindingClass.CANONICAL_DEFAULT,
            }:
                continue
            recipe = recipe_slots[slot]
            value, slot_evidence = self._resolve_non_derived(
                slot,
                binding_class,
                recipe,
                context,
            )
            if value is _UNSET:
                if slot in required_slots:
                    raise BindingError(
                        f"required {binding_class.value} slot is unavailable: {slot}"
                    )
                continue
            arguments[slot] = value
            evidence[slot] = slot_evidence

        non_derived_snapshot = MappingProxyType(deepcopy(arguments))
        for slot, binding_class in definition.slot_binding_policy.items():
            if binding_class is not SlotBindingClass.DERIVED:
                continue
            recipe = recipe_slots[slot]
            resolver_id = recipe.source_key
            if resolver_id is None:
                raise BindingError(f"DERIVED recipe is missing resolver id: {slot}")
            resolver = self._derived_resolvers[resolver_id]
            try:
                value = resolver(
                    definition,
                    proposal,
                    context,
                    non_derived_snapshot,
                )
            except Exception as exc:
                raise BindingError(
                    f"DERIVED resolver failed for {definition.canonical_operation}.{slot}"
                ) from exc
            arguments[slot] = deepcopy(value)
            evidence[slot] = SlotBindingEvidence(
                slot=slot,
                binding_class=SlotBindingClass.DERIVED,
                source=f"DerivedResolver:{resolver_id}",
                source_ref=resolver_id,
            )

        missing_required = sorted(
            slot
            for slot in required_slots
            if definition.slot_binding_policy[slot] is not SlotBindingClass.PROVIDER
            and slot not in arguments
        )
        if missing_required:
            raise BindingError(
                f"required canonical slot(s) remain unbound: {missing_required}"
            )

        validation_schema = deepcopy(definition.input_schema)
        if "required" in validation_schema:
            validation_schema["required"] = [
                slot
                for slot in validation_schema["required"]
                if definition.slot_binding_policy[slot] is not SlotBindingClass.PROVIDER
            ]
        try:
            validate(instance=arguments, schema=validation_schema)
        except (ValidationError, SchemaError) as exc:
            raise BindingError(
                f"bound arguments violate canonical input schema: {exc.message}"
            ) from exc

        return BoundOperationProposal(
            operation=CanonicalOperationRef(
                definition.canonical_operation,
                definition.version,
            ),
            arguments=arguments,
            binding_evidence=evidence,
            context_snapshot_ref=ContextSnapshotRef(
                context.context_snapshot_id,
                context.context_snapshot_hash,
                context.document_ref,
            ),
            planning_requirements=PlanningRequirements(
                operation_freshness_requirements=(
                    definition.operation_freshness_requirements
                ),
                coverage_requirements=definition.coverage_requirements,
                assurance_requirements=definition.assurance_requirements,
            ),
            semantic_environment_ref=context.semantic_environment_ref,
        )

    @staticmethod
    def _resolve_non_derived(
        slot: str,
        binding_class: SlotBindingClass,
        recipe: SlotBindingRecipe,
        context: ParameterBindingContext,
    ) -> tuple[Any, SlotBindingEvidence]:
        if recipe.resolver_kind is BindingResolverKind.CONTEXT_SELECTION:
            value: Any = list(context.selection) if context.selection else _UNSET
            return value, SlotBindingEvidence(
                slot=slot,
                binding_class=binding_class,
                source="ContextSnapshot.selection",
                source_ref=context.context_snapshot_id,
            )

        if recipe.resolver_kind is BindingResolverKind.CONTEXT_VALUE:
            source_key = recipe.source_key
            if source_key is None or source_key not in context.context_values:
                value = _UNSET
            else:
                value = deepcopy(context.context_values[source_key])
            return value, SlotBindingEvidence(
                slot=slot,
                binding_class=binding_class,
                source="ContextSnapshot.context_values",
                source_ref=source_key,
            )

        if recipe.resolver_kind is BindingResolverKind.CANONICAL_DEFAULT:
            return deepcopy(recipe.default_value), SlotBindingEvidence(
                slot=slot,
                binding_class=binding_class,
                source="CanonicalDefault",
            )

        raise BindingError(f"invalid non-derived resolver kind for slot: {slot}")


MOVE_V1_BINDING_RECIPE = OperationBindingRecipe(
    canonical_operation=MOVE_V1.canonical_operation,
    slots=(
        SlotBindingRecipe(
            slot="targets",
            resolver_kind=BindingResolverKind.CONTEXT_SELECTION,
        ),
    ),
)

SET_WALL_THICKNESS_V1_BINDING_RECIPE = OperationBindingRecipe(
    canonical_operation=SET_WALL_THICKNESS_V1.canonical_operation,
    slots=(
        SlotBindingRecipe(
            slot="targets",
            resolver_kind=BindingResolverKind.CONTEXT_SELECTION,
        ),
    ),
)

MVP_BINDING_RECIPES: tuple[OperationBindingRecipe, ...] = (
    MOVE_V1_BINDING_RECIPE,
    SET_WALL_THICKNESS_V1_BINDING_RECIPE,
)
