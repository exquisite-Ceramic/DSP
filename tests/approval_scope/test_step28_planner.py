import pytest

from design_approval_scope import (
    ApprovalScopeError,
    ApprovalScopePlanRequest,
    ApprovalScopePlanner,
    CanonicalAspect,
    CanonicalEffectEvidence,
    CreationRule,
    DeletionRule,
    DirectEntityEffect,
    EntitySelector,
    ExecutionSliceScopeRule,
    ScopeEffectRecipe,
    direct_existing_rule_id,
    recipe_existing_rule_id,
)
from design_impact import (
    DependencyStrength,
    ImpactAnalysis,
    ImpactException,
    IntentBoundary,
    PlanningSnapshotBinding,
    PredictedImpact,
    PropagationAction,
    PropagationBundle,
    PropagationOwner,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)


def base_parts(*, blocking=False):
    env = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding("PS-1", "planning-hash", "DOC-1", env)
    snapshot_set = SnapshotSetBinding("SS-1", "set-hash", ("PS-1",), env)
    predicted = (
        PredictedImpact(
            "WALL-001", "OPENING-001", DependencyStrength.HARD,
            PropagationOwner.HOST_NATIVE, PropagationAction.REVALIDATE,
            "DEP-OPENING", (), True,
        ),
        PredictedImpact(
            "WALL-001", "ANNOTATION-002", DependencyStrength.SOFT,
            PropagationOwner.SEMANTIC_RUNTIME, PropagationAction.RECOMPUTE,
            "DEP-ANNOTATION", (), False,
        ),
    )
    bundles = (
        PropagationBundle(
            "PB-ANNOTATION", "RULE-ANNOTATION", DependencyStrength.SOFT,
            PropagationOwner.SEMANTIC_RUNTIME, PropagationAction.RECOMPUTE,
            ("WALL-001",), ("ANNOTATION-002",), True,
            ({"aspect": "PLACEMENT"},),
        ),
    )
    exceptions = ()
    if blocking:
        exceptions = (
            ImpactException(
                "IX-1", "REPLAN_REQUIRED", ("WALL-001",), ("MEP-008",),
                "SOFT", "AGENT", "REPLAN", True, (),
            ),
        )
    impact = ImpactAnalysis(
        "IA-1", "move.v1", ("WALL-001",), planning, snapshot_set, env,
        predicted, bundles, exceptions, "impact-fp",
    )
    evidence = CanonicalEffectEvidence(
        "move.v1", "1.0.0",
        (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
    )
    intent = IntentBoundary(
        ("WALL-001",),
        ("PLACEMENT", "GEOMETRY"),
        ("RULE-ANNOTATION",),
    )
    direct = DirectEntityEffect(
        "WALL-001",
        (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
    )
    opening = ScopeEffectRecipe(
        "REC-OPEN", "DEP-OPENING",
        (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
    )
    annotation = ScopeEffectRecipe(
        "REC-ANN", "DEP-ANNOTATION", (CanonicalAspect.PLACEMENT,),
        rule_ref="RULE-ANNOTATION", propagation_bundle_id="PB-ANNOTATION",
    )
    return impact, evidence, intent, direct, opening, annotation


def request(*, impact=None, evidence=None, intent=None, directs=None, recipes=None,
            create=(), delete=(), slices=None):
    base = base_parts()
    impact = impact or base[0]
    evidence = evidence or base[1]
    intent = intent or base[2]
    directs = (base[3],) if directs is None else directs
    recipes = (base[4], base[5]) if recipes is None else recipes
    if slices is None:
        rule_ids = (
            direct_existing_rule_id("WALL-001"),
            recipe_existing_rule_id(base[4], "OPENING-001"),
            recipe_existing_rule_id(base[5], "ANNOTATION-002"),
        )
        slices = (ExecutionSliceScopeRule("SLICE-SCOPE-1", "DOC-1", rule_ids),)
    return ApprovalScopePlanRequest(
        evidence, impact, intent, directs, recipes, create, delete, slices,
    )


def assert_code(code, operation):
    with pytest.raises(ApprovalScopeError) as exc:
        operation()
    assert exc.value.code == code


def test_safe_move_plans_exact_existing_entity_scope():
    result = ApprovalScopePlanner().plan(request())
    by_entity = {
        rule.selector.entities[0]: tuple(aspect.value for aspect in rule.allowed_aspects)
        for rule in result.existing_entity_rules
    }
    assert by_entity == {
        "WALL-001": ("GEOMETRY", "PLACEMENT"),
        "OPENING-001": ("GEOMETRY", "PLACEMENT"),
        "ANNOTATION-002": ("PLACEMENT",),
    }
    assert result.propagation_bundle_ids == ("PB-ANNOTATION",)
    assert result.creation_rules == result.deletion_rules == ()


def test_canonical_operation_mismatch_fails_contract():
    bad = CanonicalEffectEvidence("copy.v1", "1.0.0", (CanonicalAspect.PLACEMENT,))
    assert_code(
        "SCOPE_EFFECT_CONTRACT_MISMATCH",
        lambda: ApprovalScopePlanner().plan(request(evidence=bad)),
    )


def test_intent_effect_cannot_exceed_canonical_effect_authority():
    bad = IntentBoundary(
        ("WALL-001",), ("PLACEMENT", "PROPERTIES"), ("RULE-ANNOTATION",),
    )
    assert_code(
        "SCOPE_EFFECT_CONTRACT_MISMATCH",
        lambda: ApprovalScopePlanner().plan(request(intent=bad)),
    )


def test_direct_effect_is_explicit_and_cannot_expand_target_scope():
    bad = DirectEntityEffect("OTHER-001", (CanonicalAspect.PLACEMENT,))
    assert_code(
        "SCOPE_RULE_INVALID",
        lambda: ApprovalScopePlanner().plan(request(directs=(bad,))),
    )
    assert_code(
        "SCOPE_EFFECT_UNDEFINED",
        lambda: ApprovalScopePlanner().plan(request(directs=())),
    )


def test_effect_bearing_predicted_impacts_require_recipes():
    base = base_parts()
    assert_code(
        "SCOPE_EFFECT_UNDEFINED",
        lambda: ApprovalScopePlanner().plan(request(recipes=(base[5],))),
    )
    assert_code(
        "SCOPE_EFFECT_UNDEFINED",
        lambda: ApprovalScopePlanner().plan(request(recipes=(base[4],))),
    )


def test_recipe_must_bind_known_dependency_and_stay_within_authority():
    base = base_parts()
    unknown = ScopeEffectRecipe(
        "REC-X", "DEP-UNKNOWN", (CanonicalAspect.PLACEMENT,),
    )
    assert_code(
        "SCOPE_RULE_INVALID",
        lambda: ApprovalScopePlanner().plan(request(recipes=(base[4], base[5], unknown))),
    )
    widened = ScopeEffectRecipe(
        "REC-OPEN", "DEP-OPENING", (CanonicalAspect.PROPERTIES,),
    )
    assert_code(
        "SCOPE_RULE_INVALID",
        lambda: ApprovalScopePlanner().plan(request(recipes=(widened, base[5]))),
    )


def test_bundle_recipe_must_match_rule_ref():
    base = base_parts()
    bad = ScopeEffectRecipe(
        "REC-ANN", "DEP-ANNOTATION", (CanonicalAspect.PLACEMENT,),
        rule_ref="OTHER-RULE", propagation_bundle_id="PB-ANNOTATION",
    )
    assert_code(
        "SCOPE_RULE_INVALID",
        lambda: ApprovalScopePlanner().plan(request(recipes=(base[4], bad))),
    )


def test_advisory_only_impact_needs_no_recipe_and_adds_no_permission():
    base = base_parts()
    impact = base[0]
    advisory = PredictedImpact(
        "WALL-001", "NOTE-003", DependencyStrength.ADVISORY,
        PropagationOwner.HOST_NATIVE, PropagationAction.MARK_DIRTY,
        "DEP-NOTE", (), False,
    )
    changed = ImpactAnalysis(
        impact.analysis_id, impact.canonical_operation, impact.direct_targets,
        impact.planning_snapshot_ref, impact.snapshot_set_ref,
        impact.semantic_environment_ref, impact.predicted_impacts + (advisory,),
        impact.propagation_bundles, impact.exceptions, impact.analysis_fingerprint,
    )
    result = ApprovalScopePlanner().plan(request(impact=changed))
    assert "NOTE-003" not in {
        rule.selector.entities[0] for rule in result.existing_entity_rules
    }


def test_blocking_exception_stops_scope_planning():
    blocking = base_parts(blocking=True)[0]
    assert_code(
        "SCOPE_NOT_APPROVABLE",
        lambda: ApprovalScopePlanner().plan(request(impact=blocking)),
    )


def test_non_empty_creation_or_deletion_is_unsupported_in_v1():
    creation = CreationRule(
        "CR-1", "copy.v1", EntitySelector(entities=("WALL-001",)),
        ("ifc:IfcWall",), 1, "RULE-COPY",
    )
    deletion = DeletionRule("DR-1", EntitySelector(entities=("WALL-001",)))
    assert_code(
        "SCOPE_EXISTENCE_EFFECT_UNSUPPORTED",
        lambda: ApprovalScopePlanner().plan(request(create=(creation,))),
    )
    assert_code(
        "SCOPE_EXISTENCE_EFFECT_UNSUPPORTED",
        lambda: ApprovalScopePlanner().plan(request(delete=(deletion,))),
    )


def test_slice_scope_must_reference_known_rules_and_cover_all_rules():
    unknown = (ExecutionSliceScopeRule("S-1", "DOC-1", ("NOPE",)),)
    assert_code(
        "SCOPE_SLICE_RULE_INVALID",
        lambda: ApprovalScopePlanner().plan(request(slices=unknown)),
    )
    partial = (
        ExecutionSliceScopeRule(
            "S-1", "DOC-1", (direct_existing_rule_id("WALL-001"),),
        ),
    )
    assert_code(
        "SCOPE_SLICE_RULE_INVALID",
        lambda: ApprovalScopePlanner().plan(request(slices=partial)),
    )


def test_inconsistent_snapshot_environment_binding_fails_input():
    base = base_parts()
    impact = base[0]
    other_env = SemanticEnvironmentBinding("ENV-OTHER", "other-hash")
    planning = PlanningSnapshotBinding("PS-1", "planning-hash", "DOC-1", other_env)
    bad = ImpactAnalysis(
        impact.analysis_id, impact.canonical_operation, impact.direct_targets,
        planning, impact.snapshot_set_ref, impact.semantic_environment_ref,
        impact.predicted_impacts, impact.propagation_bundles, impact.exceptions,
        impact.analysis_fingerprint,
    )
    assert_code(
        "SCOPE_INPUT_INVALID",
        lambda: ApprovalScopePlanner().plan(request(impact=bad)),
    )
