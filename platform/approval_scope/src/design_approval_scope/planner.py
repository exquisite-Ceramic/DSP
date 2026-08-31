"""Closed-world deterministic Step28 approval scope planner."""
from __future__ import annotations

from hashlib import sha256

from design_impact import ImpactAnalysis, IntentBoundary

from .contracts import (
    ApprovalScopeDefinition,
    ApprovalScopeError,
    ApprovalScopePlanRequest,
    CanonicalAspect,
    CreationRule,
    DirectEntityEffect,
    EntitySelector,
    ExistingEntityRule,
    ScopeEffectRecipe,
)
from .hashing import compute_scope_body_hash, creation_rule_id


def _stable_id(prefix: str, material: str) -> str:
    return f"{prefix}-{sha256(material.encode('utf-8')).hexdigest()[:12]}"


def direct_existing_rule_id(semantic_id: str) -> str:
    """Return the deterministic construction id for one direct existing-entity rule."""
    semantic_id = semantic_id.strip()
    if not semantic_id:
        raise ValueError("semantic_id is required")
    return _stable_id("ER", f"direct:{semantic_id}")


def recipe_existing_rule_id(recipe: ScopeEffectRecipe, affected_semantic_id: str) -> str:
    """Return the deterministic construction id for one recipe-backed rule."""
    if not isinstance(recipe, ScopeEffectRecipe):
        raise TypeError("recipe must be ScopeEffectRecipe")
    affected_semantic_id = affected_semantic_id.strip()
    if not affected_semantic_id:
        raise ValueError("affected_semantic_id is required")
    material = f"recipe:{recipe.recipe_id}:{recipe.dependency_ref}:{affected_semantic_id}"
    return _stable_id("ER", material)


def _error(code: str, message: str) -> None:
    raise ApprovalScopeError(code, message)


def _aspect_values(values) -> set[str]:
    result: set[str] = set()
    for value in values:
        raw = getattr(value, "value", value)
        try:
            result.add(CanonicalAspect(str(raw)).value)
        except ValueError:
            _error("SCOPE_EFFECT_CONTRACT_MISMATCH", f"unknown canonical effect {raw!r}")
    return result


def _existence_values(values) -> set[str]:
    return {str(getattr(value, "value", value)) for value in values}


def _direct_effects(effects: tuple[DirectEntityEffect, ...]) -> dict[str, DirectEntityEffect]:
    result: dict[str, DirectEntityEffect] = {}
    for effect in effects:
        previous = result.get(effect.semantic_id)
        if previous is not None and previous.allowed_aspects != effect.allowed_aspects:
            _error("SCOPE_RULE_INVALID", f"conflicting direct effects for {effect.semantic_id}")
        result[effect.semantic_id] = effect
    return result


def _recipes(recipes: tuple[ScopeEffectRecipe, ...]) -> dict[str, ScopeEffectRecipe]:
    result: dict[str, ScopeEffectRecipe] = {}
    for recipe in recipes:
        previous = result.get(recipe.dependency_ref)
        if previous is not None and previous != recipe:
            _error(
                "SCOPE_RULE_INVALID",
                f"conflicting scope effect recipes for {recipe.dependency_ref}",
            )
        result[recipe.dependency_ref] = recipe
    return result


