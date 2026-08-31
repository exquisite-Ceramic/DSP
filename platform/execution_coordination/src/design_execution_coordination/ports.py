"""Provider-neutral ports for Step37 execution coordination."""

from __future__ import annotations

from typing import Protocol

from design_approval_scope import ApprovalScopeBoundary
from design_changeset import CanonicalChangeSet
from design_execution_planning import ExecutionSlice, HostRuntimeRef
from design_execution_reconciliation import ActualDelta, VerificationEvidenceBundle
from design_gateway_authorization import AdmittedExecutionAuthority

from .contracts import AuthorityFailure, HostExecutionResult


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


__all__ = [
    "CoordinationClock",
    "ExecutionAuthorityPort",
    "HostExecutionPort",
    "HostExecutionRegistry",
    "VerificationEvidencePort",
]
