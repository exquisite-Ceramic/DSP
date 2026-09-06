"""Provider-neutral ports for Step37 execution coordination."""

from __future__ import annotations

from typing import Protocol

from design_approval_scope import ApprovalScopeBoundary
from design_changeset import CanonicalChangeSet
from design_execution_planning import (
    ExecutionSlice,
    ExecutionSliceV2,
    HostRuntimeRef,
)
from design_execution_reconciliation import ActualDelta, VerificationEvidenceBundle
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


__all__ = [
    "CoordinationClock",
    "ExecutionAuthorityPort",
    "HostExecutionPort",
    "HostExecutionRegistry",
    "HostReadinessPort",
    "HostReadinessRegistry",
    "VerificationEvidencePort",
]
