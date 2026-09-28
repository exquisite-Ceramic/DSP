from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from design_convergence import (
    CrossHostConvergenceVerifier,
    build_materialization_canonical_evidence,
    compute_materialization_canonical_evidence_hash,
)
from design_execution_coordination import HostCommitted, MaterializedExecutionSagaCoordinator
from design_execution_reconciliation import (
    ExecutionReconciliationServiceV2,
    HostDispatchStatus,
    InMemoryExecutionSagaStoreV2,
    ReconciliationError,
)

from tests.execution_coordination._support import barrier, phase_i_readiness_inputs
from tests.execution_reconciliation._support import signed_bundle, signed_delta


class FixedClock:
    """为 materialized coordinator 测试提供确定性审计时间。"""

    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> str:
        """每次调用都返回同一冻结时间；identity 不得依赖 wall clock 变化。"""
        self.calls += 1
        return "2026-09-06T14:00:00Z"


class TrackingReconciliation:
    """包装真实 V2 reconciliation，并记录 Task 7 关心的 Saga 边界顺序。"""

    def __init__(self, events: list[tuple[str, object]] | None = None) -> None:
        self.service = ExecutionReconciliationServiceV2(
            store=InMemoryExecutionSagaStoreV2()
        )
        self.create_calls = 0
        self.events = events if events is not None else []

    def create_saga(self, *args, **kwargs):
        """创建真实 Saga；readiness 之前的行为仍由 production service 决定。"""
        self.create_calls += 1
        return self.service.create_saga(*args, **kwargs)

    def reserve_slice_admission(self, saga_id, execution_slice_hash, **kwargs):
        """记录 admission reservation，并委托真实 V2 service。"""
        self.events.append(("reserve_slice_admission", execution_slice_hash))
        return self.service.reserve_slice_admission(
            saga_id,
            execution_slice_hash,
            **kwargs,
        )

    def confirm_slice_admitted(self, saga_id, authority, **kwargs):
        """记录 Step32 admitted authority 已进入 Saga durable state。"""
        self.events.append(("confirm_slice_admitted", authority))
        return self.service.confirm_slice_admitted(saga_id, authority, **kwargs)

    def record_host_commit(self, saga_id, actual_delta, **kwargs):
        """记录 Host commit 被写入 Saga 的时点，便于证明 intent evidence 先于 Saga。"""
        self.events.append(("record_host_commit", actual_delta))
        return self.service.record_host_commit(saga_id, actual_delta, **kwargs)

    def __getattr__(self, name):
        """其余 Step33/Saga 行为保持完全委托给 production service。"""
        return getattr(self.service, name)


