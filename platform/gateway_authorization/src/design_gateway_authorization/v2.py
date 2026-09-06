"""Phase I 面向 materialization 的 Step32 V2 Gateway 授权。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from design_approval_scope import (
    ApprovalScopeBoundaryV2,
    ApprovalScopeError,
    validate_approval_scope_boundary_v2,
)
from design_changeset import (
    CanonicalChangeSet,
    ChangeSetError,
    canonical_hash,
    validate_changeset_integrity_v2,
)
from design_execution_planning import (
    ExecutionPlanningError,
    ExecutionPlanV2,
    ExecutionSliceV2,
    validate_execution_plan_v2,
)
from design_materialization_planning import MaterializationPlan
from design_materialization_topology import MaterializationTopologySnapshot
from design_provider_binding import (
    ProviderBindingError,
    ProviderBindingSetV2,
    validate_provider_binding_set_v2,
)

from .contracts import (
    ApprovalAdmission,
    ApprovalRecord,
    ApprovalState,
    GatewayAuthorizationError,
    _digest,
    _text,
    _texts,
    _utc_timestamp,
)
from .hashing import (
    compute_admission_fingerprint,
    compute_approval_hash,
)


def _error(
    code: str,
    message: str,
    *,
    upstream_code: str | None = None,
) -> None:
    """统一抛出带可选上游错误码的 Step32 V2 领域错误。"""
    raise GatewayAuthorizationError(
        code,
        message,
        upstream_code=upstream_code,
    )


def _parse_utc(value: str) -> datetime:
    """把已规范化 UTC 时间解析为可比较的 datetime。"""
    raw = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(raw)


@dataclass(frozen=True, slots=True)
class ApprovalConsumptionRequestV2:
    """Step32 V2 审批消费的 exact BoundaryV2 请求。"""

    admission: ApprovalAdmission
    canonical_changeset: CanonicalChangeSet
    approval_scope_boundary: ApprovalScopeBoundaryV2
    consumed_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.admission, ApprovalAdmission):
            raise TypeError("admission must be ApprovalAdmission")
        if not isinstance(self.canonical_changeset, CanonicalChangeSet):
            raise TypeError("canonical_changeset must be CanonicalChangeSet")
        if not isinstance(self.approval_scope_boundary, ApprovalScopeBoundaryV2):
            raise TypeError(
                "approval_scope_boundary must be ApprovalScopeBoundaryV2"
            )
        object.__setattr__(
            self,
            "consumed_at",
            _utc_timestamp(self.consumed_at, "consumed_at"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionGrantRequestV2:
    """一个 REQUIRED materialization grant 的完整 owner-validation 证据。"""

    approval_id: str
    execution_plan: ExecutionPlanV2
    execution_slice: ExecutionSliceV2
    provider_binding_set: ProviderBindingSetV2
    materialization_plan: MaterializationPlan
    topology_snapshot: MaterializationTopologySnapshot
    approval_scope_boundary: ApprovalScopeBoundaryV2
    issued_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", _text(self.approval_id, "approval_id"))
        if not isinstance(self.execution_plan, ExecutionPlanV2):
            raise TypeError("execution_plan must be ExecutionPlanV2")
        if not isinstance(self.execution_slice, ExecutionSliceV2):
            raise TypeError("execution_slice must be ExecutionSliceV2")
        if not isinstance(self.provider_binding_set, ProviderBindingSetV2):
            raise TypeError("provider_binding_set must be ProviderBindingSetV2")
        if not isinstance(self.materialization_plan, MaterializationPlan):
            raise TypeError("materialization_plan must be MaterializationPlan")
        if not isinstance(self.topology_snapshot, MaterializationTopologySnapshot):
            raise TypeError("topology_snapshot must be MaterializationTopologySnapshot")
        if not isinstance(self.approval_scope_boundary, ApprovalScopeBoundaryV2):
            raise TypeError(
                "approval_scope_boundary must be ApprovalScopeBoundaryV2"
            )
        object.__setattr__(
            self,
            "issued_at",
            _utc_timestamp(self.issued_at, "issued_at"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionGrantV2:
    """授权一个精确 REQUIRED materialization 执行的不可变 grant。"""

    grant_id: str
    approval_id: str
    approval_hash: str
    changeset_hash: str
    approved_scope_hash: str
    materialization_plan_hash: str
    materialization_id: str
    execution_slice_id: str
    execution_slice_hash: str
    binding_set_hash: str
    host_instance_id: str
    allowed_operations: tuple[str, ...]
    issued_at: str
    expires_at: str
    grant_hash: str

    def __post_init__(self) -> None:
        for name in (
            "grant_id",
            "approval_id",
            "materialization_id",
            "execution_slice_id",
            "host_instance_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "approval_hash",
            "changeset_hash",
            "approved_scope_hash",
            "materialization_plan_hash",
            "execution_slice_hash",
            "binding_set_hash",
            "grant_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "allowed_operations",
            _texts(self.allowed_operations, "allowed_operation", required=True),
        )
        object.__setattr__(self, "issued_at", _utc_timestamp(self.issued_at, "issued_at"))
        object.__setattr__(
            self,
            "expires_at",
            _utc_timestamp(self.expires_at, "expires_at"),
        )


@dataclass(frozen=True, slots=True)
class AdmittedExecutionAuthorityV2:
    """Host 执行前已 admission 的精确 materialization authority。"""

    approval_hash: str
    grant_hash: str
    changeset_hash: str
    approved_scope_hash: str
    materialization_plan_hash: str
    materialization_id: str
    execution_slice_hash: str
    binding_set_hash: str
    host_instance_id: str
    admitted_at: str

    def __post_init__(self) -> None:
        for name in (
            "approval_hash",
            "grant_hash",
            "changeset_hash",
            "approved_scope_hash",
            "materialization_plan_hash",
            "execution_slice_hash",
            "binding_set_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "materialization_id",
            _text(self.materialization_id, "materialization_id"),
        )
        object.__setattr__(
            self,
            "host_instance_id",
            _text(self.host_instance_id, "host_instance_id"),
        )
        object.__setattr__(
            self,
            "admitted_at",
            _utc_timestamp(self.admitted_at, "admitted_at"),
        )


def compute_grant_hash_v2(
    *,
    approval_hash: str,
    changeset_hash: str,
    approved_scope_hash: str,
    materialization_plan_hash: str,
    materialization_id: str,
    execution_slice_hash: str,
    binding_set_hash: str,
    host_instance_id: str,
    allowed_operations,
    issued_at: str,
    expires_at: str,
) -> str:
    """计算 Step32 V2 自己拥有的 materialization-aware grant hash。"""
    return canonical_hash(
        {
            "version": "EXECUTION_GRANT_V2",
            "approval_hash": _digest(approval_hash, "approval_hash"),
            "changeset_hash": _digest(changeset_hash, "changeset_hash"),
            "approved_scope_hash": _digest(
                approved_scope_hash,
                "approved_scope_hash",
            ),
            "materialization_plan_hash": _digest(
                materialization_plan_hash,
                "materialization_plan_hash",
            ),
            "materialization_id": _text(materialization_id, "materialization_id"),
            "execution_slice_hash": _digest(
                execution_slice_hash,
                "execution_slice_hash",
            ),
            "binding_set_hash": _digest(binding_set_hash, "binding_set_hash"),
            "host_instance_id": _text(host_instance_id, "host_instance_id"),
            "allowed_operations": list(
                _texts(allowed_operations, "allowed_operation", required=True)
            ),
            "issued_at": _utc_timestamp(issued_at, "issued_at"),
            "expires_at": _utc_timestamp(expires_at, "expires_at"),
        }
    )


class GatewayAuthorizationServiceV2:
    """只对 exact V2 materialization lineage 发放与 admission 执行权限。"""

    def __init__(self, store) -> None:
        required = (
            "consume_admission_once",
            "get_approval",
            "issue_or_get_grant_v2",
            "admit_grant_v2",
        )
        if store is None or any(
            not callable(getattr(store, name, None)) for name in required
        ):
            raise TypeError("store must provide the Step32 V2 authorization boundary")
        self._store = store

    def consume_approval(
        self,
        request: ApprovalConsumptionRequestV2,
    ) -> ApprovalRecord:
        """消费 exact BoundaryV2 approval，并复用既有 ApprovalRecord 持久形状。"""
        if not isinstance(request, ApprovalConsumptionRequestV2):
            _error(
                "APPROVAL_INPUT_INVALID",
                "request must be ApprovalConsumptionRequestV2",
            )
        self._validate_admission_fingerprint(request)
        self._validate_admission_expiry(request)
        self._validate_approval_owners(request)
        self._validate_approval_join(request)
        allowed_operations = self._least_privilege_operations(request)
        record = self._build_approval_record(request, allowed_operations)
        return self._store.consume_admission_once(
            request.admission.admission_id,
            request.admission.admission_fingerprint,
            record,
        )

    def issue_execution_grant(
        self,
        request: ExecutionGrantRequestV2,
    ) -> ExecutionGrantV2:
        """为一个 exact REQUIRED materialization 生成或读取幂等 grant。"""
        if not isinstance(request, ExecutionGrantRequestV2):
            _error(
                "EXECUTION_GRANT_INPUT_INVALID",
                "request must be ExecutionGrantRequestV2",
            )
        stored = self._store.get_approval(request.approval_id)
        if stored is None:
            _error("APPROVAL_RECORD_NOT_FOUND", "approval record not found")
        if stored.lifecycle.state is ApprovalState.REVOKED:
            _error("APPROVAL_REVOKED", "approval is revoked")

        self._validate_execution_plan_owner(request)
        self._validate_materialization_authority(stored.record, request)
        self._validate_binding_owner(request)
        allowed_operations = self._validate_grant_operations(
            stored.record,
            request.execution_slice,
        )
        expires_at = self._derive_grant_expiry(
            request.provider_binding_set,
            request.issued_at,
        )
        grant = self._build_grant(
            stored.record,
            request,
            allowed_operations,
            expires_at,
        )
        return self._store.issue_or_get_grant_v2(grant)

    def admit_execution_grant(
        self,
        grant_hash: str,
        admitted_at: str,
    ) -> AdmittedExecutionAuthorityV2:
        """把一个持久 V2 grant 原子 admission 为 Host 执行 authority。"""
        return self._store.admit_grant_v2(grant_hash, admitted_at)

    @staticmethod
    def _validate_admission_fingerprint(
        request: ApprovalConsumptionRequestV2,
    ) -> None:
        expected = compute_admission_fingerprint(request.admission)
        if expected != request.admission.admission_fingerprint:
            _error(
                "APPROVAL_INTEGRITY_INVALID",
                "ApprovalAdmission fingerprint does not match immutable authority content",
            )

    @staticmethod
    def _validate_admission_expiry(
        request: ApprovalConsumptionRequestV2,
    ) -> None:
        if _parse_utc(request.consumed_at) >= _parse_utc(request.admission.expires_at):
            _error(
                "APPROVAL_ADMISSION_EXPIRED",
                "ApprovalAdmission is not valid at consumed_at",
            )

    @staticmethod
    def _validate_approval_owners(
        request: ApprovalConsumptionRequestV2,
    ) -> None:
        try:
            validate_approval_scope_boundary_v2(request.approval_scope_boundary)
        except ApprovalScopeError as exc:
            _error(
                "APPROVAL_INTEGRITY_INVALID",
                "Step28 V2 approval scope integrity validation failed",
                upstream_code=exc.code,
            )
        try:
            validate_changeset_integrity_v2(
                request.canonical_changeset,
                request.approval_scope_boundary,
            )
        except ChangeSetError as exc:
            _error(
                "APPROVAL_INTEGRITY_INVALID",
                "Step29 V2 ChangeSet integrity validation failed",
                upstream_code=exc.code,
            )

    @staticmethod
    def _validate_approval_join(
        request: ApprovalConsumptionRequestV2,
    ) -> None:
        admission = request.admission
        changeset = request.canonical_changeset
        boundary = request.approval_scope_boundary
        if not (
            admission.changeset_hash
            == changeset.changeset_hash
            == boundary.changeset_hash
        ):
            _error(
                "APPROVAL_SCOPE_MISMATCH",
                "ApprovalAdmission, ChangeSet, and BoundaryV2 changeset hashes differ",
            )
        if (
            changeset.approval_scope_definition_ref.scope_body_hash
            != boundary.scope_body_hash
        ):
            _error(
                "APPROVAL_SCOPE_MISMATCH",
                "ChangeSet scope body does not match final BoundaryV2",
            )
        if admission.approved_scope_hash != boundary.scope_hash:
            _error(
                "APPROVAL_SCOPE_MISMATCH",
                "ApprovalAdmission approved scope does not match BoundaryV2",
            )
        if not (
            admission.semantic_environment_ref
            == changeset.semantic_environment_ref
            == boundary.semantic_environment_ref
        ):
            _error(
                "SEMANTIC_ENVIRONMENT_MISMATCH",
                "approval semantic environments do not match exactly",
            )

    @staticmethod
    def _least_privilege_operations(
        request: ApprovalConsumptionRequestV2,
    ) -> tuple[str, ...]:
        changeset = request.canonical_changeset
        operations = tuple(
            sorted(
                {
                    changeset.root_operation.canonical_operation,
                    *(
                        operation.canonical_operation
                        for operation in changeset.derived_operations
                    ),
                }
            )
        )
        if not set(operations).issubset(request.admission.policy_allowed_operations):
            _error(
                "APPROVAL_OPERATION_FORBIDDEN",
                "ChangeSet contains canonical operations outside policy authority",
            )
        return operations

    @staticmethod
    def _build_approval_record(
        request: ApprovalConsumptionRequestV2,
        allowed_operations: tuple[str, ...],
    ) -> ApprovalRecord:
        admission = request.admission
        approval_hash = compute_approval_hash(
            admission_fingerprint=admission.admission_fingerprint,
            changeset_hash=admission.changeset_hash,
            approved_scope_hash=admission.approved_scope_hash,
            semantic_environment_ref=admission.semantic_environment_ref,
            approver=admission.approver,
            policy_snapshot_hash=admission.policy_snapshot_hash,
            allowed_operations=allowed_operations,
            approved_at=admission.approved_at,
        )
        return ApprovalRecord(
            approval_id=f"AR-{approval_hash[:12]}",
            admission_id=admission.admission_id,
            admission_fingerprint=admission.admission_fingerprint,
            changeset_hash=admission.changeset_hash,
            approved_scope_hash=admission.approved_scope_hash,
            semantic_environment_ref=admission.semantic_environment_ref,
            approver=admission.approver,
            policy_snapshot_hash=admission.policy_snapshot_hash,
            allowed_operations=allowed_operations,
            approved_at=admission.approved_at,
            consumed_at=request.consumed_at,
            approval_hash=approval_hash,
        )

    @staticmethod
    def _validate_execution_plan_owner(
        request: ExecutionGrantRequestV2,
    ) -> None:
        try:
            validate_execution_plan_v2(
                request.execution_plan,
                request.topology_snapshot,
                request.approval_scope_boundary,
            )
        except ExecutionPlanningError as exc:
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                "Step30 V2 execution plan integrity validation failed",
                upstream_code=exc.code,
            )

    @staticmethod
    def _validate_materialization_authority(
        approval: ApprovalRecord,
        request: ExecutionGrantRequestV2,
    ) -> None:
        execution_plan = request.execution_plan
        execution_slice = request.execution_slice
        materialization_plan = request.materialization_plan
        boundary = request.approval_scope_boundary

        exact_slices = tuple(
            item
            for item in execution_plan.execution_slices
            if item.materialization_id == execution_slice.materialization_id
        )
        if (
            len(exact_slices) != 1
            or exact_slices[0] != execution_slice
        ):
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                "ExecutionSliceV2 is not the exact materialization Slice in ExecutionPlanV2",
            )

        if not (
            execution_plan.materialization_plan_hash
            == materialization_plan.materialization_plan_hash
            == execution_slice.materialization_plan_hash
        ):
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                "materialization plan lineage differs across plan and Slice",
            )
        if not (
            execution_plan.required_set_hash == materialization_plan.required_set_hash
            and execution_plan.topology_snapshot_hash
            == materialization_plan.topology_snapshot_hash
            == request.topology_snapshot.topology_snapshot_hash
        ):
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                "required-set or topology lineage differs",
            )
        if not (
            approval.changeset_hash
            == materialization_plan.changeset_hash
            == execution_plan.changeset_hash
            == execution_slice.changeset_hash
            == boundary.changeset_hash
        ):
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                "approval and materialization changeset lineage differs",
            )
        if not (
            approval.approved_scope_hash
            == materialization_plan.approved_scope_hash
            == execution_plan.approval_scope_ref.scope_hash
            == execution_slice.approved_scope_ref.scope_hash
            == boundary.scope_hash
        ):
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                "approval and materialization scope lineage differs",
            )

        intents = tuple(
            intent
            for intent in materialization_plan.intents
            if intent.materialization_id == execution_slice.materialization_id
        )
        if len(intents) != 1:
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                "materialization id is not uniquely present in MaterializationPlan",
            )
        intent = intents[0]
        unit = execution_slice.execution_units[0]
        if (
            intent.materialization_slot_id != execution_slice.materialization_slot_id
            or intent.materialization_slot_id != unit.materialization_slot_id
            or intent.required_host_type != execution_slice.host_runtime_ref.host_type
            or intent.required_host_type != unit.required_host_type
            or set(intent.semantic_targets) != set(unit.targets)
        ):
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                "materialization intent does not match the exact V2 Slice",
            )

    @staticmethod
    def _validate_binding_owner(
        request: ExecutionGrantRequestV2,
    ) -> None:
        try:
            validate_provider_binding_set_v2(
                request.provider_binding_set,
                request.execution_slice,
            )
        except ProviderBindingError as exc:
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                "Step31 V2 ProviderBindingSet validation failed",
                upstream_code=exc.code,
            )
        binding_set = request.provider_binding_set
        execution_slice = request.execution_slice
        if (
            binding_set.materialization_id != execution_slice.materialization_id
            or binding_set.materialization_plan_hash
            != execution_slice.materialization_plan_hash
            or binding_set.execution_slice_id != execution_slice.execution_slice_id
            or binding_set.execution_slice_hash != execution_slice.execution_slice_hash
        ):
            _error(
                "MATERIALIZATION_AUTHORITY_MISMATCH",
                "ProviderBindingSetV2 lineage differs from exact Slice",
            )

    @staticmethod
    def _validate_grant_operations(
        approval: ApprovalRecord,
        execution_slice: ExecutionSliceV2,
    ) -> tuple[str, ...]:
        operations = tuple(
            sorted(
                {
                    unit.canonical_operation
                    for unit in execution_slice.execution_units
                }
            )
        )
        if not set(operations).issubset(approval.allowed_operations):
            _error(
                "EXECUTION_GRANT_OPERATION_FORBIDDEN",
                "materialization Slice contains operations outside ApprovalRecord authority",
            )
        return operations

    @staticmethod
    def _derive_grant_expiry(
        binding_set: ProviderBindingSetV2,
        issued_at: str,
    ) -> str:
        expires_at = min(
            binding.binding_expires_at for binding in binding_set.bindings
        )
        if _parse_utc(issued_at) >= _parse_utc(expires_at):
            _error(
                "EXECUTION_BINDING_EXPIRED",
                "provider binding authority is expired at issued_at",
            )
        return expires_at

    @staticmethod
    def _build_grant(
        approval: ApprovalRecord,
        request: ExecutionGrantRequestV2,
        allowed_operations: tuple[str, ...],
        expires_at: str,
    ) -> ExecutionGrantV2:
        execution_slice = request.execution_slice
        binding_set = request.provider_binding_set
        grant_hash = compute_grant_hash_v2(
            approval_hash=approval.approval_hash,
            changeset_hash=execution_slice.changeset_hash,
            approved_scope_hash=execution_slice.approved_scope_ref.scope_hash,
            materialization_plan_hash=execution_slice.materialization_plan_hash,
            materialization_id=execution_slice.materialization_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            binding_set_hash=binding_set.binding_set_hash,
            host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
            allowed_operations=allowed_operations,
            issued_at=request.issued_at,
            expires_at=expires_at,
        )
        return ExecutionGrantV2(
            grant_id=f"EGV2-{grant_hash[:12]}",
            approval_id=approval.approval_id,
            approval_hash=approval.approval_hash,
            changeset_hash=execution_slice.changeset_hash,
            approved_scope_hash=execution_slice.approved_scope_ref.scope_hash,
            materialization_plan_hash=execution_slice.materialization_plan_hash,
            materialization_id=execution_slice.materialization_id,
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            binding_set_hash=binding_set.binding_set_hash,
            host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
            allowed_operations=allowed_operations,
            issued_at=request.issued_at,
            expires_at=expires_at,
            grant_hash=grant_hash,
        )


__all__ = [
    "AdmittedExecutionAuthorityV2",
    "ApprovalConsumptionRequestV2",
    "ExecutionGrantRequestV2",
    "ExecutionGrantV2",
    "GatewayAuthorizationServiceV2",
    "compute_grant_hash_v2",
]
