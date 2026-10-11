from __future__ import annotations

from dataclasses import replace

import pytest
from design_convergence import (
    ConvergenceStatus,
    ConvergenceVerificationError,
    CrossHostConvergenceVerifier,
    build_convergence_evidence_set,
    compute_materialization_canonical_evidence_hash,
)

from tests.convergence.test_evidence import _local_evidence


def _inputs():
    ctx, first = _local_evidence(0)
    _, second = _local_evidence(1)
    evidence_set = build_convergence_evidence_set(
        plan=ctx.materialization_plan,
        profile=ctx.case.profile,
        evidence_items=(first, second),
    )
    return ctx, first, second, evidence_set


def _changed_field(item, *, value: float | None = None, unit: str | None = None):
    original = item.verified_fields[0]
    changed_field = replace(
        original,
        value=original.value if value is None else value,
        unit=original.unit if unit is None else unit,
    )
    draft = replace(
        item,
        verified_fields=(changed_field,),
        evidence_hash="0" * 64,
    )
    return replace(
        draft,
        evidence_hash=compute_materialization_canonical_evidence_hash(draft),
    )


def test_status_enum_is_exact() -> None:
    assert tuple(item.value for item in ConvergenceStatus) == (
        "CONVERGED",
        "DIVERGED",
        "EVIDENCE_INSUFFICIENT",
    )


def test_exact_300_mm_across_required_materializations_converges() -> None:
    ctx, _, _, evidence_set = _inputs()

    result = CrossHostConvergenceVerifier().verify(
        ctx.materialization_plan,
        ctx.case.profile,
        evidence_set,
    )

    assert result.status is ConvergenceStatus.CONVERGED
    assert result.materialization_plan_hash == ctx.materialization_plan.materialization_plan_hash
    assert result.required_set_hash == ctx.materialization_plan.required_set_hash
    assert result.convergence_profile_hash == ctx.case.profile.profile_hash
    assert result.evidence_set_hash == evidence_set.evidence_set_hash
    assert len(result.convergence_result_hash) == 64


def test_exact_300_mm_vs_305_mm_diverges() -> None:
    ctx, first, second, _ = _inputs()
    changed_second = _changed_field(second, value=305.0)
    evidence_set = build_convergence_evidence_set(
        plan=ctx.materialization_plan,
        profile=ctx.case.profile,
        evidence_items=(first, changed_second),
    )

    result = CrossHostConvergenceVerifier().verify(
        ctx.materialization_plan,
        ctx.case.profile,
        evidence_set,
    )

    assert result.status is ConvergenceStatus.DIVERGED
    assert result.convergence_result_hash


def test_cross_unit_canonical_evidence_is_insufficient_without_conversion() -> None:
    ctx, first, second, _ = _inputs()
    changed_second = _changed_field(second, unit="cm")
    evidence_set = build_convergence_evidence_set(
        plan=ctx.materialization_plan,
        profile=ctx.case.profile,
        evidence_items=(first, changed_second),
    )

    result = CrossHostConvergenceVerifier().verify(
        ctx.materialization_plan,
        ctx.case.profile,
        evidence_set,
    )

    assert result.status is ConvergenceStatus.EVIDENCE_INSUFFICIENT


def test_verifier_fails_closed_on_plan_profile_or_required_set_substitution() -> None:
    ctx, _, _, evidence_set = _inputs()
    verifier = CrossHostConvergenceVerifier()

    substituted_plan = replace(
        ctx.materialization_plan,
        materialization_plan_hash="f" * 64,
    )
    with pytest.raises(ConvergenceVerificationError):
        verifier.verify(substituted_plan, ctx.case.profile, evidence_set)

    substituted_profile = replace(ctx.case.profile, profile_hash="e" * 64)
    with pytest.raises(ConvergenceVerificationError):
        verifier.verify(ctx.materialization_plan, substituted_profile, evidence_set)

    substituted_required_set = replace(
        ctx.materialization_plan,
        required_set_hash="d" * 64,
    )
    with pytest.raises(ConvergenceVerificationError):
        verifier.verify(substituted_required_set, ctx.case.profile, evidence_set)