class InMemoryDispatchIntentStore:
    """测试侧最小 durable-intent fake；只模拟 Task 6 已冻结的 store 语义。

    该 fake 不替代 PostgreSQL contract。Task 6 已由真实 PostgreSQL 17 lane 验证；这里
    只用于 Task 7 coordinator ordering、lineage freeze 与 Host context threading。
    """

    def __init__(self, events: list[tuple[str, object]] | None = None) -> None:
        self.events = events if events is not None else []
        self.by_id = {}
        self.prepared_by_slice = {}

    def _store(self, intent):
        """同步主键索引和 Slice 索引，保持 fake 的单一 durable truth。"""
        self.by_id[intent.dispatch_intent_id] = intent
        self.prepared_by_slice[intent.execution_slice_hash] = intent
        return intent

    def prepare(self, intent):
        """同 Slice/同 identity replay-safe；不同 admitted lineage fail closed。"""
        self.events.append(("prepare_dispatch_intent", intent))
        existing = self.prepared_by_slice.get(intent.execution_slice_hash)
        if existing is None:
            return self._store(intent)
        if existing.dispatch_intent_id != intent.dispatch_intent_id:
            raise ReconciliationError(
                "DISPATCH_INTENT_CONFLICT",
                "test store already holds a different admitted dispatch lineage",
            )
        return existing

    def get(self, dispatch_intent_id):
        """按稳定 intent id 读取当前 fake durable 状态。"""
        return self.by_id.get(dispatch_intent_id)

    def _transition(self, dispatch_intent_id, *, expected_revision, status, event_name):
        """用严格 revision CAS 模拟 Task 6 状态推进，并记录调用顺序。"""
        current = self.by_id.get(dispatch_intent_id)
        if current is None or current.intent_revision != expected_revision:
            raise ReconciliationError(
                "DISPATCH_INTENT_CONFLICT",
                "test dispatch intent revision changed before transition",
            )
        updated = replace(
            current,
            status=status,
            intent_revision=current.intent_revision + 1,
        )
        self._store(updated)
        self.events.append((event_name, updated))
        return updated

    def mark_dispatched(self, dispatch_intent_id, *, expected_revision, observed_at):
        """记录 Host I/O 即将开始；observed_at 仅为审计输入。"""
        del observed_at
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            status=HostDispatchStatus.DISPATCHED,
            event_name="mark_dispatched",
        )

    def mark_outcome_unknown(
        self,
        dispatch_intent_id,
        *,
        expected_revision,
        failure_ref,
        observed_at,
    ):
        """模拟未知提交结果；timeout 不会被 fake 自动解释为未提交。"""
        del failure_ref, observed_at
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            status=HostDispatchStatus.OUTCOME_UNKNOWN,
            event_name="mark_outcome_unknown",
        )

    def mark_host_committed(
        self,
        dispatch_intent_id,
        *,
        expected_revision,
        evidence_hash,
        observed_at,
    ):
        """模拟 actual_delta_hash 已先作为 Host commit evidence 落到 intent store。"""
        del evidence_hash, observed_at
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            status=HostDispatchStatus.HOST_COMMITTED,
            event_name="mark_host_committed",
        )

    def mark_safe_to_retry(
        self,
        dispatch_intent_id,
        *,
        expected_revision,
        evidence_ref,
        observed_at,
    ):
        """模拟 BEFORE_COMMIT 正向证据已经允许重试。"""
        del evidence_ref, observed_at
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            status=HostDispatchStatus.SAFE_TO_RETRY,
            event_name="mark_safe_to_retry",
        )

    def mark_reconciled(
        self,
        dispatch_intent_id,
        *,
        expected_revision,
        evidence_hash,
        observed_at,
    ):
        """提供完整 Task 6 store surface；Task 8 才会真正消费 recovery reconcile。"""
        del evidence_hash, observed_at
        return self._transition(
            dispatch_intent_id,
            expected_revision=expected_revision,
            status=HostDispatchStatus.RECONCILED,
            event_name="mark_reconciled",
        )


class MaterializedHostPort:
    """记录 materialized Host 调用并返回真实测试 ActualDelta。"""

    def __init__(self, ctx, host_type: str, failure=None, events=None) -> None:
        self.ctx = ctx
        self.host_type = host_type
        self.failure = failure
        self.calls = []
        self.events = events if events is not None else []

    def execute(self, execution_slice, authority, binding_set, dispatch_context):
        """验证 Host 收到 exact binding/authority 与 durable dispatch context。"""
        self.calls.append((execution_slice, authority, binding_set, dispatch_context))
        self.events.append(("host.execute", execution_slice))
        assert execution_slice.host_runtime_ref.host_type == self.host_type
        assert binding_set.materialization_id == execution_slice.materialization_id
        assert authority.binding_set_hash == binding_set.binding_set_hash
        assert dispatch_context.execution_slice_hash == execution_slice.execution_slice_hash
        if self.failure is not None:
            return self.failure
        index = next(
            index
            for index, item in enumerate(self.ctx.execution_plan.execution_slices)
            if item.execution_slice_hash == execution_slice.execution_slice_hash
        )
        return HostCommitted(
            actual_delta=signed_delta(self.ctx, index),
            committed_at=f"2026-09-06T14:0{index + 1}:00Z",
        )


class MaterializedHostRegistry:
    """按 frozen Host type 解析测试 execution port。"""

    def __init__(self, ctx, failures=None, events=None) -> None:
        failures = dict(failures or {})
        self.ports = {
            host_type: MaterializedHostPort(
                ctx,
                host_type,
                failures.get(host_type),
                events,
            )
            for host_type in ("autocad", "revit")
        }
        self.resolutions = []

    def resolve(self, runtime_ref):
        """记录解析顺序并返回对应 Host port。"""
        self.resolutions.append(runtime_ref)
        return self.ports[runtime_ref.host_type]


