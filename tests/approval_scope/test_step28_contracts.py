import pytest
from design_approval_scope import (
    ApprovalScopeDefinition,
    CanonicalAspect,
    CanonicalEffectEvidence,
    EntityPredicate,
    EntitySelector,
    PredicateField,
    PredicateOperator,
    PredicateTerm,
)
from design_impact import PlanningSnapshotBinding, SemanticEnvironmentBinding, SnapshotSetBinding


def test_selector_requires_exactly_one_selector_form():
    with pytest.raises(ValueError):
        EntitySelector()
    predicate = EntityPredicate(
        all_of=(
            PredicateTerm(
                PredicateField.SEMANTIC_ID,
                PredicateOperator.EQ,
                ("WALL-001",),
            ),
        )
    )
    with pytest.raises(ValueError):
        EntitySelector(entities=("WALL-001",), predicate=predicate)


def test_predicate_cardinality_is_closed_world():
    with pytest.raises(ValueError):
        PredicateTerm(PredicateField.SEMANTIC_ID, PredicateOperator.EQ, ("A", "B"))
    with pytest.raises(ValueError):
        PredicateTerm(PredicateField.SEMANTIC_ID, PredicateOperator.IN, ())


def test_native_aspect_is_not_a_canonical_aspect():
    with pytest.raises(ValueError):
        CanonicalAspect("AutoCAD.Handle")


def test_selector_and_predicate_normalize_order():
    selector = EntitySelector(entities=("B", "A", "B"))
    assert selector.entities == ("A", "B")
    term = PredicateTerm(
        PredicateField.CANONICAL_KIND,
        PredicateOperator.IN,
        ("ifc:IfcWall", "ifc:IfcDoor", "ifc:IfcWall"),
    )
    assert term.values == ("ifc:IfcDoor", "ifc:IfcWall")


def test_scope_definition_rejects_non_sha256_body_hash():
    env = SemanticEnvironmentBinding("ENV", "h")
    planning = PlanningSnapshotBinding("PS", "p", "DOC", env)
    snapshot_set = SnapshotSetBinding("SS", "s", ("PS",), env)
    evidence = CanonicalEffectEvidence(
        "move.v1",
        "1.0.0",
        (CanonicalAspect.PLACEMENT,),
    )
    with pytest.raises(ValueError):
        ApprovalScopeDefinition(
            "DEF",
            "impact",
            evidence,
            planning,
            snapshot_set,
            env,
            (),
            (),
            (),
            (),
            (),
            "not-a-hash",
        )
