"""AutoCAD 墙厚产品 vertical 的 provider-binding 与 materialized execution adapters。"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime

from design_approval_scope import CanonicalAspect
from design_execution_coordination import (
    HostCommitted,
    HostDispatchContext,
    HostExecutionResult,
    HostFailed,
    HostFailurePhase,
)
from design_execution_planning import ExecutionSliceV2
from design_execution_reconciliation import (
    ActualChange,
    ActualChangeKind,
    ActualDelta,
    compute_actual_change_hash,
    compute_actual_delta_hash,
)
from design_gateway_authorization import AdmittedExecutionAuthorityV2
from design_provider_binding import (
    ProviderBindingError,
    ProviderBindingMaterial,
    ProviderBindingSetV2,
    ProviderExecutionSnapshotV2,
    compute_provider_snapshot_hash_v2,
    validate_provider_binding_set_v2,
)
from semantic_runtime import SnapshotKind

_CANONICAL_REVISION_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")


def _utc_now() -> str:
    """生成 Host outcome UTC 审计时间。"""

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_revision(value: object) -> int:
    """把 planning base revision 严格解析为 canonical 非负整数。"""

    if not isinstance(value, str) or _CANONICAL_REVISION_RE.fullmatch(value) is None:
        raise ValueError(
            "AutoCAD planning snapshot revision must be canonical non-negative decimal"
        )
    return int(value)


def _environment_identity(value: object) -> tuple[str, str]:
    """跨 owner 比较 semantic environment 的稳定 id/hash。"""

    environment_id = getattr(value, "environment_id", None)
    content_hash = getattr(value, "content_hash", None)
    if not isinstance(environment_id, str) or not environment_id.strip():
        raise ValueError("semantic environment requires environment_id")
    if not isinstance(content_hash, str) or not content_hash.strip():
        raise ValueError("semantic environment requires content_hash")
    return environment_id.strip(), content_hash.strip()


def _require_exact_provider_snapshot(
    snapshot: ProviderExecutionSnapshotV2,
    execution_slice: ExecutionSliceV2,
) -> None:
    """确认 environment-owned provider snapshot 对应 exact Slice。"""

    if not isinstance(snapshot, ProviderExecutionSnapshotV2):
        raise TypeError("provider_snapshot_factory must return ProviderExecutionSnapshotV2")
    if (
        snapshot.materialization_id != execution_slice.materialization_id
        or snapshot.materialization_plan_hash
        != execution_slice.materialization_plan_hash
        or snapshot.execution_slice_id != execution_slice.execution_slice_id
        or snapshot.execution_slice_hash != execution_slice.execution_slice_hash
        or snapshot.host_runtime_ref != execution_slice.host_runtime_ref
    ):
        raise ValueError("provider snapshot does not match exact AutoCAD Slice lineage")


class AutoCadWallThicknessProviderExecutionSnapshotBoundary:
    """把 AutoCAD 自己的 PlanningSnapshot revision 冻结进 Step31 binding metadata。"""

    def __init__(
        self,
        *,
        changeset_store,
        snapshot_registry,
        provider_snapshot_factory: Callable[[ExecutionSliceV2], ProviderExecutionSnapshotV2],
    ) -> None:
        if changeset_store is None or not callable(getattr(changeset_store, "get", None)):
            raise TypeError("changeset_store must provide get")
        if snapshot_registry is None:
            raise TypeError("snapshot_registry is required")
        if not callable(getattr(snapshot_registry, "get_snapshot_set", None)):
            raise TypeError("snapshot_registry must provide get_snapshot_set")
        if not callable(getattr(snapshot_registry, "get_snapshot", None)):
            raise TypeError("snapshot_registry must provide get_snapshot")
        if not callable(provider_snapshot_factory):
            raise TypeError("provider_snapshot_factory must be callable")
        self._changeset_store = changeset_store
        self._snapshot_registry = snapshot_registry
        self._provider_snapshot_factory = provider_snapshot_factory

    def __call__(self, execution_slice: ExecutionSliceV2) -> ProviderExecutionSnapshotV2:
        """为 exact AutoCAD Slice 发布 hash-bound expected revision。"""

        if not isinstance(execution_slice, ExecutionSliceV2):
            raise TypeError("execution_slice must be ExecutionSliceV2")
        if execution_slice.host_runtime_ref.host_type != "autocad":
            raise ValueError(
                "AutoCAD provider snapshot boundary requires an AutoCAD execution slice"
            )

        changeset = self._changeset_store.get(execution_slice.changeset_id)
        if (
            changeset.changeset_id != execution_slice.changeset_id
            or changeset.changeset_hash != execution_slice.changeset_hash
        ):
            raise ValueError("ExecutionSliceV2 ChangeSet lineage does not match owner truth")

        snapshot_set_ref = changeset.snapshot_set_ref
        snapshot_set = self._snapshot_registry.get_snapshot_set(
            snapshot_set_ref.snapshot_set_id
        )
        if (
            snapshot_set.snapshot_set_id != snapshot_set_ref.snapshot_set_id
            or snapshot_set.hash != snapshot_set_ref.snapshot_set_hash
        ):
            raise ValueError("ChangeSet SnapshotSet lineage does not match owner truth")
        if _environment_identity(snapshot_set.semantic_environment_ref) != _environment_identity(
            snapshot_set_ref.semantic_environment
        ):
            raise ValueError("SnapshotSet semantic environment does not match ChangeSet ref")

        candidates = []
        for snapshot_id in tuple(snapshot_set.member_snapshot_ids):
            snapshot = self._snapshot_registry.get_snapshot(snapshot_id)
            if (
                getattr(snapshot, "kind", None) is SnapshotKind.PLANNING
                and getattr(snapshot, "document_ref", None)
                == execution_slice.host_runtime_ref.document_ref
            ):
                candidates.append(snapshot)
        if len(candidates) != 1:
            raise ValueError(
                "AutoCAD execution document must resolve to exactly one PlanningSnapshot"
            )
        planning = candidates[0]
        planning_environment = _environment_identity(planning.semantic_environment_ref)
        if planning_environment != _environment_identity(snapshot_set.semantic_environment_ref):
            raise ValueError(
                "AutoCAD PlanningSnapshot semantic environment does not match SnapshotSet"
            )

        expected_revision = _canonical_revision(planning.base_host_revision)
        base_snapshot = self._provider_snapshot_factory(execution_slice)
        _require_exact_provider_snapshot(base_snapshot, execution_slice)

        materials: dict[str, ProviderBindingMaterial] = {}
        for fingerprint, material in base_snapshot.candidate_binding_materials.items():
            metadata = dict(material.native_binding_metadata)
            metadata["expected_revision"] = expected_revision
            materials[fingerprint] = replace(
                material,
                native_binding_metadata=metadata,
            )
        provisional = replace(
            base_snapshot,
            candidate_binding_materials=materials,
            snapshot_hash="0" * 64,
        )
        return replace(
            provisional,
            snapshot_hash=compute_provider_snapshot_hash_v2(provisional),
        )


def _expected_revision(binding) -> int:
    """读取已经进入 ProviderBindingV2 hash 的 planning revision。"""

    value = binding.native_binding_metadata.get("expected_revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            "AutoCAD binding requires hash-bound non-negative expected_revision"
        )
    return value


def _thickness_mm(unit) -> float:
    """只接受 canonical execution unit 中有限正 mm 墙厚。"""

    raw = unit.arguments.get("thickness")
    if not isinstance(raw, Mapping):
        raise TypeError("AutoCAD execution requires thickness argument mapping")
    value = raw.get("value")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        or raw.get("unit") != "mm"
    ):
        raise ValueError("AutoCAD execution requires finite positive mm thickness")
    return float(value)


def _validate_lineage(
    execution_slice: ExecutionSliceV2,
    authority: AdmittedExecutionAuthorityV2,
    binding_set: ProviderBindingSetV2,
    dispatch_context: HostDispatchContext,
):
    """在 Host 写 I/O 前闭合 Slice、Grant、Binding 与 durable dispatch lineage。"""

    if not isinstance(execution_slice, ExecutionSliceV2):
        raise TypeError("execution_slice must be ExecutionSliceV2")
    if not isinstance(authority, AdmittedExecutionAuthorityV2):
        raise TypeError("authority must be AdmittedExecutionAuthorityV2")
    if not isinstance(binding_set, ProviderBindingSetV2):
        raise TypeError("binding_set must be ProviderBindingSetV2")
    if not isinstance(dispatch_context, HostDispatchContext):
        raise TypeError("dispatch_context must be HostDispatchContext")
    if execution_slice.host_runtime_ref.host_type != "autocad":
        raise ValueError("AutoCAD execution port requires AutoCAD ExecutionSliceV2")
    if dispatch_context.execution_slice_hash != execution_slice.execution_slice_hash:
        raise ValueError("HostDispatchContext does not match exact AutoCAD Slice")

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
        raise ValueError("admitted authority does not match exact AutoCAD execution lineage")

    if len(execution_slice.execution_units) != 1 or len(binding_set.bindings) != 1:
        raise ValueError(
            "AutoCAD wall thickness execution requires exactly one unit and binding"
        )
    unit = execution_slice.execution_units[0]
    binding = binding_set.bindings[0]
    if (
        unit.canonical_operation != "set_wall_thickness.v1"
        or binding.canonical_operation != unit.canonical_operation
        or binding.execution_unit_hash != unit.execution_unit_hash
        or binding.execution_slice_hash != execution_slice.execution_slice_hash
        or binding.host_runtime_ref != execution_slice.host_runtime_ref
    ):
        raise ValueError("AutoCAD provider binding does not match exact execution unit")
    if len(unit.targets) != 1 or len(binding.native_targets) != 1:
        raise ValueError("AutoCAD wall thickness execution requires exactly one target")
    target = binding.native_targets[0]
    if (
        target.semantic_id != unit.targets[0]
        or target.host_type != "autocad"
        or target.document_ref != execution_slice.host_runtime_ref.document_ref
        or target.native_kind != "LWPOLYLINE"
    ):
        raise ValueError("AutoCAD native target does not match exact wall execution lineage")
    return unit, binding, target


def _number(value: object, field_name: str) -> float:
    """读取 Host response 中有限数字。"""

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{field_name} must be a finite number")
    return float(value)


def _effect_is_exact(
    payload: object,
    *,
    native_id: str,
    expected_width: float,
) -> bool:
    """确认 Host success response 只描述 exact target 的 wall-width property 修改。"""

    if not isinstance(payload, Mapping):
        return False
    before = payload.get("beforeWidths")
    after = payload.get("widths")
    if (
        payload.get("updated") != 1
        or payload.get("unit") != "mm"
        or not isinstance(before, Mapping)
        or not isinstance(after, Mapping)
        or set(before) != {native_id}
        or set(after) != {native_id}
    ):
        return False
    try:
        before_width = _number(before[native_id], "beforeWidths target")
        after_width = _number(after[native_id], "widths target")
    except ValueError:
        return False
    return before_width >= 0 and abs(after_width - expected_width) <= 1e-6


def _actual_delta(
    *,
    execution_slice: ExecutionSliceV2,
    authority: AdmittedExecutionAuthorityV2,
    binding_set: ProviderBindingSetV2,
    revision_before: int,
    revision_after: int,
    command_id: str,
) -> ActualDelta:
    """把 exact native wall property effect 投影为 provider-neutral ActualDelta。"""

    unit = execution_slice.execution_units[0]
    change_draft = ActualChange(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id=unit.targets[0],
        canonical_kind="ifc:IfcWall",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
        source_execution_unit_hash=unit.execution_unit_hash,
        actual_change_hash="0" * 64,
    )
    change = replace(
        change_draft,
        actual_change_hash=compute_actual_change_hash(change_draft),
    )
    delta_draft = ActualDelta(
        actual_delta_id=f"AD-AUTOCAD-{command_id}",
        grant_hash=authority.grant_hash,
        binding_set_hash=binding_set.binding_set_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=revision_before,
        revision_after=revision_after,
        changes=(change,),
        actual_delta_hash="0" * 64,
    )
    return replace(
        delta_draft,
        actual_delta_hash=compute_actual_delta_hash(delta_draft),
    )


class AutoCadWallThicknessExecutionPort:
    """把 admitted AutoCAD Slice 转交给窄 Host mutation port 并规范化 outcome。"""

    def __init__(
        self,
        mutation_port,
        *,
        clock: Callable[[], str] | None = None,
    ) -> None:
        if mutation_port is None or not callable(getattr(mutation_port, "execute", None)):
            raise TypeError("mutation_port must provide execute")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._mutation_port = mutation_port
        self._clock = clock or _utc_now

    def execute(
        self,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
        dispatch_context: HostDispatchContext,
    ) -> HostExecutionResult:
        """执行 exact admitted wall-thickness logical dispatch。"""

        unit, binding, target = _validate_lineage(
            execution_slice,
            authority,
            binding_set,
            dispatch_context,
        )
        expected_revision = _expected_revision(binding)
        thickness = _thickness_mm(unit)
        try:
            result = self._mutation_port.execute(
                native_id=target.native_id,
                thickness_mm=thickness,
                idempotency_key=dispatch_context.idempotency_key,
                expected_revision=expected_revision,
            )
        except (ConnectionError, OSError, TimeoutError):
            return HostFailed(
                phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
                failure_ref="AUTOCAD_COMMIT_STATE_UNKNOWN",
                failed_at=self._clock(),
            )

        occurred_at = self._clock()
        if not bool(getattr(result, "ok", False)):
            error = getattr(result, "error", None)
            code = getattr(error, "error_code", None)
            if code == "REVISION_CONFLICT":
                return HostFailed(
                    phase=HostFailurePhase.BEFORE_COMMIT,
                    failure_ref="REVISION_CONFLICT",
                    failed_at=occurred_at,
                )
            return HostFailed(
                phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
                failure_ref=(
                    code
                    if isinstance(code, str) and code.strip()
                    else "AUTOCAD_COMMIT_STATE_UNKNOWN"
                ),
                failed_at=occurred_at,
            )

        revision_after = getattr(result, "revision_after", None)
        if (
            isinstance(revision_after, bool)
            or not isinstance(revision_after, int)
            or revision_after <= expected_revision
            or not _effect_is_exact(
                getattr(result, "payload", None),
                native_id=target.native_id,
                expected_width=thickness,
            )
        ):
            return HostFailed(
                phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
                failure_ref="AUTOCAD_COMMIT_EVIDENCE_MISMATCH",
                failed_at=occurred_at,
            )
        command_id = getattr(result, "command_id", None)
        if not isinstance(command_id, str) or not command_id.strip():
            return HostFailed(
                phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
                failure_ref="AUTOCAD_COMMIT_EVIDENCE_MISMATCH",
                failed_at=occurred_at,
            )
        return HostCommitted(
            actual_delta=_actual_delta(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                revision_before=expected_revision,
                revision_after=revision_after,
                command_id=command_id.strip(),
            ),
            committed_at=occurred_at,
        )


__all__ = [
    "AutoCadWallThicknessExecutionPort",
    "AutoCadWallThicknessProviderExecutionSnapshotBoundary",
]
