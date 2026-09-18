"""Execution Saga owner 的 PostgreSQL Host dispatch intent durable store。"""

from __future__ import annotations

import re
from uuid import UUID, uuid5

from .contracts import ReconciliationError
from .dispatch_intent import HostDispatchIntent, HostDispatchStatus
from .postgres import connect_postgres

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_OBSERVATION_NAMESPACE = UUID("e8bead9e-ef83-55d8-a946-e89965986074")


def _text(value: object, field_name: str) -> str:
    """规范化数据库适配器入口的非空文本。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: object | None, field_name: str) -> str | None:
    """规范化可选 recovery evidence 引用。"""
    return None if value is None else _text(value, field_name)


def _digest(value: object, field_name: str) -> str:
    """校验 observation 使用的证据哈希。"""
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _expected_revision(value: object) -> int:
    """校验调用方携带的 intent CAS revision。"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("expected_revision must be an integer")
    if value < 0:
        raise ValueError("expected_revision must be non-negative")
    return value


def _timestamp_text(value) -> str:
    """把 PostgreSQL timestamptz 恢复为仓库统一使用的 UTC 文本形式。"""
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _decode_row(row) -> HostDispatchIntent:
    """把 host_dispatch_intent 行恢复为不可变领域对象。"""
    return HostDispatchIntent(
        dispatch_intent_id=(
            row[0] if isinstance(row[0], UUID) else UUID(str(row[0]))
        ),
        saga_id=row[1],
        execution_slice_hash=row[2],
        grant_hash=row[3],
        binding_set_hash=row[4],
        host_instance_id=row[5],
        document_ref=row[6],
        idempotency_key=(
            row[7] if isinstance(row[7], UUID) else UUID(str(row[7]))
        ),
        expected_host_revision=row[8],
        status=HostDispatchStatus(row[9]),
        intent_revision=row[10],
        prepared_at=_timestamp_text(row[11]),
    )


_SELECT_COLUMNS = """
    dispatch_intent_id,
    saga_id,
    execution_slice_hash,
    grant_hash,
    binding_set_hash,
    host_instance_id,
    document_ref,
    idempotency_key,
    expected_host_revision,
    status,
    intent_revision,
    prepared_at
"""


def _same_admitted_lineage(existing: HostDispatchIntent, candidate: HostDispatchIntent) -> bool:
    """判断是否是同一 Saga/Slice 已冻结 admitted execution lineage 的 replay。

    ``prepared_at`` 是审计时间，``expected_host_revision`` 不参与计划冻结的 candidate
    identity。若 replay 提供了不同审计时间或 revision hint，仍返回数据库中最早持久化
    的 intent；绝不覆盖 durable truth。
    """
    return (
        existing.dispatch_intent_id == candidate.dispatch_intent_id
        and existing.grant_hash == candidate.grant_hash
        and existing.binding_set_hash == candidate.binding_set_hash
        and existing.host_instance_id == candidate.host_instance_id
        and existing.document_ref == candidate.document_ref
        and existing.idempotency_key == candidate.idempotency_key
    )