def _admit_creation_rules(
    request: ApprovalScopePlanRequest,
    *,
    impact: ImpactAnalysis,
    canonical_existence: set[str],
    intent_existence: set[str],
) -> tuple[CreationRule, ...]:
    if not request.requested_creation_rules:
        return ()
    if "CREATE" not in canonical_existence or "CREATE" not in intent_existence:
        _error(
            "SCOPE_RULE_INVALID",
            "creation rules require CREATE authority in both canonical evidence and intent",
        )

    contract = request.canonical_effect_evidence.creation_contract
    if contract is None:
        _error("SCOPE_RULE_INVALID", "CREATE authority requires a canonical creation contract")

    direct_targets = tuple(sorted(impact.direct_targets))
    canonical_kinds = set(contract.entity_kinds)
    admitted: dict[str, CreationRule] = {}
    for rule in request.requested_creation_rules:
        if rule.canonical_operation != request.canonical_effect_evidence.canonical_operation:
            _error("SCOPE_RULE_INVALID", "creation rule operation exceeds canonical authority")
        if rule.source_selector.predicate is not None or rule.source_selector.entities != direct_targets:
            _error("SCOPE_RULE_INVALID", "creation rule source selector must equal direct targets")
        if not set(rule.entity_kinds).issubset(canonical_kinds):
            _error("SCOPE_RULE_INVALID", "creation rule entity kinds exceed canonical authority")
        if rule.max_count is None or rule.max_count > contract.max_count:
            _error("SCOPE_RULE_INVALID", "creation rule count exceeds canonical authority")
        if rule.required_derivation != contract.required_derivation:
            _error("SCOPE_RULE_INVALID", "creation rule derivation does not match canonical authority")

        stable_id = creation_rule_id(rule)
        rebuilt = CreationRule(
            rule_id=stable_id,
            canonical_operation=rule.canonical_operation,
            source_selector=rule.source_selector,
            entity_kinds=rule.entity_kinds,
            max_count=rule.max_count,
            required_derivation=rule.required_derivation,
        )
        if stable_id in admitted:
            _error("SCOPE_RULE_INVALID", "creation rules must have unique semantic authority")
        admitted[stable_id] = rebuilt

    return tuple(admitted[rule_id] for rule_id in sorted(admitted))


