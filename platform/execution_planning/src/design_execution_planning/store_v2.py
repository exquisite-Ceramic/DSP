"""Step30 V2 owner-local immutable execution-plan reference store."""

from __future__ import annotations

from .contracts import ExecutionPlanningError
from .v2 import ExecutionPlanV2


def _validate_reference(plan: ExecutionPlanV2) -> None:
    """Validate the owner-issued content-addressed id/hash relation only.

    Full ``validate_execution_plan_v2`` also requires Step28 and topology owner
    artifacts, so that cross-owner validation remains in composition rather than
    turning this owner-local store into a service locator.
    """
    if not isinstance(plan, ExecutionPlanV2):
        raise TypeError("plan must be ExecutionPlanV2")
    if plan.execution_plan_id != f"XPV2-{plan.execution_plan_hash[:12]}":
        raise ExecutionPlanningError(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "ExecutionPlanV2 id does not match its owner hash",
        )


class InMemoryExecutionPlanV2Store:
    """Reference in-memory lookup surface for immutable Step30 V2 plans."""

    def __init__(self) -> None:
        self._items: dict[str, ExecutionPlanV2] = {}

    def put(self, plan: ExecutionPlanV2) -> None:
        """Store one V2 plan; exact replay is safe and conflicts fail closed."""
        existing = self._items.get(plan.execution_plan_id)
        if existing is not None and existing != plan:
            raise ExecutionPlanningError(
                "EXECUTION_PLAN_REFERENCE_CONFLICT",
                f"execution plan reference conflicts: {plan.execution_plan_id}",
            )
        _validate_reference(plan)
        if existing is None:
            self._items[plan.execution_plan_id] = plan

    def get(self, execution_plan_id: str) -> ExecutionPlanV2:
        """Resolve one owner artifact and re-check its local id/hash relation."""
        try:
            plan = self._items[execution_plan_id]
        except KeyError as exc:
            raise ExecutionPlanningError(
                "EXECUTION_PLAN_REFERENCE_NOT_FOUND",
                f"execution plan reference is unresolved: {execution_plan_id}",
            ) from exc
        _validate_reference(plan)
        return plan


__all__ = ["InMemoryExecutionPlanV2Store"]
