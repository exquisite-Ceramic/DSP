"""Atomic ApprovalAdmission consumption semantics for Step32 stores."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from design_gateway_authorization import (
    ApprovalRecord,
    ApprovalState,
    GatewayAuthorizationError,
    GatewayAuthorizationService,
    InMemoryGatewayAuthorizationStore,
)


@pytest.fixture
def approval_record(valid_approval_request, spy_store) -> ApprovalRecord:
    return GatewayAuthorizationService(spy_store).consume_approval(valid_approval_request)


@pytest.fixture
def store() -> InMemoryGatewayAuthorizationStore:
    return InMemoryGatewayAuthorizationStore()


def test_first_consume_persists_active_stored_approval(store, approval_record) -> None:
    result = store.consume_admission_once(
        approval_record.admission_id,
        approval_record.admission_fingerprint,
        approval_record,
    )
    assert result == approval_record
    stored = store.get_approval(approval_record.approval_id)
    assert stored is not None
    assert stored.record == approval_record
    assert stored.lifecycle.state is ApprovalState.ACTIVE
    assert stored.lifecycle.revoked_at is None
    assert stored.lifecycle.revocation_reason is None


def test_same_admission_and_fingerprint_is_strict_replay(store, approval_record) -> None:
    store.consume_admission_once(
        approval_record.admission_id,
        approval_record.admission_fingerprint,
        approval_record,
    )
    with pytest.raises(GatewayAuthorizationError) as exc:
        store.consume_admission_once(
            approval_record.admission_id,
            approval_record.admission_fingerprint,
            approval_record,
        )
    assert exc.value.code == "APPROVAL_ADMISSION_ALREADY_CONSUMED"


def test_same_admission_with_different_fingerprint_is_conflict(store, approval_record) -> None:
    store.consume_admission_once(
        approval_record.admission_id,
        approval_record.admission_fingerprint,
        approval_record,
    )
    conflicting = replace(
        approval_record,
        admission_fingerprint="e" * 64,
    )
    with pytest.raises(GatewayAuthorizationError) as exc:
        store.consume_admission_once(
            conflicting.admission_id,
            conflicting.admission_fingerprint,
            conflicting,
        )
    assert exc.value.code == "APPROVAL_ADMISSION_CONFLICT"


def test_same_admission_concurrency_creates_exactly_one_record(store, approval_record) -> None:
    def consume():
        try:
            return store.consume_admission_once(
                approval_record.admission_id,
                approval_record.admission_fingerprint,
                approval_record,
            )
        except GatewayAuthorizationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: consume(), range(32)))

    successes = [item for item in results if isinstance(item, ApprovalRecord)]
    assert successes == [approval_record]
    assert results.count("APPROVAL_ADMISSION_ALREADY_CONSUMED") == 31
    stored = store.get_approval(approval_record.approval_id)
    assert stored is not None
    assert stored.record == approval_record


def test_missing_approval_returns_no_store_state(store) -> None:
    assert store.get_approval("AR-MISSING") is None


def test_service_has_no_half_consumed_state_when_store_fails(
    valid_approval_request,
) -> None:
    class FailingStore:
        def __init__(self) -> None:
            self.committed = False

        def consume_admission_once(self, admission_id, admission_fingerprint, approval_record):
            raise RuntimeError("commit failed before persistence")

    failing = FailingStore()
    with pytest.raises(RuntimeError, match="commit failed"):
        GatewayAuthorizationService(failing).consume_approval(valid_approval_request)
    assert failing.committed is False

    recovery_store = InMemoryGatewayAuthorizationStore()
    recovered = GatewayAuthorizationService(recovery_store).consume_approval(valid_approval_request)
    assert recovery_store.get_approval(recovered.approval_id) is not None
