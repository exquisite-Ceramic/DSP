"""Product Front Door correlation、SessionBinding 与 frozen request 的 SQLite durable owner。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from design_changeset import canonical_hash
from design_product_runtime import ProductTaskRequest

from .agent import NormalizedFreezeProposal
from .contracts import SessionBinding

_CORRELATION_CONFLICT = "FRONT_DOOR_CORRELATION_CONFLICT"
_CORRELATION_NOT_FOUND = "FRONT_DOOR_CORRELATION_NOT_FOUND"
_FREEZE_INVALID = "FRONT_DOOR_FREEZE_INVALID"
_SESSION_CONFLICT = "FRONT_DOOR_SESSION_BINDING_CONFLICT"
_STATE_INVALID = "FRONT_DOOR_SUBMISSION_STATE_INVALID"
_DELIVERY_PENDING = "DELIVERY_PENDING"


class SubmissionState(str, Enum):
    """客户端 correlation 的持久化生命周期；未冻结记录不伪造任何业务身份。"""

    UNFROZEN = "UNFROZEN"
    FROZEN = "FROZEN"


@dataclass(frozen=True, slots=True)
class FrozenSubmission:
    """一次原子 freeze 后可可靠重送的完整 client-side winner。"""

    client_submission_ref: str
    utterance: str
    proposal_hash: str
    session_binding: SessionBinding
    request: ProductTaskRequest
    delivery_state: str


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    """可表达模型调用前已落盘但尚未 freeze 的 correlation 只读投影。"""

    client_submission_ref: str
    utterance: str
    state: SubmissionState
    frozen: FrozenSubmission | None


class SessionBindingReadPort(Protocol):
    """服务器/应用 composition 只允许按 exact session_ref 读取 immutable binding。"""

    def resolve_session(self, session_ref: str) -> SessionBinding | None:
        """返回 exact binding；未知 session_ref 返回 None。"""

        ...


def _proposal_hash(proposal: NormalizedFreezeProposal) -> str:
    """只哈希 identity 生成之前已经存在的确定性 freeze 输入。"""

    return canonical_hash(
        {
            "project_id": proposal.project_id,
            "host_kind": proposal.host_kind,
            "requested_action": proposal.requested_action,
            "intent_arguments": proposal.intent_arguments,
            "candidate_key": proposal.candidate_key,
            "candidate_hash": proposal.candidate_hash,
        }
    )


def _request_payload(request: ProductTaskRequest) -> dict[str, object]:
    """把 immutable ProductTask request 投影为可持久化的完整规范 JSON body。"""

    thickness = request.intent_arguments["thickness"]
    return {
        "task_id": request.task_id,
        "project_id": request.project_id,
        "host_kind": request.host_kind,
        "session_ref": request.session_ref,
        "requested_action": request.requested_action,
        "intent_arguments": {
            "thickness": {
                "value": thickness["value"],
                "unit": thickness["unit"],
            }
        },
        "request_hash": request.request_hash,
    }


def _binding_values(binding: SessionBinding) -> tuple[str, ...]:
    """按 SQLite schema 固定顺序返回 binding authority 字段。"""

    return (
        binding.session_ref,
        binding.project_id,
        binding.host_kind,
        binding.candidate_key,
        binding.candidate_hash,
        binding.transport_locator,
        binding.host_instance_id,
        binding.document_id,
        binding.document_title,
        binding.binding_hash,
    )


def _validate_freeze_relations(
    *,
    proposal: NormalizedFreezeProposal,
    binding: SessionBinding,
    request: ProductTaskRequest,
) -> None:
    """禁止 proposal、binding 与 request 在同一原子 freeze 中形成互相矛盾的 authority。"""

    if (
        proposal.project_id != binding.project_id
        or proposal.host_kind != binding.host_kind
        or proposal.candidate_key != binding.candidate_key
        or proposal.candidate_hash != binding.candidate_hash
    ):
        raise ValueError(f"{_FREEZE_INVALID}: proposal does not match SessionBinding")
    if (
        request.project_id != proposal.project_id
        or request.host_kind != proposal.host_kind
        or request.session_ref != binding.session_ref
        or request.requested_action != proposal.requested_action
        or request.intent_arguments != proposal.intent_arguments
    ):
        raise ValueError(f"{_FREEZE_INVALID}: ProductTask request does not match freeze proposal")


class _BindingReaderMixin:
    """共享 exact SessionBinding 读取逻辑；不提供 latest/reverse lookup。"""

    _connection: sqlite3.Connection

    def resolve_session(self, session_ref: str) -> SessionBinding | None:
        """按 exact session_ref 重建并重新校验 immutable SessionBinding。"""

        normalized_ref = self._validate_nonblank(session_ref, "session_ref")
        row = self._connection.execute(
            """
            SELECT
                session_ref,
                project_id,
                host_kind,
                candidate_key,
                candidate_hash,
                transport_locator,
                host_instance_id,
                document_id,
                document_title,
                binding_hash
            FROM session_binding
            WHERE session_ref = ?
            """,
            (normalized_ref,),
        ).fetchone()
        if row is None:
            return None
        return SessionBinding(
            session_ref=row["session_ref"],
            project_id=row["project_id"],
            host_kind=row["host_kind"],
            candidate_key=row["candidate_key"],
            candidate_hash=row["candidate_hash"],
            transport_locator=row["transport_locator"],
            host_instance_id=row["host_instance_id"],
            document_id=row["document_id"],
            document_title=row["document_title"],
            binding_hash=row["binding_hash"],
        )

    @staticmethod
    def _validate_nonblank(value: object, field_name: str) -> str:
        """locator/状态字段必须是非空字符串，并只规范化外围空白。"""

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-blank string")
        return value.strip()


class SqliteFrontDoorStateStore(_BindingReaderMixin):
    """以一个 SQLite 文件持有 correlation delivery state 与 create-once SessionBinding。"""

    def __init__(self, database_path: str) -> None:
        """打开独立连接并初始化最终 Task 4 schema；foreign key 默认启用。"""

        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("database_path must be a non-blank string")
        self._database_path = database_path
        self._connection = sqlite3.connect(
            database_path,
            timeout=30.0,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """建立最终 schema，并把早期仅含 UNFROZEN correlation 的开发态表无损迁移。"""

        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_binding (
                session_ref TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                host_kind TEXT NOT NULL,
                candidate_key TEXT NOT NULL,
                candidate_hash TEXT NOT NULL,
                transport_locator TEXT NOT NULL,
                host_instance_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                document_title TEXT NOT NULL,
                binding_hash TEXT NOT NULL UNIQUE
            )
            """
        )

        existing_columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(client_submission)"
            ).fetchall()
        }
        if existing_columns and "proposal_hash" not in existing_columns:
            # Task 4 Step 1 曾只有三列开发态 schema；这里保留其 UNFROZEN correlation，
            # 不把旧记录伪造成已经冻结的业务对象。
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "ALTER TABLE client_submission RENAME TO client_submission_legacy"
                )
                self._create_submission_table()
                self._connection.execute(
                    """
                    INSERT INTO client_submission (
                        client_submission_ref,
                        utterance,
                        state
                    )
                    SELECT client_submission_ref, utterance, 'UNFROZEN'
                    FROM client_submission_legacy
                    """
                )
                self._connection.execute("DROP TABLE client_submission_legacy")
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise
        else:
            self._create_submission_table()

    def _create_submission_table(self) -> None:
        """创建 correlation + frozen outbox 表；FROZEN 行必须拥有完整 request/binding locator。"""

        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_submission (
                client_submission_ref TEXT PRIMARY KEY,
                utterance TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('UNFROZEN', 'FROZEN')),
                proposal_hash TEXT,
                session_ref TEXT,
                request_json TEXT,
                request_hash TEXT,
                delivery_state TEXT,
                FOREIGN KEY (session_ref) REFERENCES session_binding(session_ref),
                CHECK (
                    (state = 'UNFROZEN'
                        AND proposal_hash IS NULL
                        AND session_ref IS NULL
                        AND request_json IS NULL
                        AND request_hash IS NULL
                        AND delivery_state IS NULL)
                    OR
                    (state = 'FROZEN'
                        AND proposal_hash IS NOT NULL
                        AND session_ref IS NOT NULL
                        AND request_json IS NOT NULL
                        AND request_hash IS NOT NULL
                        AND delivery_state IS NOT NULL)
                )
            )
            """
        )

    def create_submission(
        self,
        client_submission_ref: str,
        utterance: str,
    ) -> SubmissionRecord:
        """模型调用前 create-once 持久化 exact correlation 与原始 utterance。"""

        normalized_ref = self._validate_nonblank(
            client_submission_ref,
            "client_submission_ref",
        )
        if not isinstance(utterance, str):
            raise TypeError("utterance must be a string")

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._submission_row(normalized_ref)
            if existing is not None:
                if existing["utterance"] != utterance:
                    raise ValueError(
                        f"{_CORRELATION_CONFLICT}: client_submission_ref already owns a different utterance"
                    )
                record = self._record_from_row(existing)
                self._connection.commit()
                return record

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
            created = self._submission_row(normalized_ref)
            if created is None:
                raise RuntimeError("created Front Door correlation could not be reloaded")
            record = self._record_from_row(created)
            self._connection.commit()
            return record
        except BaseException:
            self._connection.rollback()
            raise

    def get_submission(self, client_submission_ref: str) -> SubmissionRecord | None:
        """按 exact correlation 读取 durable 生命周期，不分配或推断业务身份。"""

        normalized_ref = self._validate_nonblank(
            client_submission_ref,
            "client_submission_ref",
        )
        row = self._submission_row(normalized_ref)
        if row is None:
            return None
        return self._record_from_row(row)

    def get_frozen_submission(
        self,
        client_submission_ref: str,
    ) -> FrozenSubmission | None:
        """只在 correlation 已原子冻结时返回完整 winner；UNFROZEN 明确返回 None。"""

        record = self.get_submission(client_submission_ref)
        if record is None or record.state is SubmissionState.UNFROZEN:
            return None
        if record.frozen is None:
            raise ValueError(f"{_STATE_INVALID}: FROZEN submission has no frozen payload")
        return record.frozen

    def freeze_submission(
        self,
        *,
        client_submission_ref: str,
        proposal: NormalizedFreezeProposal,
        binding: SessionBinding,
        request: ProductTaskRequest,
    ) -> FrozenSubmission:
        """用 BEGIN IMMEDIATE 竞争唯一 winner，并原子发布 binding + request + outbox 状态。"""

        normalized_ref = self._validate_nonblank(
            client_submission_ref,
            "client_submission_ref",
        )
        expected_proposal_hash = _proposal_hash(proposal)
        _validate_freeze_relations(
            proposal=proposal,
            binding=binding,
            request=request,
        )

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._submission_row(normalized_ref)
            if row is None:
                raise ValueError(
                    f"{_CORRELATION_NOT_FOUND}: create_submission must commit before freeze"
                )

            state = self._state_from_row(row)
            if state is SubmissionState.FROZEN:
                if row["proposal_hash"] != expected_proposal_hash:
                    raise ValueError(
                        f"{_CORRELATION_CONFLICT}: correlation already froze a different normalized proposal"
                    )
                winner = self._frozen_from_row(row)
                self._connection.commit()
                return winner

            self._insert_or_validate_binding(binding)
            request_json = json.dumps(
                _request_payload(request),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            self._connection.execute(
                """
                UPDATE client_submission
                SET
                    state = ?,
                    proposal_hash = ?,
                    session_ref = ?,
                    request_json = ?,
                    request_hash = ?,
                    delivery_state = ?
                WHERE client_submission_ref = ? AND state = ?
                """,
                (
                    SubmissionState.FROZEN.value,
                    expected_proposal_hash,
                    binding.session_ref,
                    request_json,
                    request.request_hash,
                    _DELIVERY_PENDING,
                    normalized_ref,
                    SubmissionState.UNFROZEN.value,
                ),
            )
            frozen_row = self._submission_row(normalized_ref)
            if frozen_row is None or self._state_from_row(frozen_row) is not SubmissionState.FROZEN:
                raise RuntimeError("Front Door freeze transaction did not publish a complete winner")
            winner = self._frozen_from_row(frozen_row)
            self._connection.commit()
            return winner
        except BaseException:
            self._connection.rollback()
            raise

    def mark_delivery(self, client_submission_ref: str, state: str) -> FrozenSubmission:
        """只更新 client-owned delivery 状态；绝不改写 frozen request 或 SessionBinding。"""

        normalized_ref = self._validate_nonblank(
            client_submission_ref,
            "client_submission_ref",
        )
        normalized_state = self._validate_nonblank(state, "delivery_state")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._submission_row(normalized_ref)
            if row is None:
                raise ValueError(f"{_CORRELATION_NOT_FOUND}: submission does not exist")
            if self._state_from_row(row) is not SubmissionState.FROZEN:
                raise ValueError(f"{_STATE_INVALID}: delivery state requires FROZEN submission")
            self._connection.execute(
                """
                UPDATE client_submission
                SET delivery_state = ?
                WHERE client_submission_ref = ?
                """,
                (normalized_state, normalized_ref),
            )
            updated = self._submission_row(normalized_ref)
            if updated is None:
                raise RuntimeError("updated Front Door submission could not be reloaded")
            frozen = self._frozen_from_row(updated)
            self._connection.commit()
            return frozen
        except BaseException:
            self._connection.rollback()
            raise

    def _insert_or_validate_binding(self, binding: SessionBinding) -> None:
        """SessionBinding create-once：同 session_ref 只能解析为同一 immutable body。"""

        existing = self.resolve_session(binding.session_ref)
        if existing is not None:
            if existing != binding:
                raise ValueError(
                    f"{_SESSION_CONFLICT}: session_ref already owns a different binding"
                )
            return
        self._connection.execute(
            """
            INSERT INTO session_binding (
                session_ref,
                project_id,
                host_kind,
                candidate_key,
                candidate_hash,
                transport_locator,
                host_instance_id,
                document_id,
                document_title,
                binding_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _binding_values(binding),
        )

    def _submission_row(self, client_submission_ref: str) -> sqlite3.Row | None:
        """读取完整 correlation 行；调用方负责解释生命周期。"""

        return self._connection.execute(
            """
            SELECT
                client_submission_ref,
                utterance,
                state,
                proposal_hash,
                session_ref,
                request_json,
                request_hash,
                delivery_state
            FROM client_submission
            WHERE client_submission_ref = ?
            """,
            (client_submission_ref,),
        ).fetchone()

    def _state_from_row(self, row: sqlite3.Row) -> SubmissionState:
        """把 durable state 字符串恢复成稳定枚举；未知值 fail closed。"""

        try:
            return SubmissionState(row["state"])
        except ValueError as exc:
            raise ValueError(
                f"{_STATE_INVALID}: stored submission state is not recognized"
            ) from exc

    def _record_from_row(self, row: sqlite3.Row) -> SubmissionRecord:
        """从一行 durable correlation 构造 UNFROZEN/FROZEN 统一 read model。"""

        state = self._state_from_row(row)
        frozen = None if state is SubmissionState.UNFROZEN else self._frozen_from_row(row)
        return SubmissionRecord(
            client_submission_ref=row["client_submission_ref"],
            utterance=row["utterance"],
            state=state,
            frozen=frozen,
        )

    def _frozen_from_row(self, row: sqlite3.Row) -> FrozenSubmission:
        """重建并重新执行 ProductTask/SessionBinding 自身完整性校验。"""

        required = (
            row["proposal_hash"],
            row["session_ref"],
            row["request_json"],
            row["request_hash"],
            row["delivery_state"],
        )
        if any(value is None for value in required):
            raise ValueError(f"{_STATE_INVALID}: FROZEN submission payload is incomplete")

        binding = self.resolve_session(row["session_ref"])
        if binding is None:
            raise ValueError(f"{_STATE_INVALID}: FROZEN submission binding is missing")

        try:
            request_body = json.loads(row["request_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{_STATE_INVALID}: frozen request JSON is invalid") from exc
        if not isinstance(request_body, dict):
            raise ValueError(f"{_STATE_INVALID}: frozen request JSON must be an object")
        if request_body.get("request_hash") != row["request_hash"]:
            raise ValueError(f"{_STATE_INVALID}: frozen request hash columns disagree")

        request = ProductTaskRequest(
            task_id=request_body.get("task_id"),
            project_id=request_body.get("project_id"),
            host_kind=request_body.get("host_kind"),
            session_ref=request_body.get("session_ref"),
            requested_action=request_body.get("requested_action"),
            intent_arguments=request_body.get("intent_arguments"),
            request_hash=request_body.get("request_hash"),
        )
        if request.session_ref != binding.session_ref:
            raise ValueError(f"{_STATE_INVALID}: request/session binding lineage is inconsistent")

        return FrozenSubmission(
            client_submission_ref=row["client_submission_ref"],
            utterance=row["utterance"],
            proposal_hash=row["proposal_hash"],
            session_binding=binding,
            request=request,
            delivery_state=row["delivery_state"],
        )

    def close(self) -> None:
        """关闭本 store 独占的 SQLite 连接。"""

        self._connection.close()


class SqliteSessionBindingReader(_BindingReaderMixin):
    """只暴露 SessionBinding 读取面的独立 SQLite reader；不读取 client outbox。"""

    def __init__(self, database_path: str) -> None:
        """以 read-only SQLite URI 打开现有 binding database。"""

        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("database_path must be a non-blank string")
        database_uri = f"{Path(database_path).resolve().as_uri()}?mode=ro"
        self._connection = sqlite3.connect(database_uri, uri=True)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        """关闭只读 SessionBinding 连接。"""

        self._connection.close()


__all__ = [
    "FrozenSubmission",
    "SessionBindingReadPort",
    "SqliteFrontDoorStateStore",
    "SqliteSessionBindingReader",
    "SubmissionRecord",
    "SubmissionState",
]
