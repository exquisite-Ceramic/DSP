"""AutoCAD 墙厚 materialization 的只读 readiness 适配器。"""

from __future__ import annotations

import asyncio
import math
from dataclasses import replace

from design_execution_coordination import (
    HostReadinessReceipt,
    ReadinessError,
    ReadinessStatus,
    compute_readiness_receipt_hash,
)
from design_execution_planning import ExecutionSliceV2
from design_fact_contracts import FactKind, NormalizedDesignFactBatch
from design_gateway_authorization import AdmittedExecutionAuthorityV2
from design_provider_binding import (
    ProviderBindingError,
    ProviderBindingSetV2,
    validate_provider_binding_set_v2,
)


def _error(code: str, message: str) -> None:
    """统一抛出稳定的 readiness 领域错误。"""
    raise ReadinessError(code, message)


def _signed_receipt(
    *,
    execution_slice: ExecutionSliceV2,
    authority: AdmittedExecutionAuthorityV2,
    binding_set: ProviderBindingSetV2,
    observed_revision: int,
    status: ReadinessStatus,
    failure_code: str | None,
) -> HostReadinessReceipt:
    """用真实 Host revision 与 exact authority lineage 签发不可变回执。"""
    provisional = HostReadinessReceipt(
        materialization_id=execution_slice.materialization_id,
        materialization_plan_hash=execution_slice.materialization_plan_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        binding_set_hash=binding_set.binding_set_hash,
        grant_hash=authority.grant_hash,
        host_runtime_ref=execution_slice.host_runtime_ref,
        observed_revision=observed_revision,
        status=status,
        failure_code=failure_code,
        receipt_hash="0" * 64,
    )
    return replace(
        provisional,
        receipt_hash=compute_readiness_receipt_hash(provisional),
    )


def _not_ready(
    *,
    execution_slice: ExecutionSliceV2,
    authority: AdmittedExecutionAuthorityV2,
    binding_set: ProviderBindingSetV2,
    observed_revision: int,
    failure_code: str,
) -> HostReadinessReceipt:
    """构造带真实观察 revision 的 NOT_READY 回执。"""
    return _signed_receipt(
        execution_slice=execution_slice,
        authority=authority,
        binding_set=binding_set,
        observed_revision=observed_revision,
        status=ReadinessStatus.NOT_READY,
        failure_code=failure_code,
    )


def _validate_lineage(
    execution_slice: ExecutionSliceV2,
    authority: AdmittedExecutionAuthorityV2,
    binding_set: ProviderBindingSetV2,
):
    """在任何 Host 读取前验证 Slice、binding 与 grant 的 exact lineage。"""
    if not isinstance(execution_slice, ExecutionSliceV2):
        raise TypeError("execution_slice must be ExecutionSliceV2")
    if not isinstance(authority, AdmittedExecutionAuthorityV2):
        raise TypeError("authority must be AdmittedExecutionAuthorityV2")
    if not isinstance(binding_set, ProviderBindingSetV2):
        raise TypeError("binding_set must be ProviderBindingSetV2")
    if execution_slice.host_runtime_ref.host_type != "autocad":
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "AutoCAD readiness port received a non-AutoCAD execution Slice",
        )
    try:
        validate_provider_binding_set_v2(binding_set, execution_slice)
    except ProviderBindingError as exc:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            f"Step31 V2 binding validation failed: {exc.code}",
        )
    if (
        authority.materialization_id != execution_slice.materialization_id
        or authority.materialization_plan_hash
        != execution_slice.materialization_plan_hash
        or authority.execution_slice_hash != execution_slice.execution_slice_hash
        or authority.binding_set_hash != binding_set.binding_set_hash
        or authority.host_instance_id
        != execution_slice.host_runtime_ref.host_instance_id
        or authority.changeset_hash != execution_slice.changeset_hash
        or authority.approved_scope_hash
        != execution_slice.approved_scope_ref.scope_hash
    ):
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "admitted authority does not match the exact AutoCAD materialization",
        )
    if len(execution_slice.execution_units) != 1:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "AutoCAD readiness requires exactly one execution unit",
        )
    if len(binding_set.bindings) != 1:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "AutoCAD readiness requires exactly one ProviderBindingV2",
        )
    binding = binding_set.bindings[0]
    if len(binding.native_targets) != 1:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "AutoCAD readiness requires exactly one native target",
        )
    target = binding.native_targets[0]
    unit = execution_slice.execution_units[0]
    if (
        len(unit.targets) != 1
        or target.semantic_id != unit.targets[0]
        or target.host_type != "autocad"
        or target.document_ref != execution_slice.host_runtime_ref.document_ref
        or binding.host_runtime_ref != execution_slice.host_runtime_ref
    ):
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "AutoCAD native target does not match the exact semantic/runtime Slice",
        )
    return target