class ConvergenceEvidencePort:
    """复用 production convergence builder 形成 canonical evidence。"""

    def __init__(
        self,
        ctx,
        *,
        divergent_host: str | None = None,
        bundle_failure: Exception | None = None,
    ) -> None:
        self.ctx = ctx
        self.divergent_host = divergent_host
        self.bundle_failure = bundle_failure
        self.bundle_calls = []
        self.evidence_calls = []

    def _index(self, execution_slice) -> int:
        """按 frozen execution plan 查找 Slice 的稳定测试索引。"""
        return next(
            index
            for index, item in enumerate(self.ctx.execution_plan.execution_slices)
            if item.execution_slice_hash == execution_slice.execution_slice_hash
        )

    def build_bundle(
        self,
        *,
        execution_slice,
        authority,
        binding_set,
        actual_delta,
        canonical_changeset,
        approval_scope_boundary,
    ):
        """构造与真实 Step33 约束一致的 verification bundle。"""
        assert authority.execution_slice_hash == execution_slice.execution_slice_hash
        assert authority.binding_set_hash == binding_set.binding_set_hash
        self.bundle_calls.append(execution_slice.execution_slice_hash)
        if self.bundle_failure is not None:
            raise self.bundle_failure
        assert canonical_changeset.changeset_hash == actual_delta.changeset_hash
        assert approval_scope_boundary.scope_hash == actual_delta.approved_scope_hash
        return signed_bundle(self.ctx, actual_delta, self._index(execution_slice))

    def build_evidence(
        self,
        *,
        materialization_id,
        execution_slice,
        actual_delta,
        verification_result,
        verification_bundle,
        convergence_profile,
    ):
        """构造 convergence evidence；可选注入一个确定性的 divergence。"""
        self.evidence_calls.append(materialization_id)
        evidence = build_materialization_canonical_evidence(
            materialization_id=materialization_id,
            execution_slice=execution_slice,
            actual_delta=actual_delta,
            verification_result=verification_result,
            verification_evidence_bundle=verification_bundle,
            convergence_profile=convergence_profile,
        )
        if execution_slice.host_runtime_ref.host_type != self.divergent_host:
            return evidence
        changed_field = replace(evidence.verified_fields[0], value=305.0)
        draft = replace(
            evidence,
            verified_fields=(changed_field,),
            evidence_hash="0" * 64,
        )
        return replace(
            draft,
            evidence_hash=compute_materialization_canonical_evidence_hash(draft),
        )


class TrackingConvergenceVerifier:
    """记录 convergence 调用，并委托 production verifier。"""

    def __init__(self) -> None:
        self.delegate = CrossHostConvergenceVerifier()
        self.calls = []

    def verify(self, plan, profile, evidence_set):
        """保留输入证据以供测试断言，然后调用真实 verifier。"""
        self.calls.append((plan, profile, evidence_set))
        return self.delegate.verify(plan, profile, evidence_set)


def materialized_fixture(
    *,
    readiness_statuses=None,
    host_failures=None,
    divergent_host: str | None = None,
    bundle_failure: Exception | None = None,
    dispatch_intents=None,
    events: list[tuple[str, object]] | None = None,
    record_events: bool = False,
):
    """组合 Phase I materialized 测试夹具，并允许注入 durable-intent store。

    ``record_events`` 只是显式表达测试意图；夹具始终维护事件列表，因此旧测试无需
    改造也能继续工作。
    """
    del record_events
    ctx = phase_i_readiness_inputs()
    readiness_barrier, readiness_registry, readiness_ports = barrier(readiness_statuses)
    event_log = events if events is not None else []
    reconciliation = TrackingReconciliation(event_log)
    host_registry = MaterializedHostRegistry(ctx, host_failures, event_log)
    if dispatch_intents is None:
        dispatch_intents = InMemoryDispatchIntentStore(event_log)
    evidence_port = ConvergenceEvidencePort(
        ctx,
        divergent_host=divergent_host,
        bundle_failure=bundle_failure,
    )
    convergence_verifier = TrackingConvergenceVerifier()
    clock = FixedClock()
    coordinator = MaterializedExecutionSagaCoordinator(
        readiness_barrier=readiness_barrier,
        reconciliation=reconciliation,
        host_registry=host_registry,
        dispatch_intents=dispatch_intents,
        evidence_port=evidence_port,
        convergence_verifier=convergence_verifier,
        clock=clock,
    )
    return SimpleNamespace(
        ctx=ctx,
        coordinator=coordinator,
        readiness_registry=readiness_registry,
        readiness_ports=readiness_ports,
        reconciliation=reconciliation,
        host_registry=host_registry,
        dispatch_intents=dispatch_intents,
        evidence_port=evidence_port,
        convergence_verifier=convergence_verifier,
        clock=clock,
        events=event_log,
        result_saga_id=None,
    )


def execute(fixture):
    """调用 production materialized coordinator，并把返回 Saga id 暴露给顺序断言。"""
    ctx = fixture.ctx
    result = fixture.coordinator.execute(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
        ctx.binding_sets,
        ctx.authorities,
        ctx.case.profile,
    )
    fixture.result_saga_id = result.saga_id
    return result
