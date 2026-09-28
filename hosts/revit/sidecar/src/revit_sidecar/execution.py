"""Revit 墙厚 materialized execution 的真实 Host I/O 组合端口。"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from design_execution_coordination import (
    HostCommitted,
    HostDispatchContext,
    HostExecutionResult,
    HostFailed,
    HostFailurePhase,
)
from design_execution_planning import ExecutionSliceV2
from design_gateway_authorization import AdmittedExecutionAuthorityV2
from design_provider_binding import (
    ProviderBindingError,
    ProviderBindingSetV2,
    validate_provider_binding_set_v2,
)

from .execution_result_adapter import RevitExecutionResultAdapter
from .model_adapter import RevitHostAdapter


def _utc_now() -> str:
    """生成 Host outcome 的 UTC 审计时间；该时间不参与 command/binding authority。"""

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _expected_revision(binding) -> int:
    """读取已经进入 Step31 V2 binding hash 的 exact planning revision。"""

    value = binding.native_binding_metadata.get("expected_revision")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("Revit binding requires hash-bound non-negative expected_revision")
    return value


def _thickness_mm(unit) -> float:
    """只接受 canonical execution unit 中有限、正值、mm 墙厚。"""

    raw = unit.arguments.get("thickness")
    if not isinstance(raw, Mapping):
        raise TypeError("Revit execution requires thickness argument mapping")
    value = raw.get("value")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        or raw.get("unit") != "mm"
    ):
        raise ValueError("Revit execution requires finite positive mm thickness")
    return float(value)


def _validate_lineage(
    execution_slice: ExecutionSliceV2,
    authority: AdmittedExecutionAuthorityV2,
    binding_set: ProviderBindingSetV2,
    dispatch_context: HostDispatchContext,
):
    """在任何 Host 写 I/O 前关闭 Slice、Grant、Binding 与 durable dispatch joins。"""

    if not isinstance(execution_slice, ExecutionSliceV2):
        raise TypeError("execution_slice must be ExecutionSliceV2")
    if not isinstance(authority, AdmittedExecutionAuthorityV2):
        raise TypeError("authority must be AdmittedExecutionAuthorityV2")
    if not isinstance(binding_set, ProviderBindingSetV2):
        raise TypeError("binding_set must be ProviderBindingSetV2")
    if not isinstance(dispatch_context, HostDispatchContext):
        raise TypeError("dispatch_context must be HostDispatchContext")
    if execution_slice.host_runtime_ref.host_type != "revit":
        raise ValueError("Revit execution port requires a Revit ExecutionSliceV2")
    if dispatch_context.execution_slice_hash != execution_slice.execution_slice_hash:
        raise ValueError("HostDispatchContext does not match exact ExecutionSliceV2")

    try:
        validate_provider_binding_set_v2(binding_set, execution_slice)
    except ProviderBindingError as exc:
        raise ValueError(
            f"Step31 V2 binding validation failed: {exc.code}"
        ) from exc

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
        raise ValueError("admitted authority does not match exact Revit execution lineage")

    if len(execution_slice.execution_units) != 1 or len(binding_set.bindings) != 1:
        raise ValueError("Revit wall thickness execution requires exactly one unit and binding")
    unit = execution_slice.execution_units[0]
    binding = binding_set.bindings[0]
    if unit.canonical_operation != "set_wall_thickness.v1":
        raise ValueError("unsupported Revit canonical operation")
    if binding.provider_tool != "revit.set_wall_thickness":
        raise ValueError("unsupported Revit provider tool")
    if len(unit.targets) != 1 or len(binding.native_targets) != 1:
        raise ValueError("Revit wall thickness execution requires exactly one target")

    target = binding.native_targets[0]
    if (
        target.semantic_id != unit.targets[0]
        or target.host_type != "revit"
        or target.document_ref != execution_slice.host_runtime_ref.document_ref
        or target.native_kind != "Wall"
        or binding.host_runtime_ref != execution_slice.host_runtime_ref
    ):
        raise ValueError("Revit native target does not match exact execution lineage")
    return unit, binding, target


class RevitWallThicknessExecutionPort:
    """把 admitted Revit Slice 转成既有 HostCommand 并规范化 Host outcome。"""

    def __init__(
        self,
        transport,
        *,
        clock: Callable[[], str] | None = None,
    ) -> None:
        if transport is None or not callable(getattr(transport, "request", None)):
            raise TypeError("transport must provide request")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._transport = transport
        self._clock = clock or _utc_now

    def execute(
        self,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
        dispatch_context: HostDispatchContext,
    ) -> HostExecutionResult:
        """执行一个 exact admitted wall-thickness logical dispatch。"""

        unit, binding, target = _validate_lineage(
            execution_slice,
            authority,
            binding_set,
            dispatch_context,
        )
        expected_revision = _expected_revision(binding)
        thickness_mm = _thickness_mm(unit)
        runtime_ref = execution_slice.host_runtime_ref
        command = RevitHostAdapter.build_set_wall_thickness_command(
            command_id=dispatch_context.dispatch_intent_id,
            document_id=runtime_ref.document_ref,
            wall_unique_id=target.native_id,
            expected_revision=expected_revision,
            thickness_mm=thickness_mm,
            idempotency_key=dispatch_context.idempotency_key,
        )
        validation_errors = command.validate()
        if validation_errors:
            raise ValueError(f"Revit HostCommand invalid: {validation_errors}")

        try:
            host_result = self._transport.request(command)
        except OSError:
            # EXECUTE 已跨过 transport 调用边界后，I/O 断连无法证明 Host 未提交。
            # 必须保守进入 existing unknown-outcome recovery，绝不能降格为 BEFORE_COMMIT。
            return HostFailed(
                phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
                failure_ref="REVIT_COMMIT_STATE_UNKNOWN",
                failed_at=self._clock(),
            )
        if not isinstance(host_result, Mapping):
            raise TypeError("Revit transport response must be a mapping")
        if host_result.get("command_id") != command.command_id:
            raise ValueError("Revit Host response command_id does not match durable dispatch")

        occurred_at = self._clock()
        outcome = RevitExecutionResultAdapter.adapt(
            admitted_authority=authority,
            document_ref=runtime_ref.document_ref,
            approved_semantic_wall_id=unit.targets[0],
            host_result=host_result,
            occurred_at=occurred_at,
        )
        if (
            isinstance(outcome, HostCommitted)
            and outcome.actual_delta.revision_before != expected_revision
        ):
            # 结构完整的成功响应仍必须证明它从 hash-bound planning revision 开始提交。
            # 不一致说明 mutation 可能已经发生，但不属于本次授权的正常 commit 证据；
            # 维持 unknown outcome，阻止 coordinator 再次发送同一 mutation。
            return HostFailed(
                phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
                failure_ref="REVIT_COMMIT_REVISION_MISMATCH",
                failed_at=occurred_at,
            )
        return outcome


__all__ = ["RevitWallThicknessExecutionPort"]