"""Task 14：V2 query 在 accepted/evidence owners 重启后仍可离线投影。"""

from __future__ import annotations

import os

import psycopg
import pytest
from design_orchestrator import WorkflowCheckpointView, WorkflowPhase
from design_execution_reconciliation.postgres import (
    apply_execution_saga_migrations,
    connect_postgres,
)
from design_execution_reconciliation.postgres_evidence import (
    PostgresReconciliationEvidenceStore,
)
from design_product_runtime import (
    ProductTaskQueryService,
    create_postgres_product_task_request_store,
)

from tests.execution_coordination._materialized_support import (
    execute,
    materialized_fixture,
)
from tests.product_runtime.test_product_task_query_v2 import (
    _DecisionReader,
    _DispatchReader,
    _accepted,
)


def _dsn() -> str:
    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def test_v2_query_survives_request_and_evidence_store_restart_with_hosts_absent() -> None:
    """重建 query 后只读 PostgreSQL request/evidence，不需要任何 Host/client 配置。"""

    dsn = _dsn()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS product_task CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS execution_saga CASCADE")

    migration_conn = connect_postgres(dsn)
    try:
        apply_execution_saga_migrations(migration_conn)
    finally:
        migration_conn.close()

    fixture = materialized_fixture()
    result = execute(fixture)
    accepted = _accepted(fixture.ctx, thickness_mm=777.0)

    requests = create_postgres_product_task_request_store(dsn)
    evidence = PostgresReconciliationEvidenceStore(dsn)
    try:
        requests.create_v2(accepted)
        stored = fixture.reconciliation.service.get_saga(result.saga_id)
        assert stored is not None
        for state in stored.slice_states:
            assert state.actual_delta_hash is not None
            assert state.verification_hash is not None
            delta = fixture.reconciliation.service.get_actual_delta(
                state.actual_delta_hash
            )
            verification = fixture.reconciliation.service.get_verification_result(
                state.verification_hash
            )
            assert delta is not None
            assert verification is not None
            bundle = fixture.reconciliation.service.get_verification_bundle(
                verification.evidence_bundle_hash
            )
            assert bundle is not None
            evidence.put_actual_delta(delta)
            evidence.put_verification_result(verification)
            evidence.put_verification_bundle(bundle)
    finally:
        requests.close()
        evidence.close()

    reopened_requests = create_postgres_product_task_request_store(dsn)
    reopened_evidence = PostgresReconciliationEvidenceStore(dsn)
    checkpoint = WorkflowCheckpointView(
        task_id=accepted.request.task_id,
        phase=WorkflowPhase.COMPLETED,
        saga_id=result.saga_id,
    )

    class _Checkpoint:
        def get_checkpoint(self, task_id):
            assert task_id == accepted.request.task_id
            return checkpoint

    class _SagaStore:
        def get_saga(self, saga_id):
            assert saga_id == result.saga_id
            return fixture.reconciliation.service.get_saga(saga_id)

    try:
        query = ProductTaskQueryService(
            request_store=reopened_requests,
            checkpoint_reader=_Checkpoint(),
            saga_store=_SagaStore(),
            proposal_decision_reader=_DecisionReader(),
            dispatch_intent_reader=_DispatchReader(
                fixture.dispatch_intents.prepared_by_slice
            ),
            evidence_reader=reopened_evidence,
        )
        view = query.get(accepted.request.task_id)
    finally:
        reopened_requests.close()
        reopened_evidence.close()

    assert view.version == "V2"
    assert view.status.value == "SUCCEEDED"
    assert {item.verified_thickness_mm for item in view.materializations} == {
        300.0
    }
    assert accepted.request.intent_arguments["thickness"]["value"] == 777.0
