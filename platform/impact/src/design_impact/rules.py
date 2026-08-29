"""Deterministic structured rule evaluation helpers for Step27."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import (
    ConstraintOperator,
    ConstraintOutcome,
    ConstraintRule,
    ImpactError,
)


def _evaluate_operator(operator: ConstraintOperator, actual: Any, expected: Any) -> bool:
    try:
        if operator is ConstraintOperator.EQ:
            return actual == expected
        if operator is ConstraintOperator.NE:
            return actual != expected
        if operator is ConstraintOperator.GT:
            return actual > expected
        if operator is ConstraintOperator.GE:
            return actual >= expected
        if operator is ConstraintOperator.LT:
            return actual < expected
        if operator is ConstraintOperator.LE:
            return actual <= expected
        if operator is ConstraintOperator.IN:
            if isinstance(expected, (str, bytes)):
                raise TypeError("IN expected value must be a collection, not text")
            return actual in expected
    except (TypeError, AttributeError) as exc:
        raise ImpactError(
            "CONSTRAINT_INVALID",
            f"constraint operator {operator.value} cannot evaluate supplied values",
        ) from exc
    raise ImpactError("CONSTRAINT_INVALID", f"unsupported constraint operator: {operator!r}")


def evaluate_constraint(
    rule: ConstraintRule,
    *,
    observed_facts: Mapping[str, Mapping[str, object]],
) -> tuple[ConstraintOutcome, tuple[str, ...]]:
    """Evaluate one structured rule against explicitly supplied canonical facts."""

    if not isinstance(rule, ConstraintRule):
        raise TypeError("rule must be ConstraintRule")
    if not isinstance(observed_facts, Mapping):
        raise TypeError("observed_facts must be a mapping")

    applicable = tuple(sorted(set(rule.applies_to).intersection(observed_facts.keys())))
    if not applicable:
        return ConstraintOutcome.NOT_APPLICABLE, ()

    results: list[bool] = []
    for semantic_id in applicable:
        facts = observed_facts[semantic_id]
        if not isinstance(facts, Mapping):
            raise ImpactError(
                "CONSTRAINT_INVALID",
                f"facts for {semantic_id} must be a mapping",
            )
        fact_key = rule.evaluation_spec.fact_key
        if fact_key not in facts:
            raise ImpactError(
                "CONSTRAINT_INVALID",
                f"required fact {fact_key!r} is missing for {semantic_id}",
            )
        results.append(
            _evaluate_operator(
                rule.evaluation_spec.operator,
                facts[fact_key],
                rule.evaluation_spec.expected_value,
            )
        )

    if all(results):
        return ConstraintOutcome.PASS, applicable
    return ConstraintOutcome.FAIL, applicable


__all__ = ["evaluate_constraint"]
