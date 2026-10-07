"""Operation Proposal decision 的 PostgreSQL authoritative owner。"""

from __future__ import annotations

from collections.abc import Mapping

import psycopg
from psycopg.rows import dict_row

from .proposal_decision import (
    HumanDecisionState,
    ProposalContinuationState,
    ProposalDecisionRecord,
)
from .workflow_contracts import StableRef

_OWNER_SCHEMA = "orchestrator_proposal"
_TABLE = "decision"
_SUBJECT_MISMATCH = "PROPOSAL_DECISION_SUBJECT_MISMATCH"


def _required_text(value: object, field_name: str) -> str:
    """把数据库 locator/原因规范化为非空文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


def _subject_parts(subject_ref: StableRef) -> tuple[str, str]:
    """提取必须带 content hash 的 exact proposal subject identity。"""

    if not isinstance(subject_ref, StableRef):
        raise ValueError("subject_ref must be a StableRef")
    if subject_ref.content_hash is None:
        raise ValueError("subject_ref must include content_hash")
    return subject_ref.ref_id, subject_ref.content_hash


_BOOTSTRAP_RACE_ERRORS = (
    psycopg.errors.DuplicateSchema,
    psycopg.errors.DuplicateTable,
    psycopg.errors.UniqueViolation,
)


def _bootstrap_owner_schema(dsn: str) -> None:
    """并发 worker 启动时幂等建立 owner DDL，不把 catalog race 提升为业务失败。"""

    with psycopg.connect(dsn, autocommit=True) as admin:
        try:
            admin.execute(f"CREATE SCHEMA IF NOT EXISTS {_OWNER_SCHEMA}")
        except _BOOTSTRAP_RACE_ERRORS:
            # PostgreSQL 的 IF NOT EXISTS 仍可能在并发 catalog insert 时发生唯一键竞争。
            # 该异常只说明另一个 bootstrap 已赢得相同 DDL identity，不属于 decision CAS。
            pass

    with psycopg.connect(dsn, autocommit=True) as admin:
        try:
            admin.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_OWNER_SCHEMA}.{_TABLE} (
                    task_id TEXT NOT NULL,
                    pause_id TEXT NOT NULL,
                    subject_ref_id TEXT NOT NULL,
                    subject_content_hash CHAR(64) NOT NULL,
                    human_decision TEXT NOT NULL,
                    continuation TEXT NOT NULL,
                    revision BIGINT NOT NULL,
                    reason TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (task_id, pause_id)
                )
                """
            )
        except _BOOTSTRAP_RACE_ERRORS:
            pass

        row = admin.execute(
            "SELECT to_regclass(%s)",
            (f"{_OWNER_SCHEMA}.{_TABLE}",),
        ).fetchone()
        if row is None or row[0] is None:
            raise RuntimeError("proposal decision owner bootstrap did not create table")


