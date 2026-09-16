"""Execution Saga V2 的 provider-neutral persistence port 与内存适配器。"""

from __future__ import annotations

from threading import RLock
from typing import Protocol

from design_gateway_authorization import AdmittedExecutionAuthorityV2

from .contracts import (
    ActualDelta,
    ReconciliationError,
    ScopeComparisonResult,
    SemanticVerificationResult,
)
from .saga_contracts_v2 import ExecutionSagaDefinitionV2
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


class ExecutionSagaStoreV2(Protocol):
    """Saga V2 独立持久边界；后端必须保持同一组 transition 语义。"""

    def create_saga(self, definition: ExecutionSagaDefinitionV2) -> StoredExecutionSagaV2: ...

    def get_saga(self, saga_id: str) -> StoredExecutionSagaV2 | None: ...

    def reserve_slice_admission(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        reserved_at: str,
    ) -> StoredExecutionSagaV2: ...

    def confirm_slice_admitted(
        self,
        saga_id: str,
        authority: AdmittedExecutionAuthorityV2,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2: ...

    def record_host_commit(
        self,
        saga_id: str,
        actual_delta: ActualDelta,
        *,
        expected_revision: int,
        committed_at: str,
    ) -> StoredExecutionSagaV2: ...

    def begin_reconciliation(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2: ...

    def record_scope_result(
        self,
        saga_id: str,
        result: ScopeComparisonResult,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2: ...

    def record_verification_result(
        self,
        saga_id: str,
        result: SemanticVerificationResult,
        *,
        expected_revision: int,
        reconciled_at: str,
    ) -> StoredExecutionSagaV2: ...

    def fail_slice_before_commit(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        failed_at: str,
    ) -> StoredExecutionSagaV2: ...

    def record_convergence_outcome(
        self,
        saga_id: str,
        outcome: SagaConvergenceOutcome,
        convergence_result_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2: ...


class InMemoryExecutionSagaStoreV2:
    """线程安全的内存适配器；业务状态转换全部委托给共享纯函数引擎。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sagas: dict[str, StoredExecutionSagaV2] = {}

    def create_saga(self, definition: ExecutionSagaDefinitionV2) -> StoredExecutionSagaV2:
        with self._lock:
            existing = self._sagas.get(getattr(definition, "saga_id", None))
            stored = create_initial_saga_v2(definition, existing=existing)
            self._sagas[definition.saga_id] = stored
            return stored

    def get_saga(self, saga_id: str) -> StoredExecutionSagaV2 | None:
        if not isinstance(saga_id, str) or not saga_id.strip():
            raise ValueError("saga_id is required")
        with self._lock:
            return self._sagas.get(saga_id.strip())

    def _get_required(self, saga_id: str) -> StoredExecutionSagaV2:
        """读取必须存在的 Saga，缺失时保持既有领域错误。"""
        stored = self._sagas.get(saga_id)
        if stored is None:
            raise ReconciliationError("SAGA_NOT_FOUND", "execution Saga V2 was not found")
        return stored

    def reserve_slice_admission(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        reserved_at: str,
    ) -> StoredExecutionSagaV2:
        with self._lock:
            stored = self._get_required(saga_id)
            updated = reserve_slice_admission_transition(
                stored,
                execution_slice_hash,
                expected_revision=expected_revision,
                reserved_at=reserved_at,
            )
            self._sagas[saga_id] = updated
            return updated

    def confirm_slice_admitted(
        self,
        saga_id: str,
        authority: AdmittedExecutionAuthorityV2,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        with self._lock:
            stored = self._get_required(saga_id)
            updated = confirm_slice_admitted_transition(
                stored,
                authority,
                expected_revision=expected_revision,
            )
            self._sagas[saga_id] = updated
            return updated

    def record_host_commit(
        self,
        saga_id: str,
        actual_delta: ActualDelta,
        *,
        expected_revision: int,
        committed_at: str,
    ) -> StoredExecutionSagaV2:
        with self._lock:
            stored = self._get_required(saga_id)
            updated = record_host_commit_transition(
                stored,
                actual_delta,
                expected_revision=expected_revision,
                committed_at=committed_at,
            )
            self._sagas[saga_id] = updated
            return updated

    def begin_reconciliation(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        with self._lock:
            stored = self._get_required(saga_id)
            updated = begin_reconciliation_transition(
                stored,
                execution_slice_hash,
                expected_revision=expected_revision,
            )
            self._sagas[saga_id] = updated
            return updated

    def record_scope_result(
        self,
        saga_id: str,
        result: ScopeComparisonResult,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        with self._lock:
            stored = self._get_required(saga_id)
            updated = record_scope_result_transition(
                stored,
                result,
                expected_revision=expected_revision,
            )
            self._sagas[saga_id] = updated
            return updated

    def record_verification_result(
        self,
        saga_id: str,
        result: SemanticVerificationResult,
        *,
        expected_revision: int,
        reconciled_at: str,
    ) -> StoredExecutionSagaV2:
        with self._lock:
            stored = self._get_required(saga_id)
            updated = record_verification_result_transition(
                stored,
                result,
                expected_revision=expected_revision,
                reconciled_at=reconciled_at,
            )
            self._sagas[saga_id] = updated
            return updated

    def fail_slice_before_commit(
        self,
        saga_id: str,
        execution_slice_hash: str,
        *,
        expected_revision: int,
        failed_at: str,
    ) -> StoredExecutionSagaV2:
        with self._lock:
            stored = self._get_required(saga_id)
            updated = fail_slice_before_commit_transition(
                stored,
                execution_slice_hash,
                expected_revision=expected_revision,
                failed_at=failed_at,
            )
            self._sagas[saga_id] = updated
            return updated

    def record_convergence_outcome(
        self,
        saga_id: str,
        outcome: SagaConvergenceOutcome,
        convergence_result_hash: str,
        *,
        expected_revision: int,
    ) -> StoredExecutionSagaV2:
        with self._lock:
            stored = self._get_required(saga_id)
            updated = record_convergence_outcome_transition(
                stored,
                outcome,
                convergence_result_hash,
                expected_revision=expected_revision,
            )
            self._sagas[saga_id] = updated
            return updated


__all__ = ["ExecutionSagaStoreV2", "InMemoryExecutionSagaStoreV2"]
