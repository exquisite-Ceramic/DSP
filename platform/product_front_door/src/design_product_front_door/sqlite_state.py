"""Product Front Door 客户端 correlation 的 SQLite durable owner。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum

_CORRELATION_CONFLICT = "FRONT_DOOR_CORRELATION_CONFLICT"
_STATE_INVALID = "FRONT_DOOR_SUBMISSION_STATE_INVALID"


class SubmissionState(str, Enum):
    """客户端 correlation 的持久化生命周期；冻结前不伪造任何业务身份。"""

    UNFROZEN = "UNFROZEN"
    FROZEN = "FROZEN"


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    """correlation 的只读生命周期投影；UNFROZEN 时只包含原始 utterance。"""

    client_submission_ref: str
    utterance: str
    state: SubmissionState
    frozen: object | None


class SqliteFrontDoorStateStore:
    """以单个 SQLite 文件持久化 Front Door correlation 生命周期。"""

    def __init__(self, database_path: str) -> None:
        """打开独立 SQLite 连接并初始化 correlation owner schema。"""

        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("database_path must be a non-blank string")
        self._connection = sqlite3.connect(database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_submission (
                client_submission_ref TEXT PRIMARY KEY,
                utterance TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('UNFROZEN', 'FROZEN'))
            )
            """
        )
        self._connection.commit()

    def create_submission(
        self,
        client_submission_ref: str,
        utterance: str,
    ) -> SubmissionRecord:
        """模型调用前 create-once 持久化 exact correlation 与原始 utterance。"""

        normalized_ref = self._validate_ref(client_submission_ref)
        if not isinstance(utterance, str):
            raise TypeError("utterance must be a string")

        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO client_submission (
                        client_submission_ref,
                        utterance,
                        state
                    )
                    VALUES (?, ?, ?)
                    """,
                    (normalized_ref, utterance, SubmissionState.UNFROZEN.value),
                )
        except sqlite3.IntegrityError:
            existing = self.get_submission(normalized_ref)
            if existing is None:
                raise
            if existing.utterance != utterance:
                raise ValueError(
                    f"{_CORRELATION_CONFLICT}: client_submission_ref already owns a different utterance"
                ) from None
            return existing

        created = self.get_submission(normalized_ref)
        if created is None:
            raise RuntimeError("created Front Door correlation could not be reloaded")
        return created

    def get_submission(self, client_submission_ref: str) -> SubmissionRecord | None:
        """按 exact correlation 读取 durable 生命周期，不分配或推断业务身份。"""

        normalized_ref = self._validate_ref(client_submission_ref)
        row = self._connection.execute(
            """
            SELECT client_submission_ref, utterance, state
            FROM client_submission
            WHERE client_submission_ref = ?
            """,
            (normalized_ref,),
        ).fetchone()
        if row is None:
            return None

        try:
            state = SubmissionState(row["state"])
        except ValueError as exc:
            raise ValueError(
                f"{_STATE_INVALID}: stored submission state is not recognized"
            ) from exc

        # Step 1 仅存在 UNFROZEN correlation；后续 Task 4 freeze 小步会把这里扩展为
        # 从同一事务读取 FrozenSubmission，而不会在冻结前发明 task/session/proposal 字段。
        if state is SubmissionState.FROZEN:
            raise ValueError(
                f"{_STATE_INVALID}: frozen submission payload is not implemented yet"
            )
        return SubmissionRecord(
            client_submission_ref=row["client_submission_ref"],
            utterance=row["utterance"],
            state=state,
            frozen=None,
        )

    def get_frozen_submission(self, client_submission_ref: str) -> None:
        """冻结语义尚未进入当前 TDD 小步；UNFROZEN correlation 明确返回 None。"""

        record = self.get_submission(client_submission_ref)
        if record is None or record.state is SubmissionState.UNFROZEN:
            return None
        raise ValueError(f"{_STATE_INVALID}: frozen submission payload is not implemented yet")

    def close(self) -> None:
        """幂等关闭本 store 独占的 SQLite 连接。"""

        self._connection.close()

    @staticmethod
    def _validate_ref(client_submission_ref: str) -> str:
        """correlation locator 必须是非空字符串；只规范化外围空白，不改变 utterance。"""

        if not isinstance(client_submission_ref, str) or not client_submission_ref.strip():
            raise ValueError("client_submission_ref must be a non-blank string")
        return client_submission_ref.strip()


__all__ = [
    "SqliteFrontDoorStateStore",
    "SubmissionRecord",
    "SubmissionState",
]
