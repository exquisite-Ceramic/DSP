from __future__ import annotations

from dataclasses import fields, is_dataclass, replace

import pytest
from design_execution_coordination import (
    HostReadinessReceipt,
    ReadinessBarrierResult,
    ReadinessBarrierStatus,
    ReadinessStatus,
    compute_readiness_receipt_hash,
)
from design_execution_planning import HostRuntimeRef


def _receipt(status: ReadinessStatus = ReadinessStatus.READY) -> HostReadinessReceipt:
    provisional = HostReadinessReceipt(
        materialization_id="MAT-001",
        materialization_plan_hash="a" * 64,
        execution_slice_hash="b" * 64,
        binding_set_hash="c" * 64,
        grant_hash="d" * 64,
        host_runtime_ref=HostRuntimeRef("autocad", "ACAD-01", "DOC-AUTOCAD"),
        observed_revision=7,
        status=status,
        failure_code=None if status is ReadinessStatus.READY else "HOST_NOT_READY",
        receipt_hash="0" * 64,
    )
    return replace(
        provisional,
        receipt_hash=compute_readiness_receipt_hash(provisional),
    )


def test_readiness_statuses_are_closed_world_and_separate_from_coordination_status() -> None:
    assert tuple(item.value for item in ReadinessStatus) == ("READY", "NOT_READY")
    assert tuple(item.value for item in ReadinessBarrierStatus) == (
        "READY",
        "NOT_READY",
    )


def test_receipt_contract_is_frozen_and_binds_exact_runtime_lineage() -> None:
    assert is_dataclass(HostReadinessReceipt)
    assert HostReadinessReceipt.__dataclass_params__.frozen is True
    assert {field.name for field in fields(HostReadinessReceipt)} == {
        "materialization_id",
        "materialization_plan_hash",
        "execution_slice_hash",
        "binding_set_hash",
        "grant_hash",
        "host_runtime_ref",
        "observed_revision",
        "status",
        "failure_code",
        "receipt_hash",
    }
    receipt = _receipt()
    assert receipt.host_runtime_ref.host_type == "autocad"
    assert receipt.host_runtime_ref.host_instance_id == "ACAD-01"
    assert receipt.host_runtime_ref.document_ref == "DOC-AUTOCAD"
    assert receipt.receipt_hash == compute_readiness_receipt_hash(receipt)


def test_receipt_hash_binds_revision_status_failure_and_runtime() -> None:
    baseline = _receipt()
    assert compute_readiness_receipt_hash(replace(baseline, observed_revision=8)) != (
        baseline.receipt_hash
    )
    assert compute_readiness_receipt_hash(
        replace(
            baseline,
            status=ReadinessStatus.NOT_READY,
            failure_code="HOST_NOT_READY",
        )
    ) != baseline.receipt_hash
    assert compute_readiness_receipt_hash(
        replace(
            baseline,
            host_runtime_ref=HostRuntimeRef("autocad", "ACAD-02", "DOC-AUTOCAD"),
        )
    ) != baseline.receipt_hash


def test_ready_and_not_ready_failure_code_invariants_fail_closed() -> None:
    with pytest.raises(ValueError, match="READY receipt cannot carry failure_code"):
        replace(_receipt(), failure_code="SHOULD-NOT-EXIST")
    with pytest.raises(ValueError, match="NOT_READY receipt requires failure_code"):
        HostReadinessReceipt(
            materialization_id="MAT-001",
            materialization_plan_hash="a" * 64,
            execution_slice_hash="b" * 64,
            binding_set_hash="c" * 64,
            grant_hash="d" * 64,
            host_runtime_ref=HostRuntimeRef("revit", "RVT-01", "DOC-REVIT"),
            observed_revision=0,
            status=ReadinessStatus.NOT_READY,
            failure_code=None,
            receipt_hash="0" * 64,
        )


def test_barrier_result_contract_is_frozen() -> None:
    assert is_dataclass(ReadinessBarrierResult)
    assert ReadinessBarrierResult.__dataclass_params__.frozen is True
    assert {field.name for field in fields(ReadinessBarrierResult)} == {
        "status",
        "receipts",
        "failure_ref",
    }
    ready = ReadinessBarrierResult(ReadinessBarrierStatus.READY, (_receipt(),), None)
    assert ready.failure_ref is None
