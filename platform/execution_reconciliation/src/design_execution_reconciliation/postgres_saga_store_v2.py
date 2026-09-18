"""Execution Saga V2 的 PostgreSQL durable store 适配器。

该模块只负责数据库连接、snapshot 编解码、SQL CAS 与 owner-local outbox 原子写入；
所有 Saga V2 业务状态转换继续由 ``saga_transitions_v2`` 的纯领域函数唯一承载，
避免出现第二套状态机。
"""

from __future__ import annotations

from collections.abc import Callable

from design_gateway_authorization import AdmittedExecutionAuthorityV2
from psycopg.types.json import Jsonb

from .contracts import (
    ActualDelta,
    ReconciliationError,
    ScopeComparisonResult,
    SemanticVerificationResult,
)
from .delivery import build_saga_transition_event
from .postgres import connect_postgres
from .postgres_outbox import insert_outbox_event
from .saga_contracts_v2 import ExecutionSagaDefinitionV2
from .saga_persistence_v2 import decode_stored_saga_v2, encode_stored_saga_v2
from .saga_state_v2 import SagaConvergenceOutcome, StoredExecutionSagaV2
from .saga_transitions_v2 import (
    begin_reconciliation_transition,
    confirm_slice_admitted_transition,
    create_initial_saga_v2,
    fail_slice_before_commit_transition,
    record_convergence_outcome_transition,
    record_host_commit_transition,
    record_scope_result_transition,
    record_verification_result_transition,
    reserve_slice_admission_transition,
)

_Transition = Callable[[StoredExecutionSagaV2], StoredExecutionSagaV2]


def _transaction_timestamp_text(conn) -> str:
    """读取当前 PostgreSQL 事务的审计时间，不让 Step33 领域层自行采样 wall clock。

    ``occurred_at`` 不参与事件 fingerprint；由明确的 PostgreSQL adapter 使用数据库
    transaction timestamp，可以让 Saga 状态与 outbox 事件共享同一个本地事务时间基准。
    """
    row = conn.execute("SELECT transaction_timestamp()").fetchone()
    if row is None or row[0] is None:
        raise ReconciliationError(
            "SAGA_PERSISTENCE_ERROR",
            "PostgreSQL did not return a transaction timestamp",
        )
    return row[0].isoformat().replace("+00:00", "Z")