class PostgresProposalDecisionStore:
    """按 task/pause create-once 持有 human decision 与 stale continuation。"""

    def __init__(self, dsn: str) -> None:
        """bootstrap 独立 owner schema，并为每个 store 使用独立连接。"""

        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("dsn must not be blank")
        normalized = dsn.strip()
        _bootstrap_owner_schema(normalized)
        self._connection = psycopg.connect(
            normalized,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        self._connection.execute(f"SET search_path TO {_OWNER_SCHEMA}")

    def claim_accept(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
    ) -> ProposalDecisionRecord:
        """首次 ACCEPT 原子发布；已有 winner 时只重读，不覆盖。"""

        return self._claim_initial(
            task_id,
            pause_id,
            subject_ref,
            human_decision=HumanDecisionState.ACCEPTED,
            continuation=ProposalContinuationState.CONTINUABLE,
            reason=None,
        )

    def claim_reject(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
    ) -> ProposalDecisionRecord:
        """首次 REJECT 原子发布；已有 winner 时保留 authoritative history。"""

        return self._claim_initial(
            task_id,
            pause_id,
            subject_ref,
            human_decision=HumanDecisionState.REJECTED,
            continuation=ProposalContinuationState.CONTINUABLE,
            reason=None,
        )

    def invalidate_gate_a(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
        reason: str,
    ) -> ProposalDecisionRecord:
        """首次 Gate-A stale 与 ACCEPT/REJECT 竞争同一个 owner row。"""

        return self._claim_initial(
            task_id,
            pause_id,
            subject_ref,
            human_decision=HumanDecisionState.AWAITING,
            continuation=ProposalContinuationState.STALE_GATE_A,
            reason=_required_text(reason, "reason"),
        )

    def invalidate_gate_b(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
        reason: str,
    ) -> ProposalDecisionRecord:
        """只把 ACCEPTED+CONTINUABLE 推进到 STALE_GATE_B。"""

        task = _required_text(task_id, "task_id")
        pause = _required_text(pause_id, "pause_id")
        subject_id, subject_hash = _subject_parts(subject_ref)
        normalized_reason = _required_text(reason, "reason")

        with self._connection.transaction():
            row = self._select_for_update(task, pause)
            if row is None:
                raise ValueError(
                    "PROPOSAL_DECISION_NOT_FOUND: Gate B requires durable ACCEPT"
                )
            current = self._decode(row)
            self._require_subject(current, subject_id, subject_hash)
            if (
                current.human_decision is not HumanDecisionState.ACCEPTED
                or current.continuation
                is not ProposalContinuationState.CONTINUABLE
            ):
                return current
            updated = self._connection.execute(
                """
                UPDATE decision
                SET continuation = %s,
                    revision = revision + 1,
                    reason = %s,
                    updated_at = now()
                WHERE task_id = %s
                  AND pause_id = %s
                  AND revision = %s
                RETURNING *
                """,
                (
                    ProposalContinuationState.STALE_GATE_B.value,
                    normalized_reason,
                    task,
                    pause,
                    current.revision,
                ),
            ).fetchone()
            if updated is None:
                reread = self._select_for_update(task, pause)
                if reread is None:
                    raise RuntimeError("proposal decision disappeared during Gate B")
                return self._decode(reread)
            return self._decode(updated)

    def get(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
    ) -> ProposalDecisionRecord | None:
        """按 exact task/pause/subject 读取；同 pause 换 subject 明确报错。"""

        task = _required_text(task_id, "task_id")
        pause = _required_text(pause_id, "pause_id")
        subject_id, subject_hash = _subject_parts(subject_ref)
        row = self._connection.execute(
            """
            SELECT *
            FROM decision
            WHERE task_id = %s AND pause_id = %s
            """,
            (task, pause),
        ).fetchone()
        if row is None:
            return None
        current = self._decode(row)
        self._require_subject(current, subject_id, subject_hash)
        return current

    def get_for_task(self, task_id: str) -> ProposalDecisionRecord | None:
        """按 exact task 读取唯一 proposal history；不做 latest/reverse lookup。"""

        task = _required_text(task_id, "task_id")
        rows = self._connection.execute(
            """
            SELECT *
            FROM decision
            WHERE task_id = %s
            ORDER BY pause_id
            LIMIT 2
            """,
            (task,),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError(
                "PROPOSAL_DECISION_TASK_CONFLICT: "
                "one V2 ProductTask must not own multiple proposal decisions"
            )
        return self._decode(rows[0])

    def _claim_initial(
        self,
        task_id: str,
        pause_id: str,
        subject_ref: StableRef,
        *,
        human_decision: HumanDecisionState,
        continuation: ProposalContinuationState,
        reason: str | None,
    ) -> ProposalDecisionRecord:
        """用唯一键竞争 initial transition；冲突方只返回 durable winner。"""

        task = _required_text(task_id, "task_id")
        pause = _required_text(pause_id, "pause_id")
        subject_id, subject_hash = _subject_parts(subject_ref)

        with self._connection.transaction():
            inserted = self._connection.execute(
                """
                INSERT INTO decision (
                    task_id,
                    pause_id,
                    subject_ref_id,
                    subject_content_hash,
                    human_decision,
                    continuation,
                    revision,
                    reason
                )
                VALUES (%s, %s, %s, %s, %s, %s, 1, %s)
                ON CONFLICT (task_id, pause_id) DO NOTHING
                RETURNING *
                """,
                (
                    task,
                    pause,
                    subject_id,
                    subject_hash,
                    human_decision.value,
                    continuation.value,
                    reason,
                ),
            ).fetchone()
            if inserted is not None:
                return self._decode(inserted)
            row = self._select_for_update(task, pause)
            if row is None:
                raise RuntimeError(
                    "proposal decision conflict did not resolve to a durable row"
                )
            current = self._decode(row)
            self._require_subject(current, subject_id, subject_hash)
            return current

    def _select_for_update(
        self,
        task_id: str,
        pause_id: str,
    ) -> Mapping[str, object] | None:
        """在当前事务内锁住 exact owner row。"""

        return self._connection.execute(
            """
            SELECT *
            FROM decision
            WHERE task_id = %s AND pause_id = %s
            FOR UPDATE
            """,
            (task_id, pause_id),
        ).fetchone()

    @staticmethod
    def _decode(row: Mapping[str, object]) -> ProposalDecisionRecord:
        """从 durable row 重建稳定 contract 并再次验证状态组合。"""

        return ProposalDecisionRecord(
            task_id=row["task_id"],
            pause_id=row["pause_id"],
            subject_ref=StableRef(
                row["subject_ref_id"],
                row["subject_content_hash"],
            ),
            human_decision=HumanDecisionState(row["human_decision"]),
            continuation=ProposalContinuationState(row["continuation"]),
            revision=row["revision"],
            reason=row["reason"],
        )

    @staticmethod
    def _require_subject(
        record: ProposalDecisionRecord,
        subject_ref_id: str,
        subject_content_hash: str,
    ) -> None:
        """同 task/pause 若绑定别的 subject，禁止把它解释成 replay。"""

        if (
            record.subject_ref.ref_id != subject_ref_id
            or record.subject_ref.content_hash != subject_content_hash
        ):
            raise ValueError(
                f"{_SUBJECT_MISMATCH}: task/pause already owns another proposal subject"
            )

    def close(self) -> None:
        """幂等关闭 owner connection。"""

        if not self._connection.closed:
            self._connection.close()


def create_postgres_proposal_decision_store(dsn: str) -> PostgresProposalDecisionStore:
    """创建 Proposal decision PostgreSQL owner。"""

    return PostgresProposalDecisionStore(dsn)


__all__ = [
    "PostgresProposalDecisionStore",
    "create_postgres_proposal_decision_store",
]