class PostgresHostDispatchIntentStore:
    """以 owner-local PostgreSQL transaction 持久化 Host dispatch/recovery evidence。"""

    def __init__(self, dsn: str) -> None:
        """创建该 store 独占的 PostgreSQL 连接；migration 生命周期由外部负责。"""
        self._conn = connect_postgres(dsn)

    def close(self) -> None:
        """关闭该 store 独占连接。"""
        self._conn.close()

    def _select_by_id(self, dispatch_intent_id: UUID):
        """在调用方 transaction 内按主键读取 intent。"""
        return self._conn.execute(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM execution_saga.host_dispatch_intent
            WHERE dispatch_intent_id = %s
            """,
            (dispatch_intent_id,),
        ).fetchone()

    def _select_by_slice(self, saga_id: str, execution_slice_hash: str):
        """按唯一 Saga/Slice 读取已经冻结的 post-admission intent。"""
        return self._conn.execute(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM execution_saga.host_dispatch_intent
            WHERE saga_id = %s AND execution_slice_hash = %s
            """,
            (saga_id, execution_slice_hash),
        ).fetchone()

    def prepare(self, intent: HostDispatchIntent) -> HostDispatchIntent:
        """首次持久化 intent；同 lineage replay-safe，不同 lineage fail closed。

        数据库唯一键只保持 ``(saga_id, execution_slice_hash)``，故同一逻辑 Slice
        不会因 grant/binding 改变而产生第二条可执行 intent。冲突候选只用于检测，
        不能通过扩大 unique key 获得新的执行授权。
        """
        if not isinstance(intent, HostDispatchIntent):
            raise TypeError("intent must be HostDispatchIntent")
        if intent.status is not HostDispatchStatus.PREPARED or intent.intent_revision != 0:
            raise ValueError("new dispatch intent must be PREPARED at revision 0")

        with self._conn.transaction():
            inserted = self._conn.execute(
                """
                INSERT INTO execution_saga.host_dispatch_intent (
                    dispatch_intent_id,
                    saga_id,
                    execution_slice_hash,
                    grant_hash,
                    binding_set_hash,
                    host_instance_id,
                    document_ref,
                    idempotency_key,
                    expected_host_revision,
                    status,
                    intent_revision,
                    prepared_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING dispatch_intent_id
                """,
                (
                    intent.dispatch_intent_id,
                    intent.saga_id,
                    intent.execution_slice_hash,
                    intent.grant_hash,
                    intent.binding_set_hash,
                    intent.host_instance_id,
                    intent.document_ref,
                    intent.idempotency_key,
                    intent.expected_host_revision,
                    intent.status.value,
                    intent.intent_revision,
                    intent.prepared_at,
                ),
            ).fetchone()

            if inserted is not None:
                row = self._select_by_id(intent.dispatch_intent_id)
                if row is None:
                    raise ReconciliationError(
                        "DISPATCH_INTENT_CONFLICT",
                        "inserted dispatch intent could not be reloaded",
                    )
                return _decode_row(row)

            # ON CONFLICT 也可能由 document/idempotency unique key 触发，因此必须回查
            # canonical Saga/Slice owner key，不能把任意 unique collision 当成安全 replay。
            row = self._select_by_slice(intent.saga_id, intent.execution_slice_hash)
            if row is None:
                raise ReconciliationError(
                    "DISPATCH_INTENT_CONFLICT",
                    "dispatch identity collides with a different durable Host intent",
                )
            existing = _decode_row(row)
            if not _same_admitted_lineage(existing, intent):
                raise ReconciliationError(
                    "DISPATCH_INTENT_CONFLICT",
                    "Saga/Slice is already bound to a different admitted dispatch lineage",
                )
            return existing

    def get(self, dispatch_intent_id: UUID) -> HostDispatchIntent | None:
        """按 durable intent 主键读取当前状态。"""
        if not isinstance(dispatch_intent_id, UUID):
            raise TypeError("dispatch_intent_id must be UUID")
        with self._conn.transaction():
            row = self._select_by_id(dispatch_intent_id)
            return None if row is None else _decode_row(row)

    def _transition(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        target_status: HostDispatchStatus,
        observed_at: str,
        evidence_ref: str | None = None,
        evidence_hash: str | None = None,
    ) -> HostDispatchIntent:
        """用严格 CAS 原子推进状态并追加 observation。

        UPDATE 与 observation INSERT 位于同一 PostgreSQL transaction；任一写入失败都
        会整体回滚，因此不会出现“状态已经改变但恢复证据缺失”的本地 crash window。
        """
        if not isinstance(dispatch_intent_id, UUID):
            raise TypeError("dispatch_intent_id must be UUID")
        revision = _expected_revision(expected_revision)
        if not isinstance(target_status, HostDispatchStatus):
            raise TypeError("target_status must be HostDispatchStatus")
        normalized_observed_at = _text(observed_at, "observed_at")
        normalized_evidence_ref = _optional_text(evidence_ref, "evidence_ref")
        normalized_evidence_hash = (
            None if evidence_hash is None else _digest(evidence_hash, "evidence_hash")
        )

        with self._conn.transaction():
            row = self._conn.execute(
                f"""
                UPDATE execution_saga.host_dispatch_intent
                SET status = %s,
                    intent_revision = intent_revision + 1,
                    updated_at = %s
                WHERE dispatch_intent_id = %s
                  AND intent_revision = %s
                RETURNING {_SELECT_COLUMNS}
                """,
                (
                    target_status.value,
                    normalized_observed_at,
                    dispatch_intent_id,
                    revision,
                ),
            ).fetchone()
            if row is None:
                raise ReconciliationError(
                    "DISPATCH_INTENT_CONFLICT",
                    "dispatch intent revision changed before durable transition commit",
                )

            updated = _decode_row(row)
            observation_id = uuid5(
                _OBSERVATION_NAMESPACE,
                (
                    f"{updated.dispatch_intent_id}:"
                    f"{updated.intent_revision}:{target_status.value}"
                ),
            )
            self._conn.execute(
                """
                INSERT INTO execution_saga.host_dispatch_observation (
                    observation_id,
                    dispatch_intent_id,
                    observation_kind,
                    observed_at,
                    evidence_ref,
                    evidence_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    observation_id,
                    updated.dispatch_intent_id,
                    target_status.value,
                    normalized_observed_at,
                    normalized_evidence_ref,
                    normalized_evidence_hash,
                ),
            )
            return updated

    def mark_dispatched(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录平台已越过 durable-intent 边界并开始 Host dispatch。"""
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            target_status=HostDispatchStatus.DISPATCHED,
            observed_at=observed_at,
        )

    def mark_outcome_unknown(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        failure_ref: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录响应缺失等未知结果；该状态不能被解释成 Host 未提交。"""
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            target_status=HostDispatchStatus.OUTCOME_UNKNOWN,
            observed_at=observed_at,
            evidence_ref=_text(failure_ref, "failure_ref"),
        )

    def mark_host_committed(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        evidence_hash: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录已经获得 Host commit 正向证据，但不替代后续 semantic reconciliation。"""
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            target_status=HostDispatchStatus.HOST_COMMITTED,
            observed_at=observed_at,
            evidence_hash=_digest(evidence_hash, "evidence_hash"),
        )

    def mark_safe_to_retry(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        evidence_ref: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """仅在已有“未提交”正向证据时记录 SAFE_TO_RETRY。"""
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            target_status=HostDispatchStatus.SAFE_TO_RETRY,
            observed_at=observed_at,
            evidence_ref=_text(evidence_ref, "evidence_ref"),
        )

    def mark_reconciled(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        evidence_hash: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录 Host intent 已由 read-back/verification evidence 完成恢复闭环。"""
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            target_status=HostDispatchStatus.RECONCILED,
            observed_at=observed_at,
            evidence_hash=_digest(evidence_hash, "evidence_hash"),
        )


__all__ = ["PostgresHostDispatchIntentStore"]
