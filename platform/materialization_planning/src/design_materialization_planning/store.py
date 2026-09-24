"""Phase I owner-local immutable MaterializationPlan reference store."""

from __future__ import annotations

from .contracts import MaterializationPlan, MaterializationPlanningError
from .hashing import (
    compute_materialization_intent_hash,
    compute_materialization_plan_hash,
    compute_required_set_hash,
)


def _validate_plan(plan: MaterializationPlan) -> None:
    """Recompute the owner-local content-addressed materialization plan identity."""
    if not isinstance(plan, MaterializationPlan):
        raise TypeError("plan must be MaterializationPlan")

    for intent in plan.intents:
        expected_intent_hash = compute_materialization_intent_hash(intent)
        if (
            intent.intent_hash != expected_intent_hash
            or intent.materialization_id != f"MAT-{expected_intent_hash[:12]}"
        ):
            raise MaterializationPlanningError(
                "MATERIALIZATION_PLAN_INTEGRITY_INVALID",
                "materialization intent does not match its owner hash/id",
            )

    expected_required_set_hash = compute_required_set_hash(plan.intents)
    expected_plan_hash = compute_materialization_plan_hash(
        changeset_hash=plan.changeset_hash,
        approved_scope_hash=plan.approved_scope_hash,
        topology_snapshot_hash=plan.topology_snapshot_hash,
        intents=plan.intents,
        required_set_hash=plan.required_set_hash,
        convergence_profile_hash=plan.convergence_profile_hash,
    )
    if (
        plan.required_set_hash != expected_required_set_hash
        or plan.materialization_plan_hash != expected_plan_hash
    ):
        raise MaterializationPlanningError(
            "MATERIALIZATION_PLAN_INTEGRITY_INVALID",
            "materialization plan does not match its owner content hash",
        )


class InMemoryMaterializationPlanStore:
    """Reference in-memory lookup keyed by the plan's canonical content hash."""

    def __init__(self) -> None:
        self._items: dict[str, MaterializationPlan] = {}

    def put(self, plan: MaterializationPlan) -> None:
        """Store a validated plan; exact hash/content replay is idempotent."""
        if not isinstance(plan, MaterializationPlan):
            raise TypeError("plan must be MaterializationPlan")
        identity = plan.materialization_plan_hash
        existing = self._items.get(identity)
        if existing is not None and existing != plan:
            raise MaterializationPlanningError(
                "MATERIALIZATION_PLAN_REFERENCE_CONFLICT",
                f"materialization plan reference conflicts: {identity}",
            )
        _validate_plan(plan)
        if existing is None:
            self._items[identity] = plan

    def get(self, materialization_plan_hash: str) -> MaterializationPlan:
        """Resolve and revalidate the authoritative owner artifact."""
        try:
            plan = self._items[materialization_plan_hash]
        except KeyError as exc:
            raise MaterializationPlanningError(
                "MATERIALIZATION_PLAN_REFERENCE_NOT_FOUND",
                f"materialization plan reference is unresolved: {materialization_plan_hash}",
            ) from exc
        _validate_plan(plan)
        return plan


__all__ = ["InMemoryMaterializationPlanStore"]
