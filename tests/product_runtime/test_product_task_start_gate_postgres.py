"""ProductTask 首次 workflow start 的 PostgreSQL 串行化 gate 契约测试。"""

from __future__ import annotations

import threading

import design_product_runtime as product_runtime


def _gate_type():
    """取得计划要求的 PostgreSQL gate；缺失时形成明确的 TDD RED。"""

    gate_type = getattr(product_runtime, "PostgresProductTaskStartGate", None)
    assert gate_type is not None, "PostgresProductTaskStartGate 尚未实现"
    return gate_type


def test_two_independent_postgres_gates_serialize_same_task(
    product_task_postgres_dsn: str,
) -> None:
    """两个独立连接竞争同一 task 时，后到者必须等前一个事务释放行锁。"""

    gate_type = _gate_type()
    first_gate = gate_type(product_task_postgres_dsn)
    second_gate = gate_type(product_task_postgres_dsn)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    failures: list[BaseException] = []

    def first_worker() -> None:
        """持有第一个数据库临界区，直到主线程显式允许释放。"""

        try:
            with first_gate.serialize("TASK-START-GATE-1"):
                first_entered.set()
                if not release_first.wait(timeout=5):
                    raise AssertionError("测试未能及时释放第一个 start gate")
        except BaseException as exc:  # noqa: BLE001 - 线程异常必须回传主测试线程。
            failures.append(exc)

    def second_worker() -> None:
        """竞争相同 task；只有拿到数据库锁之后才能设置 entered 事件。"""

        try:
            if not first_entered.wait(timeout=5):
                raise AssertionError("第一个 start gate 未及时进入")
            with second_gate.serialize("TASK-START-GATE-1"):
                second_entered.set()
        except BaseException as exc:  # noqa: BLE001 - 线程异常必须回传主测试线程。
            failures.append(exc)

    first_thread = threading.Thread(target=first_worker, daemon=True)
    second_thread = threading.Thread(target=second_worker, daemon=True)
    try:
        first_thread.start()
        assert first_entered.wait(timeout=5), "第一个 start gate 未进入临界区"
        second_thread.start()

        # 这里用事件超时只证明“第一个事务仍持锁时第二个不能进入”；真正释放后还会再证明
        # 第二个最终可以获得同一行锁，避免把线程没有调度误判成数据库串行化成功。
        assert not second_entered.wait(timeout=0.25), (
            "第二个 start gate 在第一个事务释放前进入了同一 task 临界区"
        )
        release_first.set()
        assert second_entered.wait(timeout=5), "第一个事务释放后第二个 start gate 仍未进入"
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert failures == []
    finally:
        release_first.set()
        first_gate.close()
        second_gate.close()
