"""Public Task10 Saga Store Protocol."""

from __future__ import annotations

from typing import Protocol

from .compensation import CompensationExecutionRef, CompensationProposal
from .saga_state import StoredExecutionSaga
from .store import ExecutionSagaStore as _Task9ExecutionSagaStore


class ExecutionSagaStore(_Task9ExecutionSagaStore, Protocol):
    def fail_slice_before_commit(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        failed_at: str,
    ) -> StoredExecutionSaga: ...

    def begin_compensation(
        self,
        saga_id: str,
        proposal: CompensationProposal,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga: ...

    def record_compensation_result(
        self,
        saga_id: str,
        execution_ref: CompensationExecutionRef,
        *,
        expected_revision: int,
    ) -> StoredExecutionSaga: ...


__all__ = ["ExecutionSagaStore"]
