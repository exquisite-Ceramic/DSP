"""Task 8：基于 durable evidence 恢复未知 Host outcome。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from design_approval_scope import ApprovalScopeBoundaryV2
from design_changeset import CanonicalChangeSet
from design_execution_planning import ExecutionSliceV2
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    HostDispatchIntent,
    HostDispatchStatus,
    ScopeComparisonStatus,
    SliceReconciliationStatusV2,
    StoredExecutionSagaV2,
    VerificationStatus,
    validate_actual_delta_integrity,
)
from design_gateway_authorization import AdmittedExecutionAuthorityV2
from design_provider_binding import ProviderBindingSetV2

from .contracts import (
    CoordinationError,
    HostCommitted,
    HostDispatchContext,
    HostFailed,
    HostFailurePhase,
)
from .materialized_contracts import (
    MaterializedCoordinationResult,
    MaterializedCoordinationStatus,
)

if TYPE_CHECKING:
    from .ports import HostOutcomeProbe


_TERMINAL_STATUS_MAP = {
    ExecutionSagaStatusV2.SUCCEEDED: MaterializedCoordinationStatus.SUCCEEDED,
    ExecutionSagaStatusV2.FAILED: MaterializedCoordinationStatus.FAILED,
    ExecutionSagaStatusV2.PARTIALLY_COMMITTED: (
        MaterializedCoordinationStatus.PARTIALLY_COMMITTED
    ),
    ExecutionSagaStatusV2.DIVERGED: MaterializedCoordinationStatus.DIVERGED,
}


def _error(code: str, message: str) -> None:
    """统一抛出带稳定机器码的 recovery 边界错误。"""
    raise CoordinationError(code, message)


def _slice_state(stored_saga: StoredExecutionSagaV2, execution_slice_hash: str):
    """从 durable Saga 中解析且仅解析一个 exact Slice state。"""
    matches = tuple(
        state
        for state in stored_saga.slice_states
        if state.execution_slice_hash == execution_slice_hash
    )
    if len(matches) != 1:
        _error("SAGA_INTEGRITY_INVALID", "recovery Slice is not uniquely present in Saga")
    return matches[0]


def _assigned_tasks(stored_saga, canonical_changeset, execution_slice_hash: str):
    """读取既有 Saga definition 冻结的 validation task 分配，不创建 recovery 专用规则。"""
    assignments = tuple(
        item
        for item in stored_saga.definition.slice_validation_assignments
        if item.execution_slice_hash == execution_slice_hash
    )
    if len(assignments) != 1:
        _error("SAGA_INTEGRITY_INVALID", "recovery validation assignment is unresolved")
    tasks = {
        item.validation_task_id: item for item in canonical_changeset.validation_tasks
    }
    try:
        return tuple(tasks[task_id] for task_id in assignments[0].validation_task_ids)
    except KeyError as exc:
        _error(
            "SAGA_INTEGRITY_INVALID",
            f"recovery assignment references unknown task {exc.args[0]}",
        )


def _project_result(
    stored_saga: StoredExecutionSagaV2,
    *,
    execution_slice_hash: str | None = None,
    failure_ref: str | None = None,
) -> MaterializedCoordinationResult:
    """把 durable Saga truth 投影为既有 materialized coordination result。"""
    terminal = _TERMINAL_STATUS_MAP.get(stored_saga.status)
    if terminal is not None:
        return MaterializedCoordinationResult(
            saga_id=stored_saga.definition.saga_id,
            saga_revision=stored_saga.saga_revision,
            status=terminal,
            active_slice_hash=None,
            failure_ref=failure_ref,
            convergence_result_hash=stored_saga.convergence_result_hash,
        )

    # Task 8 只收口当前 Slice 的 unknown outcome；后续 Slice 或 convergence 仍由原
    # materialized coordinator 驱动，因此这里明确保持 RECOVERY_REQUIRED，而不伪造
    # “整个 Saga 已成功”的结论。
    if execution_slice_hash is None:
        failure_ref = failure_ref or "MATERIALIZED_FORWARD_RESUME_REQUIRES_EVIDENCE"
    return MaterializedCoordinationResult(
        saga_id=stored_saga.definition.saga_id,
        saga_revision=stored_saga.saga_revision,
        status=MaterializedCoordinationStatus.RECOVERY_REQUIRED,
        active_slice_hash=execution_slice_hash,
        failure_ref=failure_ref,
        convergence_result_hash=stored_saga.convergence_result_hash,
    )


class UnknownOutcomeRecovery:
    """只通过 durable intent + Host probe evidence 收口 unknown outcome。

    该服务故意不接收 Host mutation port，因此 recovery 路径在结构上无法重新发写命令。
    当 commitment 被证明后，所有 scope/semantic 判断仍调用现有 Step33 V2 service。
    """

    def __init__(
        self,
        *,
        reconciliation,
        dispatch_intents,
        outcome_probe: HostOutcomeProbe,
        evidence_port,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundaryV2,
        clock,
    ) -> None:
        """冻结恢复所需 owner-local store、只读 probe 与原有 Step33 依赖。"""
        for name, value, method in (
            ("reconciliation", reconciliation, "get_saga"),
            ("dispatch_intents", dispatch_intents, "get"),
            ("outcome_probe", outcome_probe, "resolve"),
            ("evidence_port", evidence_port, "build_bundle"),
            ("clock", clock, "now"),
        ):
            if value is None or not callable(getattr(value, method, None)):
                raise TypeError(f"{name} must provide {method}")
        for method in (
            "record_host_commit",
            "begin_reconciliation",
            "compare_scope",
            "record_scope_result",
            "verify_semantics",
            "record_verification_result",
        ):
            if not callable(getattr(reconciliation, method, None)):
                raise TypeError(f"reconciliation must provide {method}")
        for method in ("mark_host_committed", "mark_safe_to_retry", "mark_reconciled"):
            if not callable(getattr(dispatch_intents, method, None)):
                raise TypeError(f"dispatch_intents must provide {method}")
        if not isinstance(canonical_changeset, CanonicalChangeSet):
            raise TypeError("canonical_changeset must be CanonicalChangeSet")
        if not isinstance(approval_scope_boundary, ApprovalScopeBoundaryV2):
            raise TypeError("approval_scope_boundary must be ApprovalScopeBoundaryV2")

        self._reconciliation = reconciliation
        self._dispatch_intents = dispatch_intents
        self._outcome_probe = outcome_probe
        self._evidence_port = evidence_port
        self._canonical_changeset = canonical_changeset
        self._approval_scope_boundary = approval_scope_boundary
        self._clock = clock

    def _load_durable_truth(
        self,
        stored_saga: StoredExecutionSagaV2,
        dispatch_intent: HostDispatchIntent,
    ) -> tuple[StoredExecutionSagaV2, HostDispatchIntent]:
        """先重读两个 durable owner truth；调用方传入快照本身不能替代持久状态。"""
        if not isinstance(stored_saga, StoredExecutionSagaV2):
            raise TypeError("stored_saga must be StoredExecutionSagaV2")
        if not isinstance(dispatch_intent, HostDispatchIntent):
            raise TypeError("dispatch_intent must be HostDispatchIntent")

        durable_intent = self._dispatch_intents.get(dispatch_intent.dispatch_intent_id)
        if durable_intent is None:
            _error(
                "DISPATCH_INTENT_MISSING",
                "unknown-outcome recovery requires an existing durable dispatch intent",
            )
        durable_saga = self._reconciliation.get_saga(stored_saga.definition.saga_id)
        if durable_saga is None:
            _error("SAGA_INTEGRITY_INVALID", "recovery Saga durable state is missing")
        if durable_saga.definition != stored_saga.definition:
            _error("SAGA_INTEGRITY_INVALID", "recovery Saga definition changed")
        return durable_saga, durable_intent

    @staticmethod
    def _validate_lineage(
        *,
        stored_saga: StoredExecutionSagaV2,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
        dispatch_intent: HostDispatchIntent,
    ) -> None:
        """要求 recovery probe 精确复用 Task 7 已冻结 admitted dispatch lineage。"""
        if not isinstance(execution_slice, ExecutionSliceV2):
            raise TypeError("execution_slice must be ExecutionSliceV2")
        if not isinstance(authority, AdmittedExecutionAuthorityV2):
            raise TypeError("authority must be AdmittedExecutionAuthorityV2")
        if not isinstance(binding_set, ProviderBindingSetV2):
            raise TypeError("binding_set must be ProviderBindingSetV2")

        state = _slice_state(stored_saga, execution_slice.execution_slice_hash)
        if (
            dispatch_intent.saga_id != stored_saga.definition.saga_id
            or dispatch_intent.execution_slice_hash
            != execution_slice.execution_slice_hash
            or dispatch_intent.grant_hash != authority.grant_hash
            or dispatch_intent.binding_set_hash != binding_set.binding_set_hash
            or dispatch_intent.host_instance_id != authority.host_instance_id
            or dispatch_intent.document_ref
            != execution_slice.host_runtime_ref.document_ref
            or authority.execution_slice_hash != execution_slice.execution_slice_hash
            or authority.binding_set_hash != binding_set.binding_set_hash
            or state.grant_hash != authority.grant_hash
            or state.binding_set_hash != binding_set.binding_set_hash
        ):
            _error(
                "DISPATCH_INTENT_CONFLICT",
                "recovery inputs do not match the admitted durable dispatch lineage",
            )

    @staticmethod
    def _dispatch_context(intent: HostDispatchIntent) -> HostDispatchContext:
        """从 durable intent 恢复同一 logical command 的稳定查询身份。"""
        return HostDispatchContext(
            dispatch_intent_id=str(intent.dispatch_intent_id),
            idempotency_key=str(intent.idempotency_key),
            saga_id=intent.saga_id,
            execution_slice_hash=intent.execution_slice_hash,
        )

    def _finish_reconciliation(
        self,
        *,
        stored_saga: StoredExecutionSagaV2,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        intent: HostDispatchIntent,
        host_result: HostCommitted,
    ) -> MaterializedCoordinationResult:
        """把 recovered ActualDelta 送回原 Step33 V2 scope/verify/reconcile 链。"""
        actual_delta = host_result.actual_delta
        validate_actual_delta_integrity(actual_delta)

        # intent 的 Host commit observation 必须早于 Saga commit；若 Task 7 已经持久化过
        # HOST_COMMITTED，则保留原 revision，不重复追加 observation。
        if intent.status is HostDispatchStatus.OUTCOME_UNKNOWN:
            intent = self._dispatch_intents.mark_host_committed(
                intent.dispatch_intent_id,
                expected_revision=intent.intent_revision,
                evidence_hash=actual_delta.actual_delta_hash,
                observed_at=host_result.committed_at,
            )
        elif intent.status is not HostDispatchStatus.HOST_COMMITTED:
            _error(
                "RECOVERY_INTENT_STATE_INVALID",
                f"commit recovery is invalid from dispatch state {intent.status.value}",
            )

        # record_host_commit 本身支持相同 evidence replay；这同时覆盖“intent 已提交、Saga
        # 尚未记录 commit”的崩溃窗口，并让 owner store 负责 exact lineage 校验。
        stored_saga = self._reconciliation.record_host_commit(
            stored_saga.definition.saga_id,
            actual_delta,
            expected_revision=stored_saga.saga_revision,
            committed_at=host_result.committed_at,
        )
        state = _slice_state(stored_saga, execution_slice.execution_slice_hash)

        # 若 Saga 本地 reconciliation 已在此前崩溃窗口完成，只缺 intent RECONCILED，
        # 直接用 durable verification/scope hash 收口，绝不再次 probe 或 mutation。
        if state.status is SliceReconciliationStatusV2.SUCCEEDED:
            if state.verification_hash is None:
                _error("SAGA_INTEGRITY_INVALID", "succeeded Slice lacks verification hash")
            self._dispatch_intents.mark_reconciled(
                intent.dispatch_intent_id,
                expected_revision=intent.intent_revision,
                evidence_hash=state.verification_hash,
                observed_at=self._clock.now(),
            )
            return _project_result(stored_saga)
        if state.status in {
            SliceReconciliationStatusV2.SCOPE_BREACH,
            SliceReconciliationStatusV2.VERIFY_FAILED,
        }:
            evidence_hash = state.verification_hash or state.scope_comparison_hash
            if evidence_hash is None:
                _error("SAGA_INTEGRITY_INVALID", "terminal Slice lacks recovery evidence")
            self._dispatch_intents.mark_reconciled(
                intent.dispatch_intent_id,
                expected_revision=intent.intent_revision,
                evidence_hash=evidence_hash,
                observed_at=self._clock.now(),
            )
            return _project_result(stored_saga, failure_ref=evidence_hash)

        stored_saga = self._reconciliation.begin_reconciliation(
            stored_saga.definition.saga_id,
            execution_slice.execution_slice_hash,
            expected_revision=stored_saga.saga_revision,
        )
        scope_result = self._reconciliation.compare_scope(
            canonical_changeset=self._canonical_changeset,
            approval_scope_boundary=self._approval_scope_boundary,
            execution_slice=execution_slice,
            authority=authority,
            actual_delta=actual_delta,
        )
        stored_saga = self._reconciliation.record_scope_result(
            stored_saga.definition.saga_id,
            scope_result,
            expected_revision=stored_saga.saga_revision,
        )
        if scope_result.status is not ScopeComparisonStatus.WITHIN_SCOPE:
            intent = self._dispatch_intents.mark_reconciled(
                intent.dispatch_intent_id,
                expected_revision=intent.intent_revision,
                evidence_hash=scope_result.comparison_hash,
                observed_at=self._clock.now(),
            )
            return _project_result(
                stored_saga,
                failure_ref=scope_result.comparison_hash,
            )

        verification_bundle = self._evidence_port.build_bundle(
            execution_slice=execution_slice,
            actual_delta=actual_delta,
            canonical_changeset=self._canonical_changeset,
            approval_scope_boundary=self._approval_scope_boundary,
        )
        verification = self._reconciliation.verify_semantics(
            canonical_changeset=self._canonical_changeset,
            approval_scope_boundary=self._approval_scope_boundary,
            execution_slice=execution_slice,
            authority=authority,
            actual_delta=actual_delta,
            validation_tasks=_assigned_tasks(
                stored_saga,
                self._canonical_changeset,
                execution_slice.execution_slice_hash,
            ),
            verification_evidence_bundle=verification_bundle,
            verified_at=self._clock.now(),
        )
        stored_saga = self._reconciliation.record_verification_result(
            stored_saga.definition.saga_id,
            verification,
            expected_revision=stored_saga.saga_revision,
            reconciled_at=self._clock.now(),
        )
        self._dispatch_intents.mark_reconciled(
            intent.dispatch_intent_id,
            expected_revision=intent.intent_revision,
            evidence_hash=verification.verification_hash,
            observed_at=self._clock.now(),
        )
        if verification.status is not VerificationStatus.PASSED:
            return _project_result(
                stored_saga,
                failure_ref=verification.verification_hash,
            )
        return _project_result(stored_saga)

    def recover(
        self,
        *,
        stored_saga: StoredExecutionSagaV2,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
        dispatch_intent: HostDispatchIntent,
    ) -> MaterializedCoordinationResult:
        """依据 Host proof 收口 unknown outcome，永不盲目重新发 Host mutation。"""
        stored_saga, intent = self._load_durable_truth(stored_saga, dispatch_intent)
        self._validate_lineage(
            stored_saga=stored_saga,
            execution_slice=execution_slice,
            authority=authority,
            binding_set=binding_set,
            dispatch_intent=intent,
        )

        # fully reconciled 是 recovery 的幂等终点：直接投影 durable truth，不再触碰 Host。
        if intent.status is HostDispatchStatus.RECONCILED:
            return _project_result(stored_saga)
        if intent.status is HostDispatchStatus.SAFE_TO_RETRY:
            return _project_result(
                stored_saga,
                execution_slice_hash=execution_slice.execution_slice_hash,
                failure_ref="HOST_SAFE_TO_RETRY",
            )
        if intent.status not in {
            HostDispatchStatus.OUTCOME_UNKNOWN,
            HostDispatchStatus.HOST_COMMITTED,
        }:
            _error(
                "RECOVERY_INTENT_STATE_INVALID",
                f"unknown-outcome recovery cannot start from {intent.status.value}",
            )

        host_result = self._outcome_probe.resolve(
            execution_slice,
            self._dispatch_context(intent),
        )
        if isinstance(host_result, HostCommitted):
            return self._finish_reconciliation(
                stored_saga=stored_saga,
                execution_slice=execution_slice,
                authority=authority,
                intent=intent,
                host_result=host_result,
            )
        if not isinstance(host_result, HostFailed):
            _error("HOST_RESULT_INVALID", "Host outcome probe returned an invalid result")

        if host_result.phase is HostFailurePhase.BEFORE_COMMIT:
            if intent.status is HostDispatchStatus.HOST_COMMITTED:
                _error(
                    "HOST_RECOVERY_EVIDENCE_CONFLICT",
                    "Host cannot be downgraded from durable committed evidence",
                )
            self._dispatch_intents.mark_safe_to_retry(
                intent.dispatch_intent_id,
                expected_revision=intent.intent_revision,
                evidence_ref=host_result.failure_ref,
                observed_at=host_result.failed_at,
            )
            return _project_result(
                stored_saga,
                execution_slice_hash=execution_slice.execution_slice_hash,
                failure_ref=host_result.failure_ref,
            )

        if host_result.phase is HostFailurePhase.COMMIT_STATE_UNKNOWN:
            # probe 仍然不充分时不追加同义 OUTCOME_UNKNOWN observation，避免每次人工恢复
            # 都无意义增加 revision；durable unknown truth 保持原样。
            return _project_result(
                stored_saga,
                execution_slice_hash=execution_slice.execution_slice_hash,
                failure_ref=host_result.failure_ref,
            )
        _error("HOST_RESULT_INVALID", "unsupported Host recovery failure phase")


__all__ = ["UnknownOutcomeRecovery"]
