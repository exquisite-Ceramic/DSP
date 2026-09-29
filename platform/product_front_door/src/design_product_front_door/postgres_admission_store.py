"""Configured-policy ApprovalAdmission 的 PostgreSQL create-once issuance store。"""

from __future__ import annotations

from collections.abc import Mapping

import psycopg
from psycopg.rows import dict_row

from design_gateway_authorization import ApprovalAdmission, compute_admission_fingerprint
from design_impact import SemanticEnvironmentBinding

_OWNER_SCHEMA = "product_policy"
_TABLE = "admission"
_CONFLICT = "FRONT_DOOR_APPROVAL_ADMISSION_CONFLICT"
_INTEGRITY_INVALID = "FRONT_DOOR_APPROVAL_ADMISSION_INTEGRITY_INVALID"


class PostgresConfiguredPolicyAdmissionStore:
    """按最终 ChangeSet/scope lineage create-once 持久化 policy issuance evidence。"""

    def __init__(self, dsn: str) -> None:
        """初始化独立 owner schema，并持有一个显式可关闭的 PostgreSQL 连接。"""

        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("dsn must be a non-blank string")
        normalized_dsn = dsn.strip()

        with psycopg.connect(normalized_dsn, autocommit=True) as admin:
            admin.execute(f"CREATE SCHEMA IF NOT EXISTS {_OWNER_SCHEMA}")
            admin.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_OWNER_SCHEMA}.{_TABLE} (
                    changeset_hash CHAR(64) NOT NULL,
                    approved_scope_hash CHAR(64) NOT NULL,
                    admission_id TEXT NOT NULL,
                    semantic_environment_id TEXT NOT NULL,
                    semantic_environment_hash TEXT NOT NULL,
                    approver TEXT NOT NULL,
                    policy_snapshot_hash CHAR(64) NOT NULL,
                    policy_allowed_operations TEXT[] NOT NULL,
                    approved_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    admission_fingerprint CHAR(64) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (changeset_hash, approved_scope_hash)
                )
                """
            )

        self._connection = psycopg.connect(
            normalized_dsn,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        try:
            self._connection.execute(f"SET search_path TO {_OWNER_SCHEMA}")
        except Exception:
            self._connection.close()
            raise

    def get(
        self,
        *,
        changeset_hash: str,
        approved_scope_hash: str,
    ) -> ApprovalAdmission | None:
        """读取 exact issuance lineage，并重新验证完整 Admission fingerprint。"""

        row = self._connection.execute(
            """
            SELECT
                admission_id,
                changeset_hash,
                approved_scope_hash,
                semantic_environment_id,
                semantic_environment_hash,
                approver,
                policy_snapshot_hash,
                policy_allowed_operations,
                approved_at,
                expires_at,
                admission_fingerprint
            FROM admission
            WHERE changeset_hash = %s AND approved_scope_hash = %s
            """,
            (changeset_hash, approved_scope_hash),
        ).fetchone()
        if row is None:
            return None
        return self._admission_from_row(row)

    def issue_or_get(self, admission: ApprovalAdmission) -> ApprovalAdmission:
        """首次发布 admission；同 fingerprint replay 返回 durable winner，冲突 authority fail closed。"""

        if not isinstance(admission, ApprovalAdmission):
            raise TypeError("admission must be ApprovalAdmission")
        self._validate_fingerprint(admission)
        environment_id, environment_hash = self._environment_parts(
            admission.semantic_environment_ref
        )

        inserted = self._connection.execute(
            """
            INSERT INTO admission (
                changeset_hash,
                approved_scope_hash,
                admission_id,
                semantic_environment_id,
                semantic_environment_hash,
                approver,
                policy_snapshot_hash,
                policy_allowed_operations,
                approved_at,
                expires_at,
                admission_fingerprint
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (changeset_hash, approved_scope_hash) DO NOTHING
            RETURNING admission_id
            """,
            (
                admission.changeset_hash,
                admission.approved_scope_hash,
                admission.admission_id,
                environment_id,
                environment_hash,
                admission.approver,
                admission.policy_snapshot_hash,
                list(admission.policy_allowed_operations),
                admission.approved_at,
                admission.expires_at,
                admission.admission_fingerprint,
            ),
        ).fetchone()
        if inserted is not None:
            return admission

        existing = self.get(
            changeset_hash=admission.changeset_hash,
            approved_scope_hash=admission.approved_scope_hash,
        )
        if existing is None:
            raise ValueError(
                f"{_INTEGRITY_INVALID}: issuance conflict did not resolve to a durable row"
            )
        if existing.admission_fingerprint == admission.admission_fingerprint:
            return existing
        raise ValueError(
            f"{_CONFLICT}: final ChangeSet/scope lineage already owns different policy authority"
        )

    def close(self) -> None:
        """幂等关闭 admission store 独占的 PostgreSQL 连接。"""

        if not self._connection.closed:
            self._connection.close()

    @staticmethod
    def _environment_parts(value: object) -> tuple[str, str]:
        """只接受仓库既有 semantic-environment stable value shape。"""

        environment_id = getattr(value, "environment_id", None)
        content_hash = getattr(value, "content_hash", None)
        if not isinstance(environment_id, str) or not environment_id.strip():
            raise ValueError(
                f"{_INTEGRITY_INVALID}: semantic environment id is invalid"
            )
        if not isinstance(content_hash, str) or not content_hash.strip():
            raise ValueError(
                f"{_INTEGRITY_INVALID}: semantic environment hash is invalid"
            )
        return environment_id.strip(), content_hash.strip()

    @staticmethod
    def _validate_fingerprint(admission: ApprovalAdmission) -> None:
        """所有写入/读取路径都只认 Gateway owner 的 canonical admission fingerprint。"""

        if compute_admission_fingerprint(admission) != admission.admission_fingerprint:
            raise ValueError(
                f"{_INTEGRITY_INVALID}: admission fingerprint does not match authority body"
            )

    @classmethod
    def _admission_from_row(cls, row: Mapping[str, object]) -> ApprovalAdmission:
        """从 durable row 重建 owner contract，并重新执行 fingerprint integrity 校验。"""

        try:
            environment = SemanticEnvironmentBinding(
                str(row["semantic_environment_id"]),
                str(row["semantic_environment_hash"]),
            )
            raw_operations = row["policy_allowed_operations"]
            if not isinstance(raw_operations, list):
                raise TypeError("policy_allowed_operations must be a PostgreSQL text array")
            admission = ApprovalAdmission(
                admission_id=row["admission_id"],
                changeset_hash=row["changeset_hash"],
                approved_scope_hash=row["approved_scope_hash"],
                semantic_environment_ref=environment,
                approver=row["approver"],
                policy_snapshot_hash=row["policy_snapshot_hash"],
                policy_allowed_operations=tuple(raw_operations),
                approved_at=row["approved_at"],
                expires_at=row["expires_at"],
                admission_fingerprint=row["admission_fingerprint"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"{_INTEGRITY_INVALID}: stored admission row is malformed"
            ) from exc
        cls._validate_fingerprint(admission)
        return admission


__all__ = ["PostgresConfiguredPolicyAdmissionStore"]
