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

from .contracts import AuthorityFailure, HostExecutionResult
from .readiness_contracts import HostReadinessReceipt


class CoordinationClock(Protocol):
    def now(self) -> str: ...


class ExecutionAuthorityPort(Protocol):
    def admit(
        self,
        execution_slice: ExecutionSlice,
    ) -> AdmittedExecutionAuthority | AuthorityFailure: ...


class HostExecutionPort(Protocol):
    def execute(
        self,
        execution_slice: ExecutionSlice,
        authority: AdmittedExecutionAuthority,
    ) -> HostExecutionResult: ...


class HostExecutionRegistry(Protocol):
    def resolve(self, runtime_ref: HostRuntimeRef) -> HostExecutionPort: ...


class VerificationEvidencePort(Protocol):
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
    """执行一个已冻结 materialization Slice 的 Host 端口。"""

    def execute(
        self,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
    ) -> HostExecutionResult: ...


class MaterializedHostExecutionRegistry(Protocol):
    """按 exact HostRuntimeRef 解析 materialized Host 执行端口。"""

    def resolve(self, runtime_ref: HostRuntimeRef) -> MaterializedHostExecutionPort: ...


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
    "HostReadinessPort",
    "HostReadinessRegistry",
    "MaterializedHostExecutionPort",
    "MaterializedHostExecutionRegistry",
    "VerificationEvidencePort",
]
