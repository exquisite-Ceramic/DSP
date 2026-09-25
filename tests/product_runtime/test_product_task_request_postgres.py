"""Real Product Vertical Task 1：ProductTask PostgreSQL owner 的真实 PG17 contract。"""

from __future__ import annotations

from importlib import import_module

import psycopg
import pytest
from design_product_runtime.contracts import ProductTaskRequest, ProductTaskRequestError


def _store_api():
    """延迟加载尚未实现的 PostgreSQL owner，让 RED 表现为明确 capability failure。"""

    try:
        module = import_module("design_product_runtime.postgres_request_store")
    except ModuleNotFoundError as exc:
        if exc.name == "design_product_runtime.postgres_request_store":
            pytest.fail("ProductTask PostgreSQL request store is not implemented")
        raise
    return module.create_postgres_product_task_request_store


def _reset_owner_schema(dsn: str) -> None:
    """每个用例从空 ProductTask owner schema 开始。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS product_task CASCADE")


def _request(*, task_id: str = "TASK-PG", thickness_mm: float = 300.0) -> ProductTaskRequest:
    """构造同一 task 可用于 replay/conflict 的冻结 vertical request。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id="PROJECT-PG",
        host_kind="REVIT",
        session_ref="SESSION-PG",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": thickness_mm, "unit": "mm"}},
    )


def test_factory_bootstraps_request_table_in_product_task_owner_schema(
    product_task_postgres_dsn: str,
) -> None:
    """request 表只能由独立 product_task schema 持有。"""

    _reset_owner_schema(product_task_postgres_dsn)
    factory = _store_api()
    store = factory(product_task_postgres_dsn)
    try:
        with psycopg.connect(product_task_postgres_dsn) as conn:
            rows = conn.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_name = 'request'
                ORDER BY table_schema
                """
            ).fetchall()
    finally:
        store.close()

    assert rows == [("product_task", "request")]


def test_create_is_replay_safe_and_same_task_different_body_conflicts(
    product_task_postgres_dsn: str,
) -> None:
    """task_id 是 create-once identity；同 body 幂等，不同 body fail closed。"""

    _reset_owner_schema(product_task_postgres_dsn)
    factory = _store_api()
    store = factory(product_task_postgres_dsn)
    request_300 = _request(thickness_mm=300.0)
    request_350 = _request(thickness_mm=350.0)
    try:
        first = store.create(request_300)
        replay = store.create(request_300)

        assert first == request_300
        assert replay == request_300
        assert first.request_hash == replay.request_hash

        with pytest.raises(ProductTaskRequestError) as captured:
            store.create(request_350)
    finally:
        store.close()

    assert captured.value.code == "PRODUCT_TASK_REQUEST_CONFLICT"


def test_fresh_store_recovers_exact_request_after_create(
    product_task_postgres_dsn: str,
) -> None:
    """owner object 重建后仍按 exact task_id 返回持久化 request。"""

    _reset_owner_schema(product_task_postgres_dsn)
    factory = _store_api()
    request = _request()

    first = factory(product_task_postgres_dsn)
    first.create(request)
    first.close()

    reopened = factory(product_task_postgres_dsn)
    try:
        recovered = reopened.get(request.task_id)
    finally:
        reopened.close()

    assert recovered == request
    assert recovered is not None
    assert recovered.request_hash == request.request_hash


def test_request_commit_survives_before_any_workflow_checkpoint_exists(
    product_task_postgres_dsn: str,
) -> None:
    """request 写入后、workflow start 前崩溃不依赖 LangGraph/checkpoint 对象存活。"""

    _reset_owner_schema(product_task_postgres_dsn)
    factory = _store_api()
    request = _request(task_id="TASK-PRESTART")

    store_before_crash = factory(product_task_postgres_dsn)
    store_before_crash.create(request)
    store_before_crash.close()

    fresh_process_store = factory(product_task_postgres_dsn)
    try:
        assert fresh_process_store.get(request.task_id) == request
    finally:
        fresh_process_store.close()


def test_corrupted_payload_fails_integrity_validation_on_read(
    product_task_postgres_dsn: str,
) -> None:
    """数据库 payload 被篡改后不能只信 request_hash 列或 task_id 主键。"""

    _reset_owner_schema(product_task_postgres_dsn)
    factory = _store_api()
    request = _request(task_id="TASK-CORRUPT-PAYLOAD")
    store = factory(product_task_postgres_dsn)
    store.create(request)
    store.close()

    with psycopg.connect(product_task_postgres_dsn, autocommit=True) as conn:
        conn.execute(
            """
            UPDATE product_task.request
            SET payload = jsonb_set(
                payload,
                '{intent_arguments,thickness,value}',
                '350.0'::jsonb
            )
            WHERE task_id = %s
            """,
            (request.task_id,),
        )

    reopened = factory(product_task_postgres_dsn)
    try:
        with pytest.raises(ProductTaskRequestError) as captured:
            reopened.get(request.task_id)
    finally:
        reopened.close()

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"


def test_corrupted_hash_fails_integrity_validation_on_read(
    product_task_postgres_dsn: str,
) -> None:
    """数据库 request_hash 被篡改后必须由 contract constructor 再次 fail closed。"""

    _reset_owner_schema(product_task_postgres_dsn)
    factory = _store_api()
    request = _request(task_id="TASK-CORRUPT-HASH")
    store = factory(product_task_postgres_dsn)
    store.create(request)
    store.close()

    with psycopg.connect(product_task_postgres_dsn, autocommit=True) as conn:
        conn.execute(
            "UPDATE product_task.request SET request_hash = %s WHERE task_id = %s",
            ("0" * 64, request.task_id),
        )

    reopened = factory(product_task_postgres_dsn)
    try:
        with pytest.raises(ProductTaskRequestError) as captured:
            reopened.get(request.task_id)
    finally:
        reopened.close()

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"
