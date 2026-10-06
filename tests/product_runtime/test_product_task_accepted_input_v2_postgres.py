"""Cross-Host Product Vertical Task 3：V2 accepted input 的 PostgreSQL owner 契约。"""

from __future__ import annotations

import psycopg
import pytest
from design_product_runtime import (
    ProductTaskRequest,
    ProductTaskRequestError,
    ProductTaskRequestV2,
    create_postgres_product_task_request_store,
)


def _reset_owner_schema(dsn: str) -> None:
    """每个用例从空 product_task owner schema 开始。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS product_task CASCADE")


def _v2_request(
    *,
    task_id: str = "TASK-V2-PG",
    binding_hash: str = "a" * 64,
    thickness_mm: float = 300.0,
) -> ProductTaskRequestV2:
    """构造 exact V2 request，便于 replay/conflict 测试。"""

    return ProductTaskRequestV2.create(
        task_id=task_id,
        project_id="PROJECT-V2",
        initiating_host_kind="REVIT",
        session_ref="SESSION-V2",
        session_binding_hash=binding_hash,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": thickness_mm, "unit": "mm"}},
    )


def _binding_payload(binding_hash: str = "a" * 64) -> dict[str, object]:
    """构造 ProductTask owner 不解释、但必须原样持久化的 SessionBindingV2 body。"""

    return {
        "session_ref": "SESSION-V2",
        "project_id": "PROJECT-V2",
        "semantic_target_id": "WALL-001",
        "semantic_environment_id": "SEM-ENV-1",
        "semantic_environment_hash": "b" * 64,
        "topology_environment_id": "TOPOLOGY-1",
        "topology_revision": 7,
        "topology_snapshot_hash": "c" * 64,
        "initiating_host_kind": "REVIT",
        "members": [
            {
                "host_kind": "AUTOCAD",
                "role": "BOUND_REQUIRED",
                "configured_reference_id": "primary-autocad",
                "configured_reference_hash": "d" * 64,
                "transport_locator": "autocad-pipe",
                "host_instance_id": "autocad-runtime",
                "document_id": r"C:\DSP\fixture.dwg",
                "native_target_id": "autocad-wall-1",
                "host_binding_fingerprint": "e" * 64,
            },
            {
                "host_kind": "REVIT",
                "role": "INITIATOR",
                "configured_reference_id": "primary-revit",
                "configured_reference_hash": "f" * 64,
                "transport_locator": "revit-pipe",
                "host_instance_id": "revit-runtime",
                "document_id": r"C:\DSP\fixture.rvt",
                "native_target_id": "revit-wall-1",
                "host_binding_fingerprint": "1" * 64,
            },
        ],
        "binding_hash": binding_hash,
    }


def test_v2_accept_persists_request_and_binding_in_one_owner_transaction(
    product_task_postgres_dsn: str,
) -> None:
    """V2 accepted input 必须在同一 owner row 同时拥有 request 与完整 binding body。"""

    _reset_owner_schema(product_task_postgres_dsn)
    request = _v2_request()
    payload = _binding_payload()
    store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    try:
        accepted = store.create_v2(
            request,
            session_binding_hash=request.session_binding_hash,
            session_binding_payload=payload,
        )
    finally:
        store.close()

    with psycopg.connect(product_task_postgres_dsn) as conn:
        row = conn.execute(
            """
            SELECT
                request_version,
                request_hash,
                payload,
                session_binding_hash,
                session_binding_payload
            FROM product_task.request
            WHERE task_id = %s
            """,
            (request.task_id,),
        ).fetchone()

    assert row is not None
    assert row[0] == "V2"
    assert row[1].strip() == request.request_hash
    assert row[2]["version"] == "V2"
    assert row[3].strip() == request.session_binding_hash
    assert row[4] == payload
    assert accepted.request == request
    assert accepted.session_binding_hash == request.session_binding_hash
    assert dict(accepted.session_binding_payload) == payload


def test_same_v2_body_replays_and_different_version_body_or_binding_conflicts(
    product_task_postgres_dsn: str,
) -> None:
    """一个 task_id 只有一个 request version/body/binding winner。"""

    _reset_owner_schema(product_task_postgres_dsn)
    store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    request = _v2_request()
    try:
        first = store.create_v2(
            request,
            session_binding_hash=request.session_binding_hash,
            session_binding_payload=_binding_payload(),
        )
        replay = store.create_v2(
            request,
            session_binding_hash=request.session_binding_hash,
            session_binding_payload=_binding_payload(),
        )
        assert first == replay

        changed = _v2_request(binding_hash="2" * 64)
        with pytest.raises(ProductTaskRequestError) as changed_binding:
            store.create_v2(
                changed,
                session_binding_hash=changed.session_binding_hash,
                session_binding_payload=_binding_payload("2" * 64),
            )

        v1 = ProductTaskRequest.create(
            task_id=request.task_id,
            project_id="PROJECT-V2",
            host_kind="REVIT",
            session_ref="SESSION-V1",
            requested_action="SET_SELECTED_WALL_THICKNESS",
            intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
        )
        with pytest.raises(ProductTaskRequestError) as changed_version:
            store.create(v1)
    finally:
        store.close()

    assert changed_binding.value.code == "PRODUCT_TASK_REQUEST_CONFLICT"
    assert changed_version.value.code == "PRODUCT_TASK_REQUEST_CONFLICT"


def test_historical_v1_row_remains_readable_after_v2_schema_upgrade(
    product_task_postgres_dsn: str,
) -> None:
    """Task 3 migration 必须原样读取升级前只含三业务列的 V1 row。"""

    _reset_owner_schema(product_task_postgres_dsn)
    request = ProductTaskRequest.create(
        task_id="TASK-HISTORICAL-V1",
        project_id="PROJECT-V1",
        host_kind="REVIT",
        session_ref="SESSION-V1",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )
    with psycopg.connect(product_task_postgres_dsn, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA product_task")
        conn.execute(
            """
            CREATE TABLE product_task.request (
                task_id TEXT PRIMARY KEY,
                request_hash CHAR(64) NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            INSERT INTO product_task.request (task_id, request_hash, payload)
            VALUES (%s, %s, %s::jsonb)
            """,
            (
                request.task_id,
                request.request_hash,
                """{"host_kind":"REVIT","intent_arguments":{"thickness":{"unit":"mm","value":300.0}},"project_id":"PROJECT-V1","requested_action":"SET_SELECTED_WALL_THICKNESS","session_ref":"SESSION-V1"}""",
            ),
        )

    store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    try:
        assert store.get(request.task_id) == request
    finally:
        store.close()


def test_server_restart_recovers_v2_binding_without_client_sqlite(
    product_task_postgres_dsn: str,
) -> None:
    """首次接受后，只重开 PostgreSQL owner 也必须恢复完整 V2 accepted input。"""

    _reset_owner_schema(product_task_postgres_dsn)
    request = _v2_request(task_id="TASK-V2-RESTART")
    payload = _binding_payload()

    first = create_postgres_product_task_request_store(product_task_postgres_dsn)
    first.create_v2(
        request,
        session_binding_hash=request.session_binding_hash,
        session_binding_payload=payload,
    )
    first.close()

    reopened = create_postgres_product_task_request_store(product_task_postgres_dsn)
    try:
        recovered = reopened.get_v2(request.task_id)
    finally:
        reopened.close()

    assert recovered is not None
    assert recovered.request == request
    assert recovered.session_binding_hash == request.session_binding_hash
    assert dict(recovered.session_binding_payload) == payload
