"""Task 7：known-commit 独立 evidence 暂不可得时必须保持可恢复 durable truth。"""

from __future__ import annotations

import inspect

from design_execution_coordination import (
    ConvergenceEvidencePort,
    MaterializedCoordinationStatus,
    VerificationEvidenceUnavailable,
)
from design_execution_reconciliation import (
    HostDispatchStatus,
    SliceReconciliationStatusV2,
)

from tests.execution_coordination._materialized_support import execute, materialized_fixture


def _host_execute_count(fixture) -> int:
    """统计所有 materialized Host ports 的真实 execute 次数。"""
    return sum(len(port.calls) for port in fixture.host_registry.ports.values())


def test_v2_evidence_port_receives_exact_admitted_lineage() -> None:
    """evidence builder 必须显式消费 admitted authority 与 exact binding set。"""
    parameters = inspect.signature(ConvergenceEvidencePort.build_bundle).parameters
    assert "authority" in parameters
    assert "binding_set" in parameters


def test_known_commit_evidence_unavailable_preserves_recovery_truth() -> None:
    """独立 READ 暂不可得不能丢失 Host commit，也不能再次执行 Host mutation。"""
    failure = VerificationEvidenceUnavailable(
        "VERIFICATION_EVIDENCE_UNAVAILABLE",
        "independent post-commit READ is temporarily unavailable",
    )
    fixture = materialized_fixture(bundle_failure=failure)

    result = execute(fixture)

    assert result.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED
    assert result.failure_ref == "VERIFICATION_EVIDENCE_UNAVAILABLE"
    assert _host_execute_count(fixture) == 1

    assert len(fixture.dispatch_intents.by_id) == 1
    intent = next(iter(fixture.dispatch_intents.by_id.values()))
    assert intent.status is HostDispatchStatus.HOST_COMMITTED

    stored = fixture.reconciliation.service.get_saga(result.saga_id)
    assert stored is not None
    active = [
        state
        for state in stored.slice_states
        if state.execution_slice_hash == result.active_slice_hash
    ]
    assert len(active) == 1
    state = active[0]
    assert state.status is SliceReconciliationStatusV2.RECONCILING
    assert state.scope_comparison_hash is not None
    assert state.verification_hash is None

    replay = execute(fixture)
    assert replay.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED
    assert replay.saga_id == result.saga_id
    assert _host_execute_count(fixture) == 1