class PostgresExecutionSagaStoreV2:
    """使用 owner-local PostgreSQL schema 持久化 Saga V2 的严格 CAS store。"""

    def __init__(self, dsn: str) -> None:
        # migration 生命周期由部署/启动边界显式负责；store 构造本身不偷偷改 schema。
        self._conn = connect_postgres(dsn)

    def close(self) -> None:
        """关闭该 store 独占的数据库连接。"""
        self._conn.close()

    @staticmethod
    def _decode_row(row) -> StoredExecutionSagaV2:
        """恢复 snapshot，并核对冗余 SQL 列与 snapshot 内的权威证据一致。"""
        stored = decode_stored_saga_v2(row[3])
        if (
            stored.saga_revision != row[0]
            or stored.definition.saga_definition_hash != row[1]
            or stored.status.value != row[2]
        ):
            raise ReconciliationError(
                "SAGA_INTEGRITY_INVALID",
                "persisted Saga V2 columns do not match the durable snapshot",
            )
        return stored

    def _select_current(self, saga_id: str):
        """在调用方事务内读取一个 Saga 的当前 durable snapshot。"""
        return self._conn.execute(
            """
            SELECT saga_revision, definition_hash, status, snapshot
            FROM execution_saga.saga_v2
            WHERE saga_id = %s
            """,
            (saga_id,),
        ).fetchone()

    def create_saga(self, definition: ExecutionSagaDefinitionV2) -> StoredExecutionSagaV2:
        """首次插入不可变定义，并与首个 owner event 在同一事务提交。"""
        if not isinstance(definition, ExecutionSagaDefinitionV2):
            # 复用领域 owner 的稳定 TypeError，而不是让 SQL adapter 自创错误语义。
            return create_initial_saga_v2(definition)

        with self._conn.transaction():
            existing_row = self._select_current(definition.saga_id)
            if existing_row is not None:
                existing = self._decode_row(existing_row)
                return create_initial_saga_v2(definition, existing=existing)

            candidate = create_initial_saga_v2(definition)
            payload = encode_stored_saga_v2(candidate)
            cursor = self._conn.execute(
                """
                INSERT INTO execution_saga.saga_v2 (
                    saga_id,
                    saga_revision,
                    definition_hash,
                    status,
                    snapshot
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (saga_id) DO NOTHING
                """,
                (
                    candidate.definition.saga_id,
                    candidate.saga_revision,
                    candidate.definition.saga_definition_hash,
                    candidate.status.value,
                    Jsonb(payload),
                ),
            )
            if cursor.rowcount == 1:
                # Saga 初始事实与通知事件必须一起成功或一起回滚，不能留下
                # “状态已存在但跨 owner 永远不可见”的 crash window。
                insert_outbox_event(
                    self._conn,
                    build_saga_transition_event(
                        None,
                        candidate,
                        occurred_at=_transaction_timestamp_text(self._conn),
                    ),
                )
                return candidate

            # 另一个连接可能刚刚赢得 create；重新读取并执行与内存后端相同的
            # exact-definition replay/conflict 判定，绝不静默覆盖已存在定义。
            winning_row = self._select_current(definition.saga_id)
            if winning_row is None:
                raise ReconciliationError(
                    "SAGA_CONFLICT",
                    "Saga V2 create lost a concurrent insert without durable winner",
                )
            winning = self._decode_row(winning_row)
            return create_initial_saga_v2(definition, existing=winning)

    def get_saga(self, saga_id: str) -> StoredExecutionSagaV2 | None:
        """按稳定 saga_id 读取 durable snapshot；空 id 保持既有 ValueError 契约。"""
        if not isinstance(saga_id, str) or not saga_id.strip():
            raise ValueError("saga_id is required")
        normalized = saga_id.strip()
        with self._conn.transaction():
            row = self._select_current(normalized)
            return None if row is None else self._decode_row(row)

    def _transition(
        self,
        saga_id: str,
        expected_revision: int,
        transition: _Transition,
    ) -> StoredExecutionSagaV2:
        """以一次 owner-local transaction 原子提交 Saga CAS 与 outbox event。"""
        if not isinstance(saga_id, str) or not saga_id.strip():
            raise ReconciliationError("SAGA_NOT_FOUND", "execution Saga V2 was not found")
        normalized = saga_id.strip()

        with self._conn.transaction():
            row = self._select_current(normalized)
            if row is None:
                raise ReconciliationError(
                    "SAGA_NOT_FOUND",
                    "execution Saga V2 was not found",
                )
            current = self._decode_row(row)
            updated = transition(current)

            # 共享 transition 对同证据 replay 会返回原 snapshot。此时即使调用方携带
            # 较旧 expected_revision，也必须保持内存后端的 replay-safe 可观察语义；
            # 同时这里不能再产生 outbox event，否则一次逻辑 transition 会被重复发布。
            if updated == current:
                return current

            payload = encode_stored_saga_v2(updated)
            cursor = self._conn.execute(
                """
                UPDATE execution_saga.saga_v2
                SET saga_revision = %s,
                    definition_hash = %s,
                    status = %s,
                    snapshot = %s,
                    updated_at = now()
                WHERE saga_id = %s
                  AND saga_revision = %s
                """,
                (
                    updated.saga_revision,
                    updated.definition.saga_definition_hash,
                    updated.status.value,
                    Jsonb(payload),
                    normalized,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ReconciliationError(
                    "SAGA_CONFLICT",
                    "Saga V2 revision changed before durable transition commit",
                )

            # outbox INSERT 仍处于同一 psycopg transaction context。任何 fingerprint
            # conflict、数据库错误或进程异常都会让前面的 Saga UPDATE 一并回滚。
            insert_outbox_event(
                self._conn,
                build_saga_transition_event(
                    current,
                    updated,
                    occurred_at=_transaction_timestamp_text(self._conn),
                ),
            )
            return updated

    def reserve_slice_admission(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        reserved_at: str,
    ) -> StoredExecutionSagaV2:
        """持久执行 Slice admission reservation。"""
        return self._transition(
            saga_id,
            expected_revision,
            lambda stored: reserve_slice_admission_transition(
                stored,
                execution_slice_hash,
                expected_revision=expected_revision,
                reserved_at=reserved_at,
            ),
        )

    def confirm_slice_admitted(
        self,
        saga_id: str,
        authority: AdmittedExecutionAuthorityV2,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        """持久确认 Gateway admission authority。"""
        return self._transition(
            saga_id,
            expected_revision,
            lambda stored: confirm_slice_admitted_transition(
                stored,
                authority,
                expected_revision=expected_revision,
            ),
        )

    def record_host_commit(
        self,
        saga_id: str,
        actual_delta: ActualDelta,
        *,
        expected_revision: int,
        committed_at: str,
    ) -> StoredExecutionSagaV2:
        """持久记录 Host commit 证据。"""
        return self._transition(
            saga_id,
            expected_revision,
            lambda stored: record_host_commit_transition(
                stored,
                actual_delta,
                expected_revision=expected_revision,
                committed_at=committed_at,
            ),
        )

    def begin_reconciliation(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        """持久进入 Slice reconciliation。"""
        return self._transition(
            saga_id,
            expected_revision,
            lambda stored: begin_reconciliation_transition(
                stored,
                execution_slice_hash,
                expected_revision=expected_revision,
            ),
        )

    def record_scope_result(
        self,
        saga_id: str,
        result: ScopeComparisonResult,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        """持久记录 scope comparison 结果。"""
        return self._transition(
            saga_id,
            expected_revision,
            lambda stored: record_scope_result_transition(
                stored,
                result,
                expected_revision=expected_revision,
            ),
        )

    def record_verification_result(
        self,
        saga_id: str,
        result: SemanticVerificationResult,
        *,
        expected_revision: int,
        reconciled_at: str,
    ) -> StoredExecutionSagaV2:
        """持久记录 semantic verification 结果。"""
        return self._transition(
            saga_id,
            expected_revision,
            lambda stored: record_verification_result_transition(
                stored,
                result,
                expected_revision=expected_revision,
                reconciled_at=reconciled_at,
            ),
        )

    def fail_slice_before_commit(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        failed_at: str,
    ) -> StoredExecutionSagaV2:
        """持久记录 Host commit 前失败。"""
        return self._transition(
            saga_id,
            expected_revision,
            lambda stored: fail_slice_before_commit_transition(
                stored,
                execution_slice_hash,
                expected_revision=expected_revision,
                failed_at=failed_at,
            ),
        )

    def record_convergence_outcome(
        self,
        saga_id: str,
        outcome: SagaConvergenceOutcome,
        convergence_result_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        """持久记录全 REQUIRED materialization 的最终 convergence outcome。"""
        return self._transition(
            saga_id,
            expected_revision,
            lambda stored: record_convergence_outcome_transition(
                stored,
                outcome,
                convergence_result_hash,
                expected_revision=expected_revision,
            ),
        )


__all__ = ["PostgresExecutionSagaStoreV2"]
