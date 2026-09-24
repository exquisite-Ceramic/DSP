"""Host dispatch intent 的公开 owner port 与内存 reference store。"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Protocol
from uuid import UUID

from .contracts import ReconciliationError
from .dispatch_intent import HostDispatchIntent, HostDispatchStatus

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _text(value: object, field_name: str) -> str:
    """规范化公开 store API 的非空文本参数。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _digest(value: object, field_name: str) -> str:
    """只接受仓库统一的小写 SHA-256 hex lineage。"""
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


def _same_admitted_lineage(
    existing: HostDispatchIntent,
    candidate: HostDispatchIntent,
) -> bool:
    """判断候选是否 replay 同一套已经冻结的 admitted execution lineage。"""
    return (
        existing.dispatch_intent_id == candidate.dispatch_intent_id
        and existing.grant_hash == candidate.grant_hash
        and existing.binding_set_hash == candidate.binding_set_hash
        and existing.host_instance_id == candidate.host_instance_id
        and existing.document_ref == candidate.document_ref
        and existing.idempotency_key == candidate.idempotency_key
    )


class HostDispatchIntentStore(Protocol):
    """Execution Saga owner 暴露给协调层的 Host dispatch intent port。"""

    def prepare(self, intent: HostDispatchIntent) -> HostDispatchIntent:
        """持久化或安全 replay 一个 PREPARED intent。"""
        ...

    def get(self, dispatch_intent_id: UUID) -> HostDispatchIntent | None:
        """按 durable intent 主键读取当前状态。"""
        ...

    def get_for_saga_slice(
        self,
        saga_id: str,
        execution_slice_hash: str,
    ) -> HostDispatchIntent | None:
        """按 exact Saga/Slice owner key 读取当前 durable intent。"""
        ...

    def mark_dispatched(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录 Host dispatch 已经开始。"""
        ...

    def mark_outcome_unknown(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        failure_ref: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录 Host effect 结果未知。"""
        ...

    def mark_host_committed(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        evidence_hash: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录 Host commit 正向证据。"""
        ...

    def mark_safe_to_retry(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        evidence_ref: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录 Host 未提交正向证据已允许 retry。"""
        ...

    def mark_reconciled(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        evidence_hash: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录 read-back/verification 已完成恢复闭环。"""
        ...


class InMemoryHostDispatchIntentStore:
    """严格复现 public port 语义的 owner-local 内存 reference store。"""

    def __init__(self) -> None:
        # 两个索引分别冻结 durable identity 与 canonical Saga/Slice owner key。
        self._items: dict[UUID, HostDispatchIntent] = {}
        self._by_slice: dict[tuple[str, str], UUID] = {}

    def prepare(self, intent: HostDispatchIntent) -> HostDispatchIntent:
        """首次保存 intent；同 lineage replay-safe，不同 admitted lineage fail closed。"""
        if not isinstance(intent, HostDispatchIntent):
            raise TypeError("intent must be HostDispatchIntent")
        if intent.status is not HostDispatchStatus.PREPARED or intent.intent_revision != 0:
            raise ValueError("new dispatch intent must be PREPARED at revision 0")

        slice_key = (intent.saga_id, intent.execution_slice_hash)
        existing_id = self._by_slice.get(slice_key)
        if existing_id is not None:
            existing = self._items[existing_id]
            if not _same_admitted_lineage(existing, intent):
                raise ReconciliationError(
                    "DISPATCH_INTENT_CONFLICT",
                    "Saga/Slice is already bound to a different admitted dispatch lineage",
                )
            return existing

        identity_collision = self._items.get(intent.dispatch_intent_id)
        if identity_collision is not None:
            raise ReconciliationError(
                "DISPATCH_INTENT_CONFLICT",
                "dispatch identity collides with a different durable Host intent",
            )

        self._items[intent.dispatch_intent_id] = intent
        self._by_slice[slice_key] = intent.dispatch_intent_id
        return intent

    def get(self, dispatch_intent_id: UUID) -> HostDispatchIntent | None:
        """按 durable intent 主键读取当前状态。"""
        if not isinstance(dispatch_intent_id, UUID):
            raise TypeError("dispatch_intent_id must be UUID")
        return self._items.get(dispatch_intent_id)

    def get_for_saga_slice(
        self,
        saga_id: str,
        execution_slice_hash: str,
    ) -> HostDispatchIntent | None:
        """按 exact Saga/Slice key 读取 intent，不解释 active/current/latest。"""
        normalized_saga_id = _text(saga_id, "saga_id")
        normalized_slice_hash = _digest(execution_slice_hash, "execution_slice_hash")
        dispatch_intent_id = self._by_slice.get(
            (normalized_saga_id, normalized_slice_hash)
        )
        if dispatch_intent_id is None:
            return None
        return self._items[dispatch_intent_id]

    def _transition(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        target_status: HostDispatchStatus,
        observed_at: str,
    ) -> HostDispatchIntent:
        """以 strict CAS 生成新的 immutable intent revision。"""
        if not isinstance(dispatch_intent_id, UUID):
            raise TypeError("dispatch_intent_id must be UUID")
        revision = _expected_revision(expected_revision)
        if not isinstance(target_status, HostDispatchStatus):
            raise TypeError("target_status must be HostDispatchStatus")
        _text(observed_at, "observed_at")

        existing = self._items.get(dispatch_intent_id)
        if existing is None or existing.intent_revision != revision:
            raise ReconciliationError(
                "DISPATCH_INTENT_CONFLICT",
                "dispatch intent revision changed before durable transition commit",
            )

        updated = replace(
            existing,
            status=target_status,
            intent_revision=existing.intent_revision + 1,
        )
        self._items[dispatch_intent_id] = updated
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
        """记录响应缺失等未知结果；不能据此推断 Host 未提交。"""
        _text(failure_ref, "failure_ref")
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            target_status=HostDispatchStatus.OUTCOME_UNKNOWN,
            observed_at=observed_at,
        )

    def mark_host_committed(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        evidence_hash: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录已经获得 Host commit 正向证据。"""
        _digest(evidence_hash, "evidence_hash")
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            target_status=HostDispatchStatus.HOST_COMMITTED,
            observed_at=observed_at,
        )

    def mark_safe_to_retry(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        evidence_ref: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录已有 Host 未提交正向证据，因此允许 retry。"""
        _text(evidence_ref, "evidence_ref")
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            target_status=HostDispatchStatus.SAFE_TO_RETRY,
            observed_at=observed_at,
        )

    def mark_reconciled(
        self,
        dispatch_intent_id: UUID,
        *,
        expected_revision: int,
        evidence_hash: str,
        observed_at: str,
    ) -> HostDispatchIntent:
        """记录 read-back/verification evidence 已完成恢复闭环。"""
        _digest(evidence_hash, "evidence_hash")
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            target_status=HostDispatchStatus.RECONCILED,
            observed_at=observed_at,
        )


__all__ = [
    "HostDispatchIntentStore",
    "InMemoryHostDispatchIntentStore",
]
