"""Phase I 全 REQUIRED materialization 的 provider-neutral readiness barrier。"""

from __future__ import annotations

from collections.abc import Sequence

from design_execution_planning import ExecutionPlanV2, ExecutionSliceV2
from design_gateway_authorization import AdmittedExecutionAuthorityV2
from design_materialization_planning import MaterializationPlan
from design_provider_binding import (
    ProviderBindingError,
    ProviderBindingSetV2,
    validate_cross_materialization_identity,
    validate_provider_binding_set_v2,
)

from .ports import HostReadinessRegistry
from .readiness_contracts import (
    HostReadinessReceipt,
    ReadinessBarrierResult,
    ReadinessBarrierStatus,
    ReadinessError,
    ReadinessStatus,
    compute_readiness_receipt_hash,
)


def _error(code: str, message: str) -> None:
    """统一抛出稳定的 readiness 领域错误。"""
    raise ReadinessError(code, message)


def _validate_plan_join(
    plan: MaterializationPlan,
    execution_plan: ExecutionPlanV2,
) -> dict[str, ExecutionSliceV2]:
    """验证 MaterializationPlan 与 ExecutionPlanV2 的闭世界 lineage join。"""
    if execution_plan.materialization_plan_hash != plan.materialization_plan_hash:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "execution plan does not reference the exact MaterializationPlan",
        )
    if execution_plan.required_set_hash != plan.required_set_hash:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "execution plan required set does not match the MaterializationPlan",
        )
    if execution_plan.changeset_hash != plan.changeset_hash:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "execution plan changeset does not match the MaterializationPlan",
        )
    if execution_plan.approval_scope_ref.scope_hash != plan.approved_scope_hash:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "execution plan approved scope does not match the MaterializationPlan",
        )

    expected_ids = {intent.materialization_id for intent in plan.intents}
    supplied_ids = [item.materialization_id for item in execution_plan.execution_slices]
    if len(set(supplied_ids)) != len(supplied_ids) or set(supplied_ids) != expected_ids:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "execution slices do not exactly cover the required materialization set",
        )

    slices = {
        item.materialization_id: item for item in execution_plan.execution_slices
    }
    for materialization_id, execution_slice in slices.items():
        if (
            execution_slice.materialization_plan_hash
            != plan.materialization_plan_hash
            or execution_slice.changeset_hash != plan.changeset_hash
            or execution_slice.execution_slice_hash == "0" * 64
        ):
            _error(
                "READINESS_LINEAGE_MISMATCH",
                f"execution Slice lineage mismatch for {materialization_id}",
            )
    return slices


def _binding_index(
    plan: MaterializationPlan,
    slices: dict[str, ExecutionSliceV2],
    binding_sets: Sequence[ProviderBindingSetV2],
) -> dict[str, ProviderBindingSetV2]:
    """在调用任何 Host readiness 端口前校验全部 binding set。"""
    normalized = tuple(binding_sets)
    if any(not isinstance(item, ProviderBindingSetV2) for item in normalized):
        raise TypeError("binding_sets must contain ProviderBindingSetV2 values")
    try:
        validate_cross_materialization_identity(plan, normalized)
    except ProviderBindingError as exc:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            f"provider binding closed-world validation failed: {exc.code}",
        )

    result = {item.materialization_id: item for item in normalized}
    if len(result) != len(normalized):
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "duplicate provider binding set materialization ids are forbidden",
        )
    for materialization_id, binding_set in result.items():
        execution_slice = slices.get(materialization_id)
        if execution_slice is None:
            _error(
                "READINESS_LINEAGE_MISMATCH",
                f"binding set has no required execution Slice: {materialization_id}",
            )
        try:
            validate_provider_binding_set_v2(binding_set, execution_slice)
        except ProviderBindingError as exc:
            _error(
                "READINESS_LINEAGE_MISMATCH",
                f"provider binding integrity validation failed: {exc.code}",
            )
    return result


