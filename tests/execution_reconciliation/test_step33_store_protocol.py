"""Task10 public Store Protocol must expose failure and compensation mutations."""

from __future__ import annotations

import design_execution_reconciliation as reconciliation


def test_public_store_protocol_exposes_task10_mutations() -> None:
    for method_name in (
        "fail_slice_before_commit",
        "begin_compensation",
        "record_compensation_result",
    ):
        assert hasattr(reconciliation.ExecutionSagaStore, method_name)