def _read_facts(dispatcher, native_id: str) -> NormalizedDesignFactBatch:
    """从同步 readiness 边界桥接现有 async AutoCAD 只读 fact extraction。"""
    extractor = getattr(dispatcher, "extract_design_facts", None)
    if not callable(extractor):
        raise TypeError("dispatcher must provide extract_design_facts")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        _error(
            "READINESS_FAILED",
            "AutoCAD synchronous readiness cannot run inside an active event loop",
        )
    try:
        batch = asyncio.run(extractor([native_id]))
    except (RuntimeError, TypeError, ValueError) as exc:
        _error("READINESS_FAILED", f"AutoCAD design fact extraction failed: {exc}")
    if not isinstance(batch, NormalizedDesignFactBatch):
        _error(
            "READINESS_FAILED",
            "AutoCAD design fact extraction did not return NormalizedDesignFactBatch",
        )
    return batch


def _observed_revision(batch: NormalizedDesignFactBatch) -> int:
    """要求本次目标 facts 非空且共享唯一真实 source revision。"""
    if not batch.facts:
        _error(
            "READINESS_FAILED",
            "AutoCAD readiness cannot prove a Host revision from an empty fact batch",
        )
    revisions = {fact.source_revision for fact in batch.facts}
    if len(revisions) != 1:
        return -1
    return next(iter(revisions))


class AutoCadWallThicknessReadinessPort:
    """仅通过 normalized fact read path 检查 AutoCAD 墙厚 materialization readiness。"""

    def __init__(self, dispatcher) -> None:
        if dispatcher is None or not callable(
            getattr(dispatcher, "extract_design_facts", None)
        ):
            raise TypeError("dispatcher must provide extract_design_facts")
        self._dispatcher = dispatcher

    def check(
        self,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
    ) -> HostReadinessReceipt:
        """只读检查 exact AutoCAD native wall 并返回带真实 revision 的回执。"""
        target = _validate_lineage(execution_slice, authority, binding_set)
        batch = _read_facts(self._dispatcher, target.native_id)
        revision = _observed_revision(batch)
        if revision < 0:
            revisions = {fact.source_revision for fact in batch.facts}
            observed = min(revisions)
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=observed,
                failure_code="AUTOCAD_READINESS_REVISION_MISMATCH",
            )

        expected_runtime = execution_slice.host_runtime_ref
        if any(fact.host_ref.host_type != "autocad" for fact in batch.facts):
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=revision,
                failure_code="AUTOCAD_READINESS_HOST_MISMATCH",
            )
        if any(
            fact.host_ref.host_instance_id != expected_runtime.host_instance_id
            for fact in batch.facts
        ):
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=revision,
                failure_code="AUTOCAD_READINESS_HOST_MISMATCH",
            )
        if any(
            fact.host_ref.document_id != expected_runtime.document_ref
            or fact.subject_native_ref.document_id != expected_runtime.document_ref
            for fact in batch.facts
        ):
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=revision,
                failure_code="AUTOCAD_READINESS_DOCUMENT_MISMATCH",
            )
        if any(
            fact.subject_native_ref.native_id != target.native_id
            for fact in batch.facts
        ):
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=revision,
                failure_code="AUTOCAD_READINESS_TARGET_MISMATCH",
            )
        if target.native_kind != "LWPOLYLINE":
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=revision,
                failure_code="AUTOCAD_READINESS_NATIVE_KIND_UNSUPPORTED",
            )
        if any(
            fact.subject_native_ref.native_kind != target.native_kind
            for fact in batch.facts
        ):
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=revision,
                failure_code="AUTOCAD_READINESS_NATIVE_KIND_MISMATCH",
            )

        width_facts = tuple(
            fact
            for fact in batch.facts
            if fact.fact_kind is FactKind.PROPERTY
            and fact.source_scheme == "autocad.property"
            and fact.source_code == "LWPOLYLINE.ConstantWidth"
            and fact.predicate == "constant_width"
        )
        if not width_facts:
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=revision,
                failure_code="AUTOCAD_READINESS_WIDTH_MISSING",
            )
        if len(width_facts) != 1:
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=revision,
                failure_code="AUTOCAD_READINESS_WIDTH_CONFLICT",
            )
        width = width_facts[0]
        if width.unit != "mm":
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=revision,
                failure_code="AUTOCAD_READINESS_WIDTH_UNIT_MISMATCH",
            )
        if (
            isinstance(width.value, bool)
            or not isinstance(width.value, (int, float))
            or not math.isfinite(width.value)
            or width.value <= 0
        ):
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=revision,
                failure_code="AUTOCAD_READINESS_WIDTH_INVALID",
            )
        return _signed_receipt(
            execution_slice=execution_slice,
            authority=authority,
            binding_set=binding_set,
            observed_revision=revision,
            status=ReadinessStatus.READY,
            failure_code=None,
        )


__all__ = ["AutoCadWallThicknessReadinessPort"]
