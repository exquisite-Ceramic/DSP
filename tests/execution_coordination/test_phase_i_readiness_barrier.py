from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_coordination import (
    ReadinessBarrierStatus,
    ReadinessError,
    ReadinessStatus,
)

from tests.execution_coordination._support import barrier, phase_i_readiness_inputs

_barrier = barrier
_phase_i_readiness_inputs = phase_i_readiness_inputs


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ReadinessError) as exc:
        operation()
    assert exc.value.code == code


def test_all_required_ready_returns_one_exact_receipt_per_materialization() -> None:
    ctx = phase_i_readiness_inputs()
    readiness_barrier, registry, ports = barrier()
    result = readiness_barrier.check_all(
        ctx.materialization_plan,
        ctx.execution_plan,
        ctx.binding_sets,
        ctx.authorities,
    )

    assert result.status is ReadinessBarrierStatus.READY
    assert result.failure_ref is None
    assert len(result.receipts) == len(ctx.materialization_plan.intents) == 2
    assert tuple(item.host_runtime_ref.host_type for item in result.receipts) == (
        "autocad",
        "revit",
    )
    assert {item.materialization_id for item in result.receipts} == {
        item.materialization_id for item in ctx.materialization_plan.intents
    }
    assert len(registry.resolutions) == 2
    assert all(len(port.calls) == 1 for port in ports.values())


def test_any_not_ready_returns_not_ready_after_observing_all_required_hosts() -> None:
    ctx = phase_i_readiness_inputs()
    readiness_barrier, _, ports = barrier(
        {
            "autocad": ReadinessStatus.NOT_READY,
            "revit": ReadinessStatus.READY,
        }
    )
    result = readiness_barrier.check_all(
        ctx.materialization_plan,
        ctx.execution_plan,
        ctx.binding_sets,
        ctx.authorities,
    )

    assert result.status is ReadinessBarrierStatus.NOT_READY
    assert result.failure_ref == "AUTOCAD_NOT_READY"
    assert len(result.receipts) == 2
    assert all(len(port.calls) == 1 for port in ports.values())


@pytest.mark.parametrize("collection", ("binding", "authority"))
def test_missing_or_extra_required_binding_or_authority_fails_closed(collection) -> None:
    ctx = phase_i_readiness_inputs()
    readiness_barrier, _, _ = barrier()
    bindings = ctx.binding_sets
    authorities = ctx.authorities
    if collection == "binding":
        _assert_code(
            "READINESS_LINEAGE_MISMATCH",
            lambda: readiness_barrier.check_all(
                ctx.materialization_plan,
                ctx.execution_plan,
                bindings[:1],
                authorities,
            ),
        )
        _assert_code(
            "READINESS_LINEAGE_MISMATCH",
            lambda: readiness_barrier.check_all(
                ctx.materialization_plan,
                ctx.execution_plan,
                (*bindings, bindings[0]),
                authorities,
            ),
        )
    else:
        _assert_code(
            "READINESS_LINEAGE_MISMATCH",
            lambda: readiness_barrier.check_all(
                ctx.materialization_plan,
                ctx.execution_plan,
                bindings,
                authorities[:1],
            ),
        )
        _assert_code(
            "READINESS_LINEAGE_MISMATCH",
            lambda: readiness_barrier.check_all(
                ctx.materialization_plan,
                ctx.execution_plan,
                bindings,
                (*authorities, authorities[0]),
            ),
        )


@pytest.mark.parametrize("corrupt", ("materialization", "binding", "runtime"))
def test_receipt_lineage_mismatch_fails_closed(corrupt) -> None:
    ctx = phase_i_readiness_inputs()
    readiness_barrier, _, _ = barrier(corrupt_host="revit", corrupt=corrupt)
    _assert_code(
        "READINESS_LINEAGE_MISMATCH",
        lambda: readiness_barrier.check_all(
            ctx.materialization_plan,
            ctx.execution_plan,
            ctx.binding_sets,
            ctx.authorities,
        ),
    )


def test_authority_or_binding_substitution_fails_before_any_readiness_check() -> None:
    ctx = phase_i_readiness_inputs()
    readiness_barrier, _, ports = barrier()
    substituted = replace(
        ctx.authorities[1],
        binding_set_hash=ctx.binding_sets[0].binding_set_hash,
    )
    _assert_code(
        "READINESS_LINEAGE_MISMATCH",
        lambda: readiness_barrier.check_all(
            ctx.materialization_plan,
            ctx.execution_plan,
            ctx.binding_sets,
            (ctx.authorities[0], substituted),
        ),
    )
    assert all(port.calls == [] for port in ports.values())
