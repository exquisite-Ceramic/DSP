"""Step26 interaction-aware wrapper around the strict Step25 ParameterBinder."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from jsonschema import ValidationError, validate

from design_interaction import (
    InteractionError,
    InteractionSession,
    InteractionState,
    InteractionType,
)
from design_orchestrator.canonical_operations import (
    CanonicalOperationDefinition,
    SlotBindingClass,
)
from design_orchestrator.parameter_binder import (
    BoundOperationProposal,
    ContextSnapshotRef,
    DerivedResolver,
    OperationBindingRecipe,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
    SlotBindingEvidence,
)


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _readonly_copy(value: Mapping[str, Any], *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return MappingProxyType(deepcopy(dict(value)))


@dataclass(frozen=True, slots=True)
class InteractionBindingContext:
    """Task/Host identity needed to validate an interaction result before D6 resume."""

    task_id: str
    host_instance_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _required_text(self.task_id, field_name="task_id"))
        object.__setattr__(
            self,
            "host_instance_id",
            _required_text(self.host_instance_id, field_name="host_instance_id"),
        )


@dataclass(frozen=True, slots=True)
class SlotInteractionRecipe:
    slot: str
    interaction_type: InteractionType
    input_constraints: Mapping[str, Any] = field(default_factory=dict)
    result_schema: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", _required_text(self.slot, field_name="slot"))
        if not isinstance(self.interaction_type, InteractionType):
            object.__setattr__(
                self,
                "interaction_type",
                InteractionType(str(self.interaction_type)),
            )
        object.__setattr__(
            self,
            "input_constraints",
            _readonly_copy(self.input_constraints, field_name="input_constraints"),
        )
        object.__setattr__(
            self,
            "result_schema",
            _readonly_copy(self.result_schema, field_name="result_schema"),
        )


@dataclass(frozen=True, slots=True)
class OperationInteractionRecipe:
    canonical_operation: str
    slots: tuple[SlotInteractionRecipe, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_operation",
            _required_text(self.canonical_operation, field_name="canonical_operation"),
        )
        slots = tuple(self.slots)
        if any(not isinstance(item, SlotInteractionRecipe) for item in slots):
            raise TypeError("slots must contain SlotInteractionRecipe values")
        names = [item.slot for item in slots]
        if len(set(names)) != len(names):
            raise ValueError("operation interaction recipe requires unique slot names")
        object.__setattr__(self, "slots", slots)


@dataclass(frozen=True, slots=True)
class InteractionRequired:
    canonical_operation: str
    slot: str
    interaction_type: InteractionType
    input_constraints: Mapping[str, Any]
    result_schema: Mapping[str, Any]
    context_snapshot_ref: ContextSnapshotRef

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_operation",
            _required_text(self.canonical_operation, field_name="canonical_operation"),
        )
        object.__setattr__(self, "slot", _required_text(self.slot, field_name="slot"))
        if not isinstance(self.interaction_type, InteractionType):
            object.__setattr__(
                self,
                "interaction_type",
                InteractionType(str(self.interaction_type)),
            )
        object.__setattr__(
            self,
            "input_constraints",
            _readonly_copy(self.input_constraints, field_name="input_constraints"),
        )
        object.__setattr__(
            self,
            "result_schema",
            _readonly_copy(self.result_schema, field_name="result_schema"),
        )
        if not isinstance(self.context_snapshot_ref, ContextSnapshotRef):
            raise TypeError("context_snapshot_ref must be a ContextSnapshotRef")


class InteractiveParameterResolver:
    """Return either a bound proposal or one explicit Host interaction requirement."""

    def __init__(
        self,
        *,
        definitions: Iterable[CanonicalOperationDefinition],
        binding_recipes: Iterable[OperationBindingRecipe],
        interaction_recipes: Iterable[OperationInteractionRecipe],
        derived_resolvers: Mapping[str, DerivedResolver] | None = None,
    ) -> None:
        definitions_by_operation: dict[str, CanonicalOperationDefinition] = {}
        ordered_definitions: list[CanonicalOperationDefinition] = []
        for definition in definitions:
            if not isinstance(definition, CanonicalOperationDefinition):
                raise TypeError("definitions must contain CanonicalOperationDefinition values")
            if definition.canonical_operation in definitions_by_operation:
                raise ValueError(f"duplicate canonical operation: {definition.canonical_operation}")
            definitions_by_operation[definition.canonical_operation] = definition
            ordered_definitions.append(definition)

        interaction_by_operation: dict[str, Mapping[str, SlotInteractionRecipe]] = {}
        for operation_recipe in interaction_recipes:
            if not isinstance(operation_recipe, OperationInteractionRecipe):
                raise TypeError("interaction_recipes must contain OperationInteractionRecipe values")
            operation_id = operation_recipe.canonical_operation
            if operation_id in interaction_by_operation:
                raise ValueError(f"duplicate interaction recipe: {operation_id}")
            definition = definitions_by_operation.get(operation_id)
            if definition is None:
                raise ValueError(f"interaction recipe references unknown operation: {operation_id}")

            properties = definition.input_schema.get("properties", {})
            required = tuple(definition.input_schema.get("required", ()))
            recipe_map: dict[str, SlotInteractionRecipe] = {}
            for slot_recipe in operation_recipe.slots:
                slot = slot_recipe.slot
                if slot not in properties:
                    raise ValueError(
                        f"interaction recipe references unknown canonical slot: {operation_id}.{slot}"
                    )
                if (
                    slot not in required
                    or definition.slot_binding_policy[slot] is not SlotBindingClass.INTENT
                ):
                    raise ValueError(
                        f"interaction recipe must target a required INTENT slot: {operation_id}.{slot}"
                    )
                if dict(slot_recipe.result_schema) != deepcopy(properties[slot]):
                    raise ValueError(
                        f"interaction result_schema must match canonical slot schema: {operation_id}.{slot}"
                    )
                recipe_map[slot] = slot_recipe
            interaction_by_operation[operation_id] = MappingProxyType(recipe_map)

        self._definitions = MappingProxyType(definitions_by_operation)
        self._interaction_recipes = MappingProxyType(interaction_by_operation)
        self._binder = ParameterBinder(
            ordered_definitions,
            binding_recipes,
            derived_resolvers=derived_resolvers,
        )

    @staticmethod
    def _snapshot_ref(context: ParameterBindingContext) -> ContextSnapshotRef:
        return ContextSnapshotRef(
            context_snapshot_id=context.context_snapshot_id,
            context_snapshot_hash=context.context_snapshot_hash,
            document_ref=context.document_ref,
        )

    @staticmethod
    def _validate_session(
        session: InteractionSession,
        *,
        recipe: SlotInteractionRecipe,
        parameter_context: ParameterBindingContext,
        interaction_context: InteractionBindingContext,
    ) -> None:
        if not isinstance(session, InteractionSession):
            raise TypeError("interaction session value must be InteractionSession")
        if (
            session.state is not InteractionState.COMPLETED
            or session.task_id != interaction_context.task_id
            or session.host_instance_id != interaction_context.host_instance_id
            or session.document_id != parameter_context.document_ref
            or session.interaction_type is not recipe.interaction_type
        ):
            raise InteractionError(
                "INTERACTION_CONTEXT_MISMATCH",
                "completed interaction does not match current task/Host/document/type",
            )
        try:
            validate(instance=session.result, schema=dict(recipe.result_schema))
        except ValidationError as exc:
            raise InteractionError(
                "INTERACTION_RESULT_INVALID",
                f"interaction result does not match recipe schema: {exc.message}",
            ) from exc

    def resolve(
        self,
        proposal: OperationProposal,
        parameter_context: ParameterBindingContext,
        interaction_context: InteractionBindingContext,
        *,
        interaction_sessions: Mapping[str, InteractionSession] | None = None,
    ) -> BoundOperationProposal | InteractionRequired:
        if not isinstance(proposal, OperationProposal):
            raise TypeError("proposal must be an OperationProposal")
        if not isinstance(parameter_context, ParameterBindingContext):
            raise TypeError("parameter_context must be a ParameterBindingContext")
        if not isinstance(interaction_context, InteractionBindingContext):
            raise TypeError("interaction_context must be an InteractionBindingContext")

        definition = self._definitions.get(proposal.canonical_operation)
        if definition is None:
            # Preserve Step25 fail-closed semantics and error type for unknown operations.
            return self._binder.bind(proposal, parameter_context)

        session_map = dict(interaction_sessions or {})
        recipes = self._interaction_recipes.get(proposal.canonical_operation, {})
        unknown_sessions = sorted(set(session_map) - set(recipes))
        if unknown_sessions:
            raise InteractionError(
                "INTERACTION_CONTEXT_MISMATCH",
                f"interaction result supplied for non-interactive slot(s): {unknown_sessions}",
            )

        intent_arguments = deepcopy(dict(proposal.intent_arguments))
        interaction_sources: dict[str, str] = {}
        required_slots = tuple(definition.input_schema.get("required", ()))

        for slot in required_slots:
            if definition.slot_binding_policy.get(slot) is not SlotBindingClass.INTENT:
                continue
            if slot in intent_arguments:
                continue

            recipe = recipes.get(slot)
            if recipe is None:
                continue
            session = session_map.get(slot)
            if session is None:
                return InteractionRequired(
                    canonical_operation=proposal.canonical_operation,
                    slot=slot,
                    interaction_type=recipe.interaction_type,
                    input_constraints=recipe.input_constraints,
                    result_schema=recipe.result_schema,
                    context_snapshot_ref=self._snapshot_ref(parameter_context),
                )

            self._validate_session(
                session,
                recipe=recipe,
                parameter_context=parameter_context,
                interaction_context=interaction_context,
            )
            intent_arguments[slot] = deepcopy(session.result)
            interaction_sources[slot] = session.interaction_id

        bound = self._binder.bind(
            OperationProposal(proposal.canonical_operation, intent_arguments),
            parameter_context,
        )
        if not interaction_sources:
            return bound

        evidence = dict(bound.binding_evidence)
        for slot, interaction_id in interaction_sources.items():
            evidence[slot] = SlotBindingEvidence(
                slot=slot,
                binding_class=SlotBindingClass.INTENT,
                source="InteractionSession",
                source_ref=interaction_id,
            )

        return BoundOperationProposal(
            operation=bound.operation,
            arguments=bound.arguments,
            binding_evidence=evidence,
            context_snapshot_ref=bound.context_snapshot_ref,
            planning_requirements=bound.planning_requirements,
            semantic_environment_ref=bound.semantic_environment_ref,
        )


__all__ = [
    "InteractionBindingContext",
    "InteractionRequired",
    "InteractiveParameterResolver",
    "OperationInteractionRecipe",
    "SlotInteractionRecipe",
]