def test_verifier_rejects_tampered_evidence_set_hash() -> None:
    ctx, _, _, evidence_set = _inputs()
    tampered = replace(evidence_set, evidence_set_hash="c" * 64)

    with pytest.raises(ConvergenceVerificationError) as exc:
        CrossHostConvergenceVerifier().verify(
            ctx.materialization_plan,
            ctx.case.profile,
            tampered,
        )
    assert exc.value.code == "CONVERGENCE_EVIDENCE_INTEGRITY_INVALID"


@pytest.mark.parametrize(
    ("autocad_value", "revit_value", "expected_status"),
    [
        (300, 300.0, ConvergenceStatus.CONVERGED),
        (0, -0.0, ConvergenceStatus.CONVERGED),
        (300, 300.00000000000006, ConvergenceStatus.DIVERGED),
        (300, 301.0, ConvergenceStatus.DIVERGED),
        (300, "300", ConvergenceStatus.DIVERGED),
        (1, True, ConvergenceStatus.DIVERGED),
        (9007199254740993, 9007199254740992.0, ConvergenceStatus.DIVERGED),
    ],
)
def test_exact_numeric_representation_preserves_value_without_tolerance(
    autocad_value, revit_value, expected_status
) -> None:
    """真实双 Host 数值表示不改变语义；不同数值与不同类型仍必须精确区分。"""

    ctx, first, second, _ = _inputs()
    autocad = _changed_field(first, value=autocad_value)
    revit = _changed_field(second, value=revit_value)
    evidence_set = build_convergence_evidence_set(
        plan=ctx.materialization_plan,
        profile=ctx.case.profile,
        evidence_items=(autocad, revit),
    )

    result = CrossHostConvergenceVerifier().verify(
        ctx.materialization_plan,
        ctx.case.profile,
        evidence_set,
    )

    assert result.status is expected_status
    assert result.evidence_set_hash == evidence_set.evidence_set_hash


def test_exact_numeric_comparison_does_not_rewrite_existing_evidence_hashes() -> None:
    """比较阶段可识别 300 与 300.0，但两份原始签名证据的 body/hash 不能被改写。"""

    ctx, first, second, _ = _inputs()
    integer_evidence = _changed_field(first, value=300)
    float_evidence = _changed_field(first, value=300.0)
    assert integer_evidence.evidence_hash != float_evidence.evidence_hash
    evidence_set = build_convergence_evidence_set(
        plan=ctx.materialization_plan,
        profile=ctx.case.profile,
        evidence_items=(integer_evidence, second),
    )
    before = tuple(
        (item.verified_fields[0].value, item.evidence_hash)
        for item in evidence_set.evidence_items
    )

    result = CrossHostConvergenceVerifier().verify(
        ctx.materialization_plan,
        ctx.case.profile,
        evidence_set,
    )

    assert result.status is ConvergenceStatus.CONVERGED
    assert result.evidence_set_hash == evidence_set.evidence_set_hash
    assert before == tuple(
        (item.verified_fields[0].value, item.evidence_hash)
        for item in evidence_set.evidence_items
    )


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_exact_numeric_comparison_fails_closed_on_nonfinite_evidence(
    invalid_value,
) -> None:
    """NaN 和无穷大不属于可比较的真实厚度，禁止产生 CONVERGED 结果。"""

    ctx, first, second, _ = _inputs()
    bad = _changed_field(first, value=invalid_value)
    evidence_set = build_convergence_evidence_set(
        plan=ctx.materialization_plan,
        profile=ctx.case.profile,
        evidence_items=(bad, second),
    )

    with pytest.raises(ConvergenceVerificationError) as exc:
        CrossHostConvergenceVerifier().verify(
            ctx.materialization_plan,
            ctx.case.profile,
            evidence_set,
        )

    assert exc.value.code == "CONVERGENCE_NONFINITE_NUMBER"
