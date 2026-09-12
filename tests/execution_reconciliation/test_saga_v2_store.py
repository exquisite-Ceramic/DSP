from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_reconciliation import (
    ExecutionSagaBuilder,
    ExecutionSagaBuilderV2,
    ExecutionSagaControllerV2,
    ExecutionSagaDefinition,
    ExecutionSagaDefinitionV2,
    ExecutionSagaStatusV2,
    InMemoryExecutionSagaStore,
    InMemoryExecutionSagaStoreV2,
    ReconciliationError,
    SliceReconciliationStatusV2,
)

from tests.execution_reconciliation.conftest import _build_single_slice_transaction
from tests.execution_reconciliation.test_saga_v2_definition import _phase_i_context


def _v2_definition():
    ctx = _phase_i_context()
    definition = ExecutionSagaBuilderV2().build(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
    )
    return ctx, definition


def test_v2_store_create_is_durable_and_cas_revisioned() -> None:
    _, definition = _v2_definition()
    store = InMemoryExecutionSagaStoreV2()

    stored = store.create_saga(definition)
    assert stored.definition == definition
    assert stored.saga_revision == 0
    assert stored.status is ExecutionSagaStatusV2.READY
    assert tuple(item.sequence_index for item in stored.slice_states) == (0, 1)
    assert all(
        item.status is SliceReconciliationStatusV2.NOT_STARTED
        for item in stored.slice_states
    )
    assert store.create_saga(definition) == stored
    assert store.get_saga(definition.saga_id) == stored


def test_v2_controller_builds_and_persists_one_definition() -> None:
    ctx, _ = _v2_definition()
    store = InMemoryExecutionSagaStoreV2()
    controller = ExecutionSagaControllerV2(store)

    stored = controller.create_saga(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
    )

    assert store.get_saga(stored.definition.saga_id) == stored
    assert stored.definition.execution_plan_hash == ctx.execution_plan.execution_plan_hash


def test_reservation_is_evidence_replay_safe_and_strict_cas() -> None:
    _, definition = _v2_definition()
    store = InMemoryExecutionSagaStoreV2()
    store.create_saga(definition)
    first_hash = definition.ordered_slice_hashes[0]

    reserved = store.reserve_slice_admission(
        definition.saga_id,
        first_hash,
        expected_revision=0,
        reserved_at="2026-09-06T12:00:00Z",
    )
    assert reserved.saga_revision == 1
    assert reserved.status is ExecutionSagaStatusV2.EXECUTING

    replay = store.reserve_slice_admission(
        definition.saga_id,
        first_hash,
        expected_revision=0,
        reserved_at="2026-09-06T12:00:00Z",
    )
    assert replay == reserved

    with pytest.raises(ReconciliationError) as exc:
        store.reserve_slice_admission(
            definition.saga_id,
            first_hash,
            expected_revision=0,
            reserved_at="2026-09-06T12:00:01Z",
        )
    assert exc.value.code == "SAGA_CONFLICT"


def test_v2_authority_admission_persists_exact_materialization_lineage() -> None:
    ctx, definition = _v2_definition()
    store = InMemoryExecutionSagaStoreV2()
    stored = store.create_saga(definition)
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]

    stored = store.reserve_slice_admission(
        definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at="2026-09-06T12:00:00Z",
    )
    admitted = store.confirm_slice_admitted(
        definition.saga_id,
        authority,
        expected_revision=stored.saga_revision,
    )
    state = admitted.slice_states[0]

    assert state.materialization_id == execution_slice.materialization_id
    assert state.materialization_plan_hash == execution_slice.materialization_plan_hash
    assert state.grant_hash == authority.grant_hash
    assert state.binding_set_hash == authority.binding_set_hash
    assert state.admitted_host_instance_id == authority.host_instance_id
    assert state.status is SliceReconciliationStatusV2.ADMITTED


def test_v2_authority_substitution_fails_before_persistence() -> None:
    ctx, definition = _v2_definition()
    store = InMemoryExecutionSagaStoreV2()
    stored = store.create_saga(definition)
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    stored = store.reserve_slice_admission(
        definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at="2026-09-06T12:00:00Z",
    )

    corrupted = replace(authority, materialization_plan_hash="f" * 64)
    with pytest.raises(ReconciliationError) as exc:
        store.confirm_slice_admitted(
            definition.saga_id,
            corrupted,
            expected_revision=stored.saga_revision,
        )
    assert exc.value.code == "SAGA_INTEGRITY_INVALID"
    assert store.get_saga(definition.saga_id) == stored


def test_v1_and_v2_stores_reject_each_others_definition_types() -> None:
    _, v2_definition = _v2_definition()
    transaction = _build_single_slice_transaction()
    v1_definition = ExecutionSagaBuilder().build(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert isinstance(v1_definition, ExecutionSagaDefinition)
    assert isinstance(v2_definition, ExecutionSagaDefinitionV2)

    with pytest.raises(TypeError):
        InMemoryExecutionSagaStore().create_saga(v2_definition)
    with pytest.raises(TypeError):
        InMemoryExecutionSagaStoreV2().create_saga(v1_definition)
