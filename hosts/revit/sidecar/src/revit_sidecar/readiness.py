"""Revit 墙厚 materialization 的只读 readiness 适配器。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace

from design_execution_coordination import (
    HostReadinessReceipt,
    ReadinessError,
    ReadinessStatus,
    compute_readiness_receipt_hash,
)
from design_execution_planning import ExecutionSliceV2
from design_gateway_authorization import AdmittedExecutionAuthorityV2
from design_provider_binding import (
    ProviderBindingError,
    ProviderBindingSetV2,
    validate_provider_binding_set_v2,
)
from host_contracts import HostCommand, HostEntityRef


def _error(code: str, message: str) -> None:
    """统一抛出稳定的 Revit readiness 领域错误。"""
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
    """用真实 Revit revision 和 exact authority lineage 签发 readiness 回执。"""
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
    """构造保留真实 Host revision 的 NOT_READY 回执。"""
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
    """在 named-pipe I/O 前验证 Slice、binding、grant 和 native identity。"""
    if not isinstance(execution_slice, ExecutionSliceV2):
        raise TypeError("execution_slice must be ExecutionSliceV2")
    if not isinstance(authority, AdmittedExecutionAuthorityV2):
        raise TypeError("authority must be AdmittedExecutionAuthorityV2")
    if not isinstance(binding_set, ProviderBindingSetV2):
        raise TypeError("binding_set must be ProviderBindingSetV2")
    if execution_slice.host_runtime_ref.host_type != "revit":
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "Revit readiness port received a non-Revit execution Slice",
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
            "admitted authority does not match the exact Revit materialization",
        )
    if len(execution_slice.execution_units) != 1 or len(binding_set.bindings) != 1:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "Revit readiness requires exactly one execution unit and one binding",
        )
    unit = execution_slice.execution_units[0]
    binding = binding_set.bindings[0]
    if len(unit.targets) != 1 or len(binding.native_targets) != 1:
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "Revit readiness requires exactly one semantic and native target",
        )
    target = binding.native_targets[0]
    if (
        target.semantic_id != unit.targets[0]
        or target.host_type != "revit"
        or target.document_ref != execution_slice.host_runtime_ref.document_ref
        or target.native_kind != "Wall"
        or binding.host_runtime_ref != execution_slice.host_runtime_ref
    ):
        _error(
            "READINESS_LINEAGE_MISMATCH",
            "Revit native target does not match the exact semantic/runtime Slice",
        )
    return unit, target


def _thickness_argument(unit) -> dict:
    """从 canonical V2 execution unit 提取 exact mm 墙厚参数。"""
    raw = unit.arguments.get("thickness")
    if not isinstance(raw, Mapping):
        _error("READINESS_FAILED", "Revit readiness requires thickness argument mapping")
    value = raw.get("value")
    unit_name = raw.get("unit")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        or unit_name != "mm"
    ):
        _error("READINESS_FAILED", "Revit readiness requires finite positive mm thickness")
    return {"value": float(value), "unit": "mm"}


def _revision(response: Mapping) -> int:
    """只接受 Host 明确返回的真实非负 revision。"""
    value = response.get("revision_after")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _error(
            "READINESS_FAILED",
            "Revit readiness response requires a real non-negative revision_after",
        )
    return value


def _mapping(value, field_name: str) -> Mapping:
    """要求 Host response 的结构字段为 mapping。"""
    if not isinstance(value, Mapping):
        _error("READINESS_FAILED", f"{field_name} must be a mapping")
    return value


class RevitWallThicknessReadinessPort:
    """通过既有 named-pipe HostCommand 路径执行只读 Revit readiness。"""

    def __init__(self, transport) -> None:
        if transport is None or not callable(getattr(transport, "request", None)):
            raise TypeError("transport must provide request")
        self._transport = transport

    def check(
        self,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
    ) -> HostReadinessReceipt:
        """对 exact Revit wall 发出一个 READ 命令并验证返回证据。"""
        unit, target = _validate_lineage(execution_slice, authority, binding_set)
        thickness = _thickness_argument(unit)
        runtime_ref = execution_slice.host_runtime_ref
        command = HostCommand(
            command_id=f"READINESS-{execution_slice.execution_slice_id}",
            document_id=runtime_ref.document_ref,
            mode="READ",
            operation="check_wall_thickness_readiness",
            target_native_refs=[
                HostEntityRef(
                    document_id=runtime_ref.document_ref,
                    native_id=target.native_id,
                    native_type="Wall",
                )
            ],
            arguments={"thickness": thickness},
            preconditions=[],
            idempotency_key=None,
        )
        validation_errors = command.validate()
        if validation_errors:
            _error(
                "READINESS_FAILED",
                f"Revit readiness HostCommand invalid: {validation_errors}",
            )
        try:
            response = self._transport.request(command)
        except (ConnectionError, OSError, TypeError, ValueError) as exc:
            _error("READINESS_FAILED", f"Revit readiness transport failed: {exc}")
        response = _mapping(response, "response")
        observed_revision = _revision(response)
        status = response.get("status")
        if status == "ERROR":
            error = _mapping(response.get("error"), "response.error")
            code = error.get("code")
            if not isinstance(code, str) or not code.strip():
                _error("READINESS_FAILED", "Revit readiness error response lacks code")
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=observed_revision,
                failure_code=code.strip(),
            )
        if status != "OK":
            _error("READINESS_FAILED", f"unsupported Revit readiness status: {status!r}")

        payload = _mapping(response.get("payload"), "response.payload")
        if payload.get("document_id") != runtime_ref.document_ref:
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=observed_revision,
                failure_code="REVIT_READINESS_DOCUMENT_MISMATCH",
            )
        if payload.get("wall_unique_id") != target.native_id:
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=observed_revision,
                failure_code="REVIT_READINESS_TARGET_MISMATCH",
            )

        current_width = _mapping(payload.get("current_width"), "payload.current_width")
        if current_width.get("unit") != "mm":
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=observed_revision,
                failure_code="REVIT_READINESS_WIDTH_UNIT_MISMATCH",
            )
        width_value = current_width.get("value")
        if (
            isinstance(width_value, bool)
            or not isinstance(width_value, (int, float))
            or not math.isfinite(width_value)
            or width_value <= 0
        ):
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=observed_revision,
                failure_code="REVIT_READINESS_WIDTH_INVALID",
            )
        if payload.get("isolation_ready") is not True:
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=observed_revision,
                failure_code="REVIT_READINESS_ISOLATION_UNPROVEN",
            )
        if payload.get("plan_ready") is not True:
            return _not_ready(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                observed_revision=observed_revision,
                failure_code="REVIT_READINESS_PLAN_UNPROVEN",
            )
        return _signed_receipt(
            execution_slice=execution_slice,
            authority=authority,
            binding_set=binding_set,
            observed_revision=observed_revision,
            status=ReadinessStatus.READY,
            failure_code=None,
        )


__all__ = ["RevitWallThicknessReadinessPort"]
