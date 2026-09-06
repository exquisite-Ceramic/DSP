from __future__ import annotations

from dataclasses import fields

import pytest
from design_execution_reconciliation import (
    ExecutionSagaBuilder,
    ExecutionSagaBuilderV2,
    ExecutionSagaDefinition,
    ExecutionSagaStatus,
    ExecutionSagaStatusV2,
    InMemoryExecutionSagaStore,
    InMemoryExecutionSagaStoreV2,
    StoredExecutionSaga,
    StoredExecutionSagaV2,
)

from tests.execution_reconciliation.conftest import _build_single_slice_transaction
from tests.execution_reconciliation.test_saga_v2_definition import _phase_i_context


def test_v1_status_enum_is_unchanged() -> None:
    assert tuple(item.value for item in ExecutionSagaStatus) == (
        "READY",
        "EXECUTING",
        "PARTIALLY_COMMITTED",
        "SUCCEEDED",
        "COMPENSATING",
        "COMPENSATED",
        "COMPENSATION_FAILED",
        "FAILED",
    )
    assert "CONVERGENCE_PENDING" not in {item.value for item in ExecutionSagaStatus}
    assert "DIVERGED" not in {item.value for item in ExecutionSagaStatus}


def test_v2_status_is_a_separate_type() -> None:
    assert ExecutionSagaStatusV2 is not ExecutionSagaStatus
    assert StoredExecutionSagaV2 is not StoredExecutionSaga
    assert {
        "materialization_plan_hash",
        "required_set_hash",
        "convergence_outcome",
        "convergence_result_hash",
    }.issubset({field.name for field in fields(StoredExecutionSagaV2)})
    assert "convergence_result_hash" not in {
        field.name for field in fields(StoredExecutionSaga)
    }


def test_v1_definition_shape_has_no_materialization_lineage() -> None:
    assert "materialization_plan_hash" not in {
        field.name for field in fields(ExecutionSagaDefinition)
    }
    assert "required_set_hash" not in {
        field.name for field in fields(ExecutionSagaDefinition)
    }


def test_v1_and_v2_stores_keep_independent_revisions() -> None:
    transaction = _build_single_slice_transaction()
    v1_definition = ExecutionSagaBuilder().build(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    ctx = _phase_i_context()
    v2_definition = ExecutionSagaBuilderV2().build(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
    )
    v1_store = InMemoryExecutionSagaStore()
    v2_store = InMemoryExecutionSagaStoreV2()
    v1 = v1_store.create_saga(v1_definition)
    v2 = v2_store.create_saga(v2_definition)

    v2 = v2_store.reserve_slice_admission(
        v2.definition.saga_id,
        v2.definition.ordered_slice_hashes[0],
        expected_revision=0,
        reserved_at="2026-09-06T12:00:00Z",
    )

    assert v1.saga_revision == 0
    assert v1_store.get_saga(v1.definition.saga_id).saga_revision == 0
    assert v2.saga_revision == 1


def test_cross_version_definition_admission_is_rejected() -> None:
    transaction = _build_single_slice_transaction()
    v1_definition = ExecutionSagaBuilder().build(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    ctx = _phase_i_context()
    v2_definition = ExecutionSagaBuilderV2().build(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
    )

    with pytest.raises(TypeError):
        InMemoryExecutionSagaStore().create_saga(v2_definition)
    with pytest.raises(TypeError):
        InMemoryExecutionSagaStoreV2().create_saga(v1_definition)
