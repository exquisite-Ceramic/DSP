"""Execution reconciliation evidence body 的 PostgreSQL content-addressed store。"""

from __future__ import annotations

from collections.abc import Mapping

from psycopg.types.json import Jsonb

from .contracts import (
    ActualDelta,
    ReconciliationError,
    SemanticVerificationResult,
    VerificationEvidenceBundle,
)
from .evidence_store import (
    decode_reconciliation_evidence,
    encode_reconciliation_evidence,
    evidence_kind_and_hash,
)
from .postgres import connect_postgres

_TABLE = "execution_saga.reconciliation_evidence"
_CODEC_VERSION = 1


class PostgresReconciliationEvidenceStore:
    """把 V2 query/recovery 必需 evidence body 持久化到 execution owner schema。"""

    def __init__(self, dsn: str) -> None:
        """store 只打开连接；migration 生命周期仍由部署/启动边界显式负责。"""

        self._conn = connect_postgres(dsn)

    def close(self) -> None:
        """关闭该 store 独占连接。"""

        self._conn.close()

    @staticmethod
    def _corrupt(message: str) -> ReconciliationError:
        """生成稳定 evidence corruption error。"""

        return ReconciliationError("RECONCILIATION_EVIDENCE_CORRUPT", message)

    def _put(self, value: object) -> str:
        """create-once 保存 body；same hash/body replay-safe，不同 body fail closed。"""

        kind, content_hash = evidence_kind_and_hash(value)
        payload = encode_reconciliation_evidence(value)
        with self._conn.transaction():
            cursor = self._conn.execute(
                f"""
                INSERT INTO {_TABLE} (
                    evidence_hash,
                    evidence_kind,
                    codec_version,
                    body
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (evidence_hash) DO NOTHING
                """,
                (
                    content_hash,
                    kind,
                    _CODEC_VERSION,
                    Jsonb(payload),
                ),
            )
            if cursor.rowcount == 1:
                return content_hash

            row = self._conn.execute(
                f"""
                SELECT evidence_kind, codec_version, body
                FROM {_TABLE}
                WHERE evidence_hash = %s
                """,
                (content_hash,),
            ).fetchone()
            if row is None:
                raise self._corrupt(
                    "evidence insert conflict did not resolve to a durable row"
                )
            if row[0] != kind or row[1] != _CODEC_VERSION or row[2] != payload:
                raise self._corrupt(
                    "same evidence hash is already bound to a different body"
                )
            return content_hash

    def _get(self, content_hash: str, expected_kind: str):
        """按 exact hash 读取并重验 codec/body/hash lineage。"""

        if not isinstance(content_hash, str) or not content_hash.strip():
            raise ValueError("content_hash is required")
        normalized = content_hash.strip()
        row = self._conn.execute(
            f"""
            SELECT evidence_kind, codec_version, body
            FROM {_TABLE}
            WHERE evidence_hash = %s
            """,
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        if row[0] != expected_kind or row[1] != _CODEC_VERSION:
            raise self._corrupt(
                "evidence row kind/version does not match requested contract"
            )
        body = row[2]
        if not isinstance(body, Mapping):
            raise self._corrupt("evidence JSON body is not an object")
        try:
            value = decode_reconciliation_evidence(body)
            _, decoded_hash = evidence_kind_and_hash(value)
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ReconciliationError):
                raise
            raise self._corrupt("persisted evidence body cannot be decoded") from exc
        if decoded_hash != normalized:
            raise self._corrupt(
                "persisted evidence body does not match its row content hash"
            )
        return value

    def put_actual_delta(self, value: ActualDelta) -> str:
        """持久化完整 ActualDelta body。"""

        return self._put(value)

    def get_actual_delta(self, content_hash: str) -> ActualDelta | None:
        """按 hash 读取完整 ActualDelta body。"""

        value = self._get(content_hash, "actual_delta")
        return value if isinstance(value, ActualDelta) else None

    def put_verification_bundle(self, value: VerificationEvidenceBundle) -> str:
        """持久化完整 VerificationEvidenceBundle body。"""

        return self._put(value)

    def get_verification_bundle(
        self,
        content_hash: str,
    ) -> VerificationEvidenceBundle | None:
        """按 hash 读取完整 verification bundle。"""

        value = self._get(content_hash, "verification_bundle")
        return value if isinstance(value, VerificationEvidenceBundle) else None

    def put_verification_result(self, value: SemanticVerificationResult) -> str:
        """持久化完整 SemanticVerificationResult body。"""

        return self._put(value)

    def get_verification_result(
        self,
        content_hash: str,
    ) -> SemanticVerificationResult | None:
        """按 hash 读取完整 semantic verification result。"""

        value = self._get(content_hash, "verification_result")
        return value if isinstance(value, SemanticVerificationResult) else None


__all__ = ["PostgresReconciliationEvidenceStore"]