class ApprovalScopePlanner:
    """Plan the maximum canonical effect scope for one exact impact result."""

    def plan(self, request: ApprovalScopePlanRequest) -> ApprovalScopeDefinition:
        if not isinstance(request, ApprovalScopePlanRequest):
            _error("SCOPE_INPUT_INVALID", "request must be ApprovalScopePlanRequest")
        impact = request.impact_analysis
        intent = request.intent_boundary
        if not isinstance(impact, ImpactAnalysis):
            _error("SCOPE_INPUT_INVALID", "impact_analysis must be ImpactAnalysis")
        if not isinstance(intent, IntentBoundary):
            _error("SCOPE_INPUT_INVALID", "intent_boundary must be IntentBoundary")

        if any(exception.blocking for exception in impact.exceptions):
            _error("SCOPE_NOT_APPROVABLE", "blocking impact exception prevents scope planning")
        if impact.planning_snapshot_ref.semantic_environment != impact.semantic_environment_ref:
            _error("SCOPE_INPUT_INVALID", "PlanningSnapshot semantic environment mismatch")
        if impact.snapshot_set_ref.semantic_environment != impact.semantic_environment_ref:
            _error("SCOPE_INPUT_INVALID", "SnapshotSet semantic environment mismatch")
        if impact.planning_snapshot_ref.snapshot_id not in impact.snapshot_set_ref.member_snapshot_ids:
            _error("SCOPE_INPUT_INVALID", "PlanningSnapshot is not a member of SnapshotSet")

        evidence = request.canonical_effect_evidence
        if evidence.canonical_operation != impact.canonical_operation:
            _error(
                "SCOPE_EFFECT_CONTRACT_MISMATCH",
                "canonical effect evidence operation does not match impact analysis",
            )
        if tuple(sorted(intent.direct_targets)) != tuple(sorted(impact.direct_targets)):
            _error(
                "SCOPE_INPUT_INVALID",
                "carried-forward intent direct targets do not match impact analysis",
            )

        canonical_aspects = {aspect.value for aspect in evidence.allowed_aspects}
        intent_aspects = _aspect_values(intent.allowed_canonical_effects)
        if not intent_aspects.issubset(canonical_aspects):
            _error(
                "SCOPE_EFFECT_CONTRACT_MISMATCH",
                "intent effects exceed canonical action effect authority",
            )

        canonical_existence = _existence_values(evidence.allowed_existence_effects)
        intent_existence = _existence_values(
            getattr(intent, "allowed_existence_effects", ())
        )
        if (
            "DELETE" in canonical_existence
            or "DELETE" in intent_existence
            or request.requested_deletion_rules
        ):
            _error(
                "SCOPE_EXISTENCE_EFFECT_UNSUPPORTED",
                "DELETE existence effect is not supported by Step28",
            )
        if not request.requested_creation_rules and not intent_existence.issubset(
            canonical_existence
        ):
            _error(
                "SCOPE_EFFECT_CONTRACT_MISMATCH",
                "intent existence effects exceed canonical action authority",
            )

        creation_rules = _admit_creation_rules(
            request,
            impact=impact,
            canonical_existence=canonical_existence,
            intent_existence=intent_existence,
        )

        existing_rules: list[ExistingEntityRule] = []
        direct_by_id = _direct_effects(request.direct_entity_effects)
        direct_targets = set(impact.direct_targets)
        unknown_direct = set(direct_by_id) - direct_targets
        if unknown_direct:
            _error(
                "SCOPE_RULE_INVALID",
                f"direct effect targets non-direct entities: {sorted(unknown_direct)}",
            )

        allowed_upper = canonical_aspects & intent_aspects
        if intent_aspects or not intent_existence:
            missing_direct = direct_targets - set(direct_by_id)
            if missing_direct:
                _error(
                    "SCOPE_EFFECT_UNDEFINED",
                    f"direct effect scope undefined for: {sorted(missing_direct)}",
                )
        elif direct_by_id:
            _error(
                "SCOPE_RULE_INVALID",
                "direct aspect effects cannot be admitted without intent aspect authority",
            )

        for semantic_id in sorted(direct_by_id):
            effect = direct_by_id[semantic_id]
            aspects = {aspect.value for aspect in effect.allowed_aspects}
            if not aspects.issubset(allowed_upper):
                _error(
                    "SCOPE_RULE_INVALID",
                    f"direct effect exceeds authority for {semantic_id}",
                )
            existing_rules.append(
                ExistingEntityRule(
                    rule_id=direct_existing_rule_id(semantic_id),
                    selector=EntitySelector(entities=(semantic_id,)),
                    allowed_aspects=effect.allowed_aspects,
                )
            )

        predicted_by_dep = {}
        for predicted in impact.predicted_impacts:
            if predicted.dependency_ref in predicted_by_dep:
                _error(
                    "SCOPE_INPUT_INVALID",
                    f"duplicate predicted dependency_ref: {predicted.dependency_ref}",
                )
            predicted_by_dep[predicted.dependency_ref] = predicted

        deterministic_bundles = {
            bundle.bundle_id: bundle
            for bundle in impact.propagation_bundles
            if bundle.deterministic
        }
        bundles_for_entity: dict[str, set[str]] = {}
        for bundle in deterministic_bundles.values():
            for entity in bundle.affected_entities:
                bundles_for_entity.setdefault(entity, set()).add(bundle.bundle_id)

        recipes = _recipes(request.scope_effect_recipes)
        unknown_recipes = set(recipes) - set(predicted_by_dep)
        if unknown_recipes:
            _error(
                "SCOPE_RULE_INVALID",
                f"recipe references unknown dependencies: {sorted(unknown_recipes)}",
            )

        effect_bearing = {
            dep_ref: predicted
            for dep_ref, predicted in predicted_by_dep.items()
            if predicted.requires_verification
            or predicted.affected_semantic_id in bundles_for_entity
        }
        extra_recipes = set(recipes) - set(effect_bearing)
        if extra_recipes:
            _error(
                "SCOPE_RULE_INVALID",
                f"recipes cannot authorize advisory-only impacts: {sorted(extra_recipes)}",
            )
        missing_recipes = set(effect_bearing) - set(recipes)
        if missing_recipes:
            _error(
                "SCOPE_EFFECT_UNDEFINED",
                f"effect-bearing impacts require recipes: {sorted(missing_recipes)}",
            )

        admitted_bundle_ids: set[str] = set()
        intent_rule_refs = set(intent.allowed_derived_rule_refs)
        for dep_ref in sorted(effect_bearing):
            predicted = effect_bearing[dep_ref]
            recipe = recipes[dep_ref]
            aspects = {aspect.value for aspect in recipe.allowed_aspects}
            if not aspects.issubset(allowed_upper):
                _error(
                    "SCOPE_RULE_INVALID",
                    f"recipe effects exceed authority for {dep_ref}",
                )

            entity_bundle_ids = bundles_for_entity.get(predicted.affected_semantic_id, set())
            if entity_bundle_ids:
                if recipe.propagation_bundle_id is None:
                    _error(
                        "SCOPE_RULE_INVALID",
                        f"deterministic bundle impact requires bundle binding for {dep_ref}",
                    )
                if recipe.propagation_bundle_id not in entity_bundle_ids:
                    _error(
                        "SCOPE_RULE_INVALID",
                        f"recipe bundle does not contain affected entity for {dep_ref}",
                    )
                bundle = deterministic_bundles[recipe.propagation_bundle_id]
                if recipe.rule_ref != bundle.rule_ref:
                    _error(
                        "SCOPE_RULE_INVALID",
                        f"recipe rule_ref does not match propagation bundle for {dep_ref}",
                    )
                if bundle.rule_ref not in intent_rule_refs:
                    _error(
                        "SCOPE_RULE_INVALID",
                        f"bundle rule not admitted by intent boundary for {dep_ref}",
                    )
                admitted_bundle_ids.add(bundle.bundle_id)
            elif recipe.propagation_bundle_id is not None:
                _error(
                    "SCOPE_RULE_INVALID",
                    f"non-bundle impact cannot claim a propagation bundle for {dep_ref}",
                )

            existing_rules.append(
                ExistingEntityRule(
                    rule_id=recipe_existing_rule_id(recipe, predicted.affected_semantic_id),
                    selector=EntitySelector(entities=(predicted.affected_semantic_id,)),
                    allowed_aspects=recipe.allowed_aspects,
                )
            )

        rule_ids = [rule.rule_id for rule in existing_rules]
        if len(set(rule_ids)) != len(rule_ids):
            _error("SCOPE_RULE_INVALID", "derived existing rule ids must be unique")
        known_existing = set(rule_ids)
        known_creation = {rule.rule_id for rule in creation_rules}
        slice_rules = tuple(request.execution_slice_scope_rules)
        covered_existing: set[str] = set()
        covered_creation: set[str] = set()
        for slice_rule in slice_rules:
            unknown_existing = set(slice_rule.existing_rule_ids) - known_existing
            unknown_creation = set(slice_rule.creation_rule_ids) - known_creation
            if unknown_existing or unknown_creation or slice_rule.deletion_rule_ids:
                _error(
                    "SCOPE_SLICE_RULE_INVALID",
                    "slice scope references unknown or unsupported rules",
                )
            covered_existing.update(slice_rule.existing_rule_ids)
            covered_creation.update(slice_rule.creation_rule_ids)
        if covered_existing != known_existing:
            _error(
                "SCOPE_SLICE_RULE_INVALID",
                "every admitted existing rule must be covered by a slice scope rule",
            )
        if covered_creation != known_creation:
            _error(
                "SCOPE_SLICE_RULE_INVALID",
                "every admitted creation rule must be covered by a slice scope rule",
            )

        existing_tuple = tuple(sorted(existing_rules, key=lambda rule: rule.rule_id))
        admitted_bundles = tuple(sorted(admitted_bundle_ids))
        scope_body_hash = compute_scope_body_hash(
            impact_analysis_fingerprint=impact.analysis_fingerprint,
            canonical_effect_evidence=evidence,
            intent_boundary=intent,
            planning_snapshot_ref=impact.planning_snapshot_ref,
            snapshot_set_ref=impact.snapshot_set_ref,
            semantic_environment_ref=impact.semantic_environment_ref,
            existing_entity_rules=existing_tuple,
            creation_rules=creation_rules,
            deletion_rules=(),
            propagation_bundle_ids=admitted_bundles,
            execution_slice_scope_rules=slice_rules,
        )
        return ApprovalScopeDefinition(
            scope_definition_id=f"ASD-{scope_body_hash[:12]}",
            impact_analysis_fingerprint=impact.analysis_fingerprint,
            canonical_effect_evidence=evidence,
            intent_boundary=intent,
            planning_snapshot_ref=impact.planning_snapshot_ref,
            snapshot_set_ref=impact.snapshot_set_ref,
            semantic_environment_ref=impact.semantic_environment_ref,
            existing_entity_rules=existing_tuple,
            creation_rules=creation_rules,
            deletion_rules=(),
            propagation_bundle_ids=admitted_bundles,
            execution_slice_scope_rules=slice_rules,
            scope_body_hash=scope_body_hash,
        )
