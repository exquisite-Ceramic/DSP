from __future__ import annotations

from dataclasses import fields

from design_convergence import (
    ConvergenceComparisonMode,
    ConvergenceFieldRule,
    compute_convergence_profile_hash,
)


def _rule(path: str, argument: str = "thickness") -> ConvergenceFieldRule:
    return ConvergenceFieldRule(
        subjects_from_argument="targets",
        path=path,
        expected_argument=argument,
        measurement_unit="mm",
        comparison_mode=ConvergenceComparisonMode.EXACT_CANONICAL_VALUE,
    )


def test_profile_hash_is_rule_order_independent() -> None:
    first = _rule("properties.dsp:WallThickness")
    second = _rule("properties.dsp:OtherThickness", "other_thickness")
    assert compute_convergence_profile_hash("1.0.0", (first, second)) == (
        compute_convergence_profile_hash("1.0.0", (second, first))
    )


def test_profile_hash_changes_with_semantic_rule_material() -> None:
    baseline = _rule("properties.dsp:WallThickness")
    changed_path = _rule("properties.dsp:OtherThickness")
    changed_unit = ConvergenceFieldRule(
        subjects_from_argument="targets",
        path="properties.dsp:WallThickness",
        expected_argument="thickness",
        measurement_unit="cm",
        comparison_mode=ConvergenceComparisonMode.EXACT_CANONICAL_VALUE,
    )

    baseline_hash = compute_convergence_profile_hash("1.0.0", (baseline,))
    assert baseline_hash != compute_convergence_profile_hash("2.0.0", (baseline,))
    assert baseline_hash != compute_convergence_profile_hash("1.0.0", (changed_path,))
    assert baseline_hash != compute_convergence_profile_hash("1.0.0", (changed_unit,))


def test_profile_contract_has_no_tolerance_field() -> None:
    assert "tolerance" not in {field.name for field in fields(ConvergenceFieldRule)}