def _authority_index(
    plan: MaterializationPlan,
    slices: dict[str, ExecutionSliceV2],
    bindings: dict[str, ProviderBindingSetV2],
    authorities: Sequence[AdmittedExecutionAuthorityV2],
) -> dict[str, AdmittedExecutionAuthorityV2]:
    """验证全部 admitted grant 与 exact Slice/binding/Host lineage。"""
    normalized = tuple(authorities)
    if any(not isinstance(item, AdmittedExecutionAuthorityV2) for item in normalized):
        raise TypeError("authorities must contain AdmittedExecutionAuthorityV2 values")

    supplied_ids = [item.materialization_id for item in normalized]
    expected_ids = {intent.materialization_id for intent in plan.intents}
    if len(set(supplied_ids)) != len(supplied_ids) or set(supplied_ids) != expected_ids:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "admitted authorities do not exactly cover the required materialization set",
        )

    result = {item.materialization_id: item for item in normalized}
    for materialization_id, authority in result.items():
        execution_slice = slices[materialization_id]
        binding_set = bindings[materialization_id]
        if (
            authority.materialization_plan_hash != plan.materialization_plan_hash
            or authority.changeset_hash != plan.changeset_hash
            or authority.approved_scope_hash != plan.approved_scope_hash
            or authority.execution_slice_hash != execution_slice.execution_slice_hash
            or authority.binding_set_hash != binding_set.binding_set_hash
            or authority.host_instance_id
            != execution_slice.host_runtime_ref.host_instance_id
        ):
            _error(
                "READINESS_LINEAGE_MISMATCH",
                f"admitted authority lineage mismatch for {materialization_id}",
            )
    return result


def _validate_receipt(
    receipt: HostReadinessReceipt,
    execution_slice: ExecutionSliceV2,
    authority: AdmittedExecutionAuthorityV2,
    binding_set: ProviderBindingSetV2,
) -> None:
    """验证 Host 回执自身 hash 以及全部 readiness lineage。"""
    if not isinstance(receipt, HostReadinessReceipt):
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "Host readiness port must return HostReadinessReceipt",
        )
    if compute_readiness_receipt_hash(receipt) != receipt.receipt_hash:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "Host readiness receipt hash does not match immutable content",
        )
    if (
        receipt.materialization_id != execution_slice.materialization_id
        or receipt.materialization_plan_hash
        != execution_slice.materialization_plan_hash
        or receipt.execution_slice_hash != execution_slice.execution_slice_hash
        or receipt.binding_set_hash != binding_set.binding_set_hash
        or receipt.grant_hash != authority.grant_hash
        or receipt.host_runtime_ref != execution_slice.host_runtime_ref
    ):
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "Host readiness receipt does not match exact execution authority",
        )


class CrossHostReadinessBarrier:
    """在任何 Host mutation 前观察并汇总全部 REQUIRED materialization readiness。"""

    def __init__(self, registry: HostReadinessRegistry) -> None:
        if registry is None or not callable(getattr(registry, "resolve", None)):
            raise TypeError("registry must provide HostReadinessRegistry.resolve")
        self._registry = registry

    def check_all(
        self,
        plan: MaterializationPlan,
        execution_plan: ExecutionPlanV2,
        binding_sets: Sequence[ProviderBindingSetV2],
        authorities: Sequence[AdmittedExecutionAuthorityV2],
    ) -> ReadinessBarrierResult:
        """先闭世界校验 authority，再按 Step30 顺序执行全部只读 readiness 检查。"""
        if not isinstance(plan, MaterializationPlan):
            raise TypeError("plan must be MaterializationPlan")
        if not isinstance(execution_plan, ExecutionPlanV2):
            raise TypeError("execution_plan must be ExecutionPlanV2")

        slices = _validate_plan_join(plan, execution_plan)
        bindings = _binding_index(plan, slices, binding_sets)
        admitted = _authority_index(plan, slices, bindings, authorities)

        receipts: list[HostReadinessReceipt] = []
        for execution_slice in execution_plan.execution_slices:
            materialization_id = execution_slice.materialization_id
            binding_set = bindings[materialization_id]
            authority = admitted[materialization_id]
            port = self._registry.resolve(execution_slice.host_runtime_ref)
            if port is None or not callable(getattr(port, "check", None)):
                _error(
                    "READINESS_FAILED",
                    f"readiness port is unavailable for {materialization_id}",
                )
            receipt = port.check(execution_slice, authority, binding_set)
            _validate_receipt(receipt, execution_slice, authority, binding_set)
            receipts.append(receipt)

        first_not_ready = next(
            (item for item in receipts if item.status is ReadinessStatus.NOT_READY),
            None,
        )
        if first_not_ready is not None:
            return ReadinessBarrierResult(
                status=ReadinessBarrierStatus.NOT_READY,
                receipts=tuple(receipts),
                failure_ref=first_not_ready.failure_code,
            )
        return ReadinessBarrierResult(
            status=ReadinessBarrierStatus.READY,
            receipts=tuple(receipts),
            failure_ref=None,
        )


__all__ = ["CrossHostReadinessBarrier"]
