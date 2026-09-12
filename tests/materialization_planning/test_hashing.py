from __future__ import annotations

from dataclasses import replace

from design_materialization_planning import (
    MaterializationIntent,
    compute_materialization_intent_hash,
    compute_materialization_plan_hash,
    compute_required_set_hash,
)


def _intent(slot_id: str, host_type: str) -> MaterializationIntent:
    draft = MaterializationIntent(
        materialization_id="MAT-DRAFT",
        source_operation_id="COP-123",
        source_operation_hash="1" * 64,
        semantic_targets=("WALL-001",),
        materialization_slot_id=slot_id,
        required_host_type=host_type,
        expected_effects=("PROPERTIES",),
        intent_hash="0" * 64,
    )
    intent_hash = compute_materialization_intent_hash(draft)
    return replace(
        draft,
        materialization_id=f"MAT-{intent_hash[:12]}",
        intent_hash=intent_hash,
    )


def test_required_set_hash_is_order_independent_and_content_sensitive():
    autocad = _intent("MS-AUTOCAD", "autocad")
    revit = _intent("MS-REVIT", "revit")
    baseline = compute_required_set_hash((autocad, revit))
    assert baseline == compute_required_set_hash((revit, autocad))
    assert baseline != compute_required_set_hash((autocad,))


def test_plan_hash_binds_all_lineage_and_intent_order_is_normalized():
    autocad = _intent("MS-AUTOCAD", "autocad")
    revit = _intent("MS-REVIT", "revit")
    required_set_hash = compute_required_set_hash((autocad, revit))
    kwargs = {
        "changeset_hash": "2" * 64,
        "approved_scope_hash": "3" * 64,
        "topology_snapshot_hash": "4" * 64,
        "intents": (autocad, revit),
        "required_set_hash": required_set_hash,
        "convergence_profile_hash": "5" * 64,
    }
    baseline = compute_materialization_plan_hash(**kwargs)
    assert baseline == compute_materialization_plan_hash(
        **{**kwargs, "intents": (revit, autocad)}
    )
    for field_name in (
        "changeset_hash",
        "approved_scope_hash",
        "topology_snapshot_hash",
        "required_set_hash",
        "convergence_profile_hash",
    ):
        changed = {**kwargs, field_name: "f" * 64}
        assert baseline != compute_materialization_plan_hash(**changed)
