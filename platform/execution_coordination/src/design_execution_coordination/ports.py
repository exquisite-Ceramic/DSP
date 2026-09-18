"""Provider-neutral ports for Step37 execution coordination."""

from __future__ import annotations

from typing import Protocol

from design_approval_scope import ApprovalScopeBoundary, ApprovalScopeBoundaryV2
from design_changeset import CanonicalChangeSet
from design_convergence import (
    ConvergenceComparisonProfile,
    MaterializationCanonicalEvidence,
)
from design_execution_planning import (
    ExecutionSlice,
    ExecutionSliceV2,
    HostRuntimeRef,
)
from design_execution_reconciliation import (
    ActualDelta,
    SemanticVerificationResult,
    VerificationEvidenceBundle,
)
from design_gateway_authorization import (
    AdmittedExecutionAuthority,
    AdmittedExecutionAuthorityV2,
)
from design_provider_binding import ProviderBindingSetV2

from .contracts import (
    AuthorityFailure,
    HostCommitted,
    HostDispatchContext,
    HostExecutionResult,
    HostFailed,
)
from .readiness_contracts import HostReadinessReceipt


class CoordinationClock(Protocol):
    """协调器审计时间的最小抽象。"""

    def now(self) -> str: ...


class ExecutionAuthorityPort(Protocol):
    """旧 Step37 authority admission 端口。"""

    def admit(
        self,
        execution_slice: ExecutionSlice,
    ) -> AdmittedExecutionAuthority | AuthorityFailure: ...


class HostExecutionPort(Protocol):
    """旧 Step37 Host execution 端口。"""

    def execute(
        self,
        execution_slice: ExecutionSlice,
        authority: AdmittedExecutionAuthority,
    ) -> HostExecutionResult: ...


class HostExecutionRegistry(Protocol):
    """旧 Step37 Host execution registry。"""

    def resolve(self, runtime_ref: HostRuntimeRef) -> HostExecutionPort: ...


class VerificationEvidencePort(Protocol):
    """旧 Step37 semantic verification evidence 端口。"""

    def build_bundle(
        self,
        *,
        execution_slice: ExecutionSlice,
        actual_delta: ActualDelta,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundary,
    ) -> VerificationEvidenceBundle: ...


class HostReadinessPort(Protocol):
    """Host 边界内只读 readiness 检查的统一端口。"""

    def check(
        self,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
    ) -> HostReadinessReceipt: ...


class HostReadinessRegistry(Protocol):
    """按 exact HostRuntimeRef 解析 readiness 端口的注册表。"""

    def resolve(self, runtime_ref: HostRuntimeRef) -> HostReadinessPort: ...


class MaterializedHostExecutionPort(Protocol):
    """执行一个已冻结 materialization Slice 的 Host 端口。

    ``dispatch_context`` 由 Execution Saga owner 在 Host I/O 前持久化生成；Host 写入
    必须复用其中的稳定 ``idempotency_key``，不能在端口内部临时生成新的随机身份。
    """

    def execute(
        self,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
        dispatch_context: HostDispatchContext,
    ) -> HostExecutionResult: ...


class MaterializedHostExecutionRegistry(Protocol):
    """按 exact HostRuntimeRef 解析 materialized Host 执行端口。"""

    def resolve(self, runtime_ref: HostRuntimeRef) -> MaterializedHostExecutionPort: ...


class HostOutcomeProbe(Protocol):
    """Task 8 的只读 Host outcome 查询端口。

    Probe 必须使用 Task 7 已持久化的 ``HostDispatchContext`` 查询同一个 logical
    command；该端口不暴露 mutation 方法，因此 recovery 不能借 probe 偷偷重发写操作。
    """

    def resolve(
        self,
        execution_slice: ExecutionSliceV2,
        dispatch_context: HostDispatchContext,
    ) -> HostCommitted | HostFailed: ...


class ConvergenceEvidencePort(Protocol):
    """连接 Step33 本地验证证据与 Task13 canonical convergence evidence。"""

    def build_bundle(
        self,
        *,
        execution_slice: ExecutionSliceV2,
        actual_delta: ActualDelta,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundaryV2,
    ) -> VerificationEvidenceBundle: ...

    def build_evidence(
        self,
        *,
        materialization_id: str,
        execution_slice: ExecutionSliceV2,
        actual_delta: ActualDelta,
        verification_result: SemanticVerificationResult,
        verification_bundle: VerificationEvidenceBundle,
        convergence_profile: ConvergenceComparisonProfile,
    ) -> MaterializationCanonicalEvidence: ...


__all__ = [
    "ConvergenceEvidencePort",
    "CoordinationClock",
    "ExecutionAuthorityPort",
    "HostExecutionPort",
    "HostExecutionRegistry",
    "HostOutcomeProbe",
    "HostReadinessPort",
    "HostReadinessRegistry",
    "MaterializedHostExecutionPort",
    "MaterializedHostExecutionRegistry",
    "VerificationEvidencePort",
]
