"""Phase I 面向 materialization 的 Step31 V2 provider/native binding。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from design_changeset import canonical_hash
from design_execution_planning import ExecutionSliceV2, ExecutionUnitV2, HostRuntimeRef
from design_materialization_planning import MaterializationPlan

from .contracts import (
    NativeTargetBindingEvidence,
    ProviderBindingError,
    ProviderBindingMaterial,
    ProviderExecutionCandidate,
    ProviderPreconditionBinding,
    _digest,
    _readonly_mapping,
    _text,
    _typed_tuple,
    _utc_timestamp,
)
from .hashing import (
    compute_candidate_fingerprint,
    compute_host_binding_fingerprint,
)
from .resolver import (
    _select_candidate,
    _validate_candidate_schema,
    _validate_material_native_targets,
    _validate_material_preconditions,
    _validate_provider_arguments,
)


def _error(code: str, message: str) -> None:
    """统一抛出 Step31 V2 的稳定领域错误。"""
    raise ProviderBindingError(code, message)


def _runtime_ref_payload(ref: HostRuntimeRef) -> dict[str, str]:
    """把运行时 Host 引用投影为稳定哈希载荷。"""
    return {
        "host_type": ref.host_type,
        "host_instance_id": ref.host_instance_id,
        "document_ref": ref.document_ref,
    }


def _native_target_payload(value: NativeTargetBindingEvidence) -> dict[str, str]:
    """把既有 Host binding evidence 投影为稳定哈希载荷。"""
    return {
        "semantic_id": value.semantic_id,
        "host_type": value.host_type,
        "document_ref": value.document_ref,
        "native_id": value.native_id,
        "native_kind": value.native_kind,
        "host_binding_fingerprint": value.host_binding_fingerprint,
    }


def _native_target_sort_key(value: dict[str, str]) -> tuple[str, ...]:
    """冻结 native target 的跨运行排序。"""
    return (
        value["semantic_id"],
        value["host_type"],
        value["document_ref"],
        value["native_id"],
        value["native_kind"],
        value["host_binding_fingerprint"],
    )


def _provider_precondition_payload(
    value: ProviderPreconditionBinding,
) -> dict[str, object]:
    """把 provider precondition 投影为稳定哈希载荷。"""
    return {
        "source_precondition_fingerprint": value.source_precondition_fingerprint,
        "provider_precondition": value.provider_precondition,
    }


def _material_payload(material: ProviderBindingMaterial) -> dict[str, object]:
    """对已冻结的 adapter binding material 做内容寻址投影。"""
    return {
        "native_targets": sorted(
            (_native_target_payload(item) for item in material.native_targets),
            key=_native_target_sort_key,
        ),
        "provider_arguments": material.provider_arguments,
        "provider_preconditions": sorted(
            (
                _provider_precondition_payload(item)
                for item in material.provider_preconditions
            ),
            key=lambda item: (
                item["source_precondition_fingerprint"],
                canonical_hash(item["provider_precondition"]),
            ),
        ),
        "native_binding_metadata": material.native_binding_metadata,
    }


@dataclass(frozen=True, slots=True)
class ProviderExecutionSnapshotV2:
    """绑定一个精确 materialization Slice 的不可变 provider 运行时证据。"""

    snapshot_id: str
    materialization_id: str
    materialization_plan_hash: str
    execution_slice_id: str
    execution_slice_hash: str
    host_runtime_ref: HostRuntimeRef
    native_target_bindings: tuple[NativeTargetBindingEvidence, ...]
    provider_candidates: tuple[ProviderExecutionCandidate, ...]
    candidate_binding_materials: Mapping[str, ProviderBindingMaterial]
    valid_until: str
    snapshot_hash: str

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id",
            "materialization_id",
            "execution_slice_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "materialization_plan_hash",
            "execution_slice_hash",
            "snapshot_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        if not isinstance(self.host_runtime_ref, HostRuntimeRef):
            raise TypeError("host_runtime_ref must be HostRuntimeRef")
        object.__setattr__(
            self,
            "native_target_bindings",
            _typed_tuple(
                self.native_target_bindings,
                NativeTargetBindingEvidence,
                "native_target_bindings",
            ),
        )
        object.__setattr__(
            self,
            "provider_candidates",
            _typed_tuple(
                self.provider_candidates,
                ProviderExecutionCandidate,
                "provider_candidates",
                required=True,
            ),
        )
        if not isinstance(self.candidate_binding_materials, Mapping):
            raise TypeError("candidate_binding_materials must be a mapping")
        materials: dict[str, ProviderBindingMaterial] = {}
        for fingerprint, material in self.candidate_binding_materials.items():
            key = _digest(fingerprint, "candidate fingerprint")
            if not isinstance(material, ProviderBindingMaterial):
                raise TypeError(
                    "candidate_binding_materials must contain ProviderBindingMaterial values"
                )
            materials[key] = material
        object.__setattr__(
            self,
            "candidate_binding_materials",
            MappingProxyType(materials),
        )
        object.__setattr__(
            self,
            "valid_until",
            _utc_timestamp(self.valid_until, "valid_until"),
        )


@dataclass(frozen=True, slots=True)
class ProviderBindingV2:
    """一个 ExecutionUnitV2 对精确 provider/native identity 的不可变绑定。"""

    binding_id: str
    materialization_id: str
    materialization_plan_hash: str
    execution_unit_id: str
    execution_unit_hash: str
    execution_slice_id: str
    execution_slice_hash: str
    host_runtime_ref: HostRuntimeRef
    canonical_operation: str
    provider_server: str
    provider_tool: str
    provider_version: str
    selected_candidate_fingerprint: str
    input_adapter_version: str
    native_targets: tuple[NativeTargetBindingEvidence, ...]
    provider_arguments: Mapping[str, Any]
    provider_preconditions: tuple[ProviderPreconditionBinding, ...]
    native_binding_metadata: Mapping[str, Any]
    verification_contract: Mapping[str, Any]
    rollback_contract: Mapping[str, Any]
    binding_expires_at: str
    binding_hash: str

    def __post_init__(self) -> None:
        for name in (
            "binding_id",
            "materialization_id",
            "execution_unit_id",
            "execution_slice_id",
            "canonical_operation",
            "provider_server",
            "provider_tool",
            "provider_version",
            "input_adapter_version",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "materialization_plan_hash",
            "execution_unit_hash",
            "execution_slice_hash",
            "selected_candidate_fingerprint",
            "binding_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        if not isinstance(self.host_runtime_ref, HostRuntimeRef):
            raise TypeError("host_runtime_ref must be HostRuntimeRef")
        object.__setattr__(
            self,
            "native_targets",
            _typed_tuple(
                self.native_targets,
                NativeTargetBindingEvidence,
                "native_targets",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "provider_arguments",
            _readonly_mapping(self.provider_arguments, "provider_arguments"),
        )
        object.__setattr__(
            self,
            "provider_preconditions",
            _typed_tuple(
                self.provider_preconditions,
                ProviderPreconditionBinding,
                "provider_preconditions",
            ),
        )
        for name in (
            "native_binding_metadata",
            "verification_contract",
            "rollback_contract",
        ):
            object.__setattr__(
                self,
                name,
                _readonly_mapping(getattr(self, name), name),
            )
        object.__setattr__(
            self,
            "binding_expires_at",
            _utc_timestamp(self.binding_expires_at, "binding_expires_at"),
        )


@dataclass(frozen=True, slots=True)
class ProviderBindingSetV2:
    """一个 REQUIRED materialization Slice 的完整 provider binding 集。"""

    binding_set_id: str
    materialization_id: str
    materialization_plan_hash: str
    execution_slice_id: str
    execution_slice_hash: str
    provider_execution_snapshot_id: str
    provider_execution_snapshot_hash: str
    bindings: tuple[ProviderBindingV2, ...]
    binding_set_hash: str

    def __post_init__(self) -> None:
        for name in (
            "binding_set_id",
            "materialization_id",
            "execution_slice_id",
            "provider_execution_snapshot_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "materialization_plan_hash",
            "execution_slice_hash",
            "provider_execution_snapshot_hash",
            "binding_set_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "bindings",
            _typed_tuple(
                self.bindings,
                ProviderBindingV2,
                "bindings",
                required=True,
            ),
        )


def compute_provider_snapshot_hash_v2(snapshot: ProviderExecutionSnapshotV2) -> str:
    """计算绑定 materialization lineage 的 V2 provider snapshot hash。"""
    if not isinstance(snapshot, ProviderExecutionSnapshotV2):
        raise TypeError("snapshot must be ProviderExecutionSnapshotV2")
    candidates = sorted(
        (
            {
                "candidate_fingerprint": candidate.candidate_fingerprint,
                "candidate_semantic_fingerprint": compute_candidate_fingerprint(candidate),
            }
            for candidate in snapshot.provider_candidates
        ),
        key=lambda item: (
            item["candidate_fingerprint"],
            item["candidate_semantic_fingerprint"],
        ),
    )
    materials = [
        {
            "candidate_fingerprint": fingerprint,
            "material": _material_payload(material),
        }
        for fingerprint, material in snapshot.candidate_binding_materials.items()
    ]
    materials.sort(key=lambda item: item["candidate_fingerprint"])
    return canonical_hash(
        {
            "version": "PROVIDER_EXECUTION_SNAPSHOT_V2",
            "materialization_id": snapshot.materialization_id,
            "materialization_plan_hash": snapshot.materialization_plan_hash,
            "execution_slice_hash": snapshot.execution_slice_hash,
            "host_runtime_ref": _runtime_ref_payload(snapshot.host_runtime_ref),
            "native_target_bindings": sorted(
                (
                    _native_target_payload(item)
                    for item in snapshot.native_target_bindings
                ),
                key=_native_target_sort_key,
            ),
            "provider_candidates": candidates,
            "candidate_binding_materials": materials,
            "valid_until": snapshot.valid_until,
        }
    )


def _compute_binding_hash_v2(
    *,
    execution_slice: ExecutionSliceV2,
    unit: ExecutionUnitV2,
    selected: ProviderExecutionCandidate,
    material: ProviderBindingMaterial,
    binding_expires_at: str,
) -> str:
    """计算单个 V2 provider binding 的 materialization-aware hash。"""
    return canonical_hash(
        {
            "version": "PROVIDER_BINDING_V2",
            "materialization_id": execution_slice.materialization_id,
            "materialization_plan_hash": execution_slice.materialization_plan_hash,
            "execution_unit_hash": unit.execution_unit_hash,
            "execution_slice_hash": execution_slice.execution_slice_hash,
            "host_runtime_ref": _runtime_ref_payload(execution_slice.host_runtime_ref),
            "canonical_operation": unit.canonical_operation,
            "provider_server": selected.provider_server,
            "provider_tool": selected.provider_tool,
            "provider_version": selected.provider_version,
            "selected_candidate_fingerprint": selected.candidate_fingerprint,
            "input_adapter_version": selected.input_adapter_version,
            "native_targets": sorted(
                (_native_target_payload(item) for item in material.native_targets),
                key=_native_target_sort_key,
            ),
            "provider_arguments": material.provider_arguments,
            "provider_preconditions": sorted(
                (
                    _provider_precondition_payload(item)
                    for item in material.provider_preconditions
                ),
                key=lambda item: (
                    item["source_precondition_fingerprint"],
                    canonical_hash(item["provider_precondition"]),
                ),
            ),
            "native_binding_metadata": material.native_binding_metadata,
            "verification_contract": selected.verification_contract,
            "rollback_contract": selected.rollback_contract,
            "binding_expires_at": binding_expires_at,
        }
    )


def _compute_binding_set_hash_v2(
    *,
    execution_slice: ExecutionSliceV2,
    provider_execution_snapshot_hash: str,
    binding_hashes: Sequence[str],
) -> str:
    """计算一个 materialization Slice 的完整 V2 binding-set hash。"""
    return canonical_hash(
        {
            "version": "PROVIDER_BINDING_SET_V2",
            "materialization_id": execution_slice.materialization_id,
            "materialization_plan_hash": execution_slice.materialization_plan_hash,
            "execution_slice_hash": execution_slice.execution_slice_hash,
            "host_runtime_ref": _runtime_ref_payload(execution_slice.host_runtime_ref),
            "provider_execution_snapshot_hash": provider_execution_snapshot_hash,
            "binding_hashes": sorted(binding_hashes),
        }
    )


def _validate_snapshot_lineage(
    execution_slice: ExecutionSliceV2,
    snapshot: ProviderExecutionSnapshotV2,
) -> None:
    """验证 snapshot 与 exact materialization Slice 的全部 lineage join。"""
    if (
        snapshot.materialization_id != execution_slice.materialization_id
        or snapshot.materialization_plan_hash
        != execution_slice.materialization_plan_hash
        or snapshot.execution_slice_id != execution_slice.execution_slice_id
        or snapshot.execution_slice_hash != execution_slice.execution_slice_hash
        or snapshot.host_runtime_ref != execution_slice.host_runtime_ref
    ):
        _error(
            "MATERIALIZATION_BINDING_MISMATCH",
            "provider snapshot does not bind the exact materialization Slice",
        )


def _native_bindings_by_semantic_id_v2(
    execution_slice: ExecutionSliceV2,
    snapshot: ProviderExecutionSnapshotV2,
) -> dict[str, NativeTargetBindingEvidence]:
    """按 semantic id 重建唯一 native identity，并在 owner 边界 fail-closed。"""
    required = {
        target
        for unit in execution_slice.execution_units
        for target in unit.targets
    }
    if not snapshot.native_target_bindings:
        _error(
            "IDENTITY_BINDING_UNRESOLVED",
            "required materialization has no native target binding",
        )

    bindings: dict[str, NativeTargetBindingEvidence] = {}
    for row in snapshot.native_target_bindings:
        if (
            row.semantic_id not in required
            or row.host_type != execution_slice.host_runtime_ref.host_type
            or row.document_ref != execution_slice.host_runtime_ref.document_ref
        ):
            _error(
                "MATERIALIZATION_BINDING_MISMATCH",
                "native binding semantic/Host/document does not match materialization Slice",
            )
        if compute_host_binding_fingerprint(row) != row.host_binding_fingerprint:
            _error(
                "IDENTITY_BINDING_CONFLICT",
                "native identity does not match its existing Host binding fingerprint",
            )
        if row.semantic_id in bindings:
            _error(
                "IDENTITY_BINDING_CONFLICT",
                f"duplicate native binding for semantic target {row.semantic_id}",
            )
        bindings[row.semantic_id] = row

    supplied = set(bindings)
    missing = required - supplied
    extraneous = supplied - required
    if missing and not extraneous:
        _error(
            "IDENTITY_BINDING_UNRESOLVED",
            f"native bindings unresolved for {sorted(missing)}",
        )
    if missing or extraneous:
        _error(
            "MATERIALIZATION_BINDING_MISMATCH",
            "native binding semantic targets do not match materialization Slice",
        )
    return bindings


def _validate_candidates_v2(
    execution_slice: ExecutionSliceV2,
    snapshot: ProviderExecutionSnapshotV2,
) -> tuple[ProviderExecutionCandidate, ...]:
    """验证候选语义、schema 与 candidate fingerprint。"""
    valid_operations = {
        unit.canonical_operation for unit in execution_slice.execution_units
    }
    candidates = tuple(snapshot.provider_candidates)
    for candidate in candidates:
        if candidate.canonical_operation not in valid_operations:
            _error(
                "PROVIDER_CANDIDATE_INVALID",
                "provider candidate operation is unrelated to materialization Slice",
            )
        _validate_candidate_schema(candidate)
        if compute_candidate_fingerprint(candidate) != candidate.candidate_fingerprint:
            _error(
                "PROVIDER_CANDIDATE_INVALID",
                "provider candidate fingerprint mismatch",
            )
    return candidates


def _material_for_candidate(
    snapshot: ProviderExecutionSnapshotV2,
    candidate: ProviderExecutionCandidate,
) -> ProviderBindingMaterial:
    """读取候选对应的已冻结 adapter material。"""
    material = snapshot.candidate_binding_materials.get(
        candidate.candidate_fingerprint
    )
    if material is None:
        _error(
            "PROVIDER_BINDING_ADAPTATION_FAILED",
            "selected provider candidate has no frozen binding material",
        )
    return material


def _materialize_binding_v2(
    *,
    execution_slice: ExecutionSliceV2,
    snapshot: ProviderExecutionSnapshotV2,
    unit: ExecutionUnitV2,
    selected: ProviderExecutionCandidate,
    material: ProviderBindingMaterial,
) -> ProviderBindingV2:
    """从冻结 evidence 构造一个 V2 provider binding。"""
    binding_hash = _compute_binding_hash_v2(
        execution_slice=execution_slice,
        unit=unit,
        selected=selected,
        material=material,
        binding_expires_at=snapshot.valid_until,
    )
    return ProviderBindingV2(
        binding_id=f"PBV2-{binding_hash[:12]}",
        materialization_id=execution_slice.materialization_id,
        materialization_plan_hash=execution_slice.materialization_plan_hash,
        execution_unit_id=unit.execution_unit_id,
        execution_unit_hash=unit.execution_unit_hash,
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        host_runtime_ref=execution_slice.host_runtime_ref,
        canonical_operation=unit.canonical_operation,
        provider_server=selected.provider_server,
        provider_tool=selected.provider_tool,
        provider_version=selected.provider_version,
        selected_candidate_fingerprint=selected.candidate_fingerprint,
        input_adapter_version=selected.input_adapter_version,
        native_targets=material.native_targets,
        provider_arguments=material.provider_arguments,
        provider_preconditions=material.provider_preconditions,
        native_binding_metadata=material.native_binding_metadata,
        verification_contract=selected.verification_contract,
        rollback_contract=selected.rollback_contract,
        binding_expires_at=snapshot.valid_until,
        binding_hash=binding_hash,
    )


def _validate_binding_hash_v2(
    binding: ProviderBindingV2,
    execution_slice: ExecutionSliceV2,
    unit: ExecutionUnitV2,
) -> None:
    """重建一个 V2 binding hash 并验证 exact Slice/unit lineage。"""
    if (
        binding.materialization_id != execution_slice.materialization_id
        or binding.materialization_plan_hash
        != execution_slice.materialization_plan_hash
        or binding.execution_slice_id != execution_slice.execution_slice_id
        or binding.execution_slice_hash != execution_slice.execution_slice_hash
        or binding.host_runtime_ref != execution_slice.host_runtime_ref
        or binding.execution_unit_id != unit.execution_unit_id
        or binding.execution_unit_hash != unit.execution_unit_hash
        or binding.canonical_operation != unit.canonical_operation
    ):
        _error(
            "MATERIALIZATION_BINDING_MISMATCH",
            "provider binding lineage does not match exact materialization Slice",
        )
    material = ProviderBindingMaterial(
        native_targets=binding.native_targets,
        provider_arguments=binding.provider_arguments,
        provider_preconditions=binding.provider_preconditions,
        native_binding_metadata=binding.native_binding_metadata,
    )
    expected = canonical_hash(
        {
            "version": "PROVIDER_BINDING_V2",
            "materialization_id": binding.materialization_id,
            "materialization_plan_hash": binding.materialization_plan_hash,
            "execution_unit_hash": binding.execution_unit_hash,
            "execution_slice_hash": binding.execution_slice_hash,
            "host_runtime_ref": _runtime_ref_payload(binding.host_runtime_ref),
            "canonical_operation": binding.canonical_operation,
            "provider_server": binding.provider_server,
            "provider_tool": binding.provider_tool,
            "provider_version": binding.provider_version,
            "selected_candidate_fingerprint": binding.selected_candidate_fingerprint,
            "input_adapter_version": binding.input_adapter_version,
            "native_targets": sorted(
                (_native_target_payload(item) for item in material.native_targets),
                key=_native_target_sort_key,
            ),
            "provider_arguments": material.provider_arguments,
            "provider_preconditions": sorted(
                (
                    _provider_precondition_payload(item)
                    for item in material.provider_preconditions
                ),
                key=lambda item: (
                    item["source_precondition_fingerprint"],
                    canonical_hash(item["provider_precondition"]),
                ),
            ),
            "native_binding_metadata": material.native_binding_metadata,
            "verification_contract": binding.verification_contract,
            "rollback_contract": binding.rollback_contract,
            "binding_expires_at": binding.binding_expires_at,
        }
    )
    if (
        binding.binding_hash != expected
        or binding.binding_id != f"PBV2-{expected[:12]}"
    ):
        _error(
            "PROVIDER_BINDING_HASH_MISMATCH",
            "provider binding V2 hash/id mismatch",
        )


def resolve_provider_bindings_v2(
    execution_slice: ExecutionSliceV2,
    snapshot: ProviderExecutionSnapshotV2,
) -> ProviderBindingSetV2:
    """为一个 exact materialization Slice 解析确定性 provider/native binding。"""
    if not isinstance(execution_slice, ExecutionSliceV2):
        raise TypeError("execution_slice must be ExecutionSliceV2")
    if not isinstance(snapshot, ProviderExecutionSnapshotV2):
        raise TypeError("snapshot must be ProviderExecutionSnapshotV2")

    _validate_snapshot_lineage(execution_slice, snapshot)
    native_by_semantic_id = _native_bindings_by_semantic_id_v2(
        execution_slice,
        snapshot,
    )
    candidates = _validate_candidates_v2(execution_slice, snapshot)
    if compute_provider_snapshot_hash_v2(snapshot) != snapshot.snapshot_hash:
        _error(
            "PROVIDER_SNAPSHOT_HASH_MISMATCH",
            "provider execution snapshot V2 hash mismatch",
        )

    bindings: list[ProviderBindingV2] = []
    for unit in execution_slice.execution_units:
        unit_native_targets = tuple(
            native_by_semantic_id[target] for target in unit.targets
        )
        selected = _select_candidate(unit, unit_native_targets, candidates)
        material = _material_for_candidate(snapshot, selected)
        _validate_material_native_targets(
            unit,
            material,
            native_by_semantic_id,
        )
        _validate_material_preconditions(unit, material)
        _validate_provider_arguments(selected, material)
        bindings.append(
            _materialize_binding_v2(
                execution_slice=execution_slice,
                snapshot=snapshot,
                unit=unit,
                selected=selected,
                material=material,
            )
        )

    normalized = tuple(
        sorted(bindings, key=lambda item: item.execution_unit_hash)
    )
    binding_set_hash = _compute_binding_set_hash_v2(
        execution_slice=execution_slice,
        provider_execution_snapshot_hash=snapshot.snapshot_hash,
        binding_hashes=tuple(item.binding_hash for item in normalized),
    )
    binding_set = ProviderBindingSetV2(
        binding_set_id=f"PBSV2-{binding_set_hash[:12]}",
        materialization_id=execution_slice.materialization_id,
        materialization_plan_hash=execution_slice.materialization_plan_hash,
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        provider_execution_snapshot_id=snapshot.snapshot_id,
        provider_execution_snapshot_hash=snapshot.snapshot_hash,
        bindings=normalized,
        binding_set_hash=binding_set_hash,
    )
    validate_provider_binding_set_v2(binding_set, execution_slice)
    return binding_set


def validate_provider_binding_set_v2(
    binding_set: ProviderBindingSetV2,
    execution_slice: ExecutionSliceV2,
) -> None:
    """重建一个 V2 binding set 并验证 exact materialization/unit 覆盖。"""
    if not isinstance(binding_set, ProviderBindingSetV2):
        raise TypeError("binding_set must be ProviderBindingSetV2")
    if not isinstance(execution_slice, ExecutionSliceV2):
        raise TypeError("execution_slice must be ExecutionSliceV2")
    if (
        binding_set.materialization_id != execution_slice.materialization_id
        or binding_set.materialization_plan_hash
        != execution_slice.materialization_plan_hash
        or binding_set.execution_slice_id != execution_slice.execution_slice_id
        or binding_set.execution_slice_hash != execution_slice.execution_slice_hash
    ):
        _error(
            "MATERIALIZATION_BINDING_MISMATCH",
            "binding set does not match exact materialization Slice",
        )

    units = {
        unit.execution_unit_id: unit
        for unit in execution_slice.execution_units
    }
    bindings = {
        binding.execution_unit_id: binding
        for binding in binding_set.bindings
    }
    if (
        len(bindings) != len(binding_set.bindings)
        or set(bindings) != set(units)
    ):
        _error(
            "MATERIALIZATION_BINDING_MISMATCH",
            "binding set does not exactly cover materialization execution units",
        )
    for unit_id, binding in bindings.items():
        _validate_binding_hash_v2(
            binding,
            execution_slice,
            units[unit_id],
        )

    expected = _compute_binding_set_hash_v2(
        execution_slice=execution_slice,
        provider_execution_snapshot_hash=(
            binding_set.provider_execution_snapshot_hash
        ),
        binding_hashes=tuple(
            binding.binding_hash for binding in binding_set.bindings
        ),
    )
    if (
        binding_set.binding_set_hash != expected
        or binding_set.binding_set_id != f"PBSV2-{expected[:12]}"
    ):
        _error(
            "PROVIDER_BINDING_SET_INVALID",
            "provider binding set V2 hash/id mismatch",
        )


def validate_cross_materialization_identity(
    plan: MaterializationPlan,
    binding_sets: Sequence[ProviderBindingSetV2],
) -> None:
    """验证一个 MaterializationPlan 的 REQUIRED binding set 闭世界覆盖。"""
    if not isinstance(plan, MaterializationPlan):
        raise TypeError("plan must be MaterializationPlan")
    normalized = tuple(binding_sets)
    if any(
        not isinstance(binding_set, ProviderBindingSetV2)
        for binding_set in normalized
    ):
        raise TypeError("binding_sets must contain ProviderBindingSetV2 values")

    expected_ids = {
        intent.materialization_id for intent in plan.intents
    }
    supplied_ids = [
        binding_set.materialization_id for binding_set in normalized
    ]
    if (
        len(set(supplied_ids)) != len(supplied_ids)
        or set(supplied_ids) != expected_ids
        or any(
            binding_set.materialization_plan_hash
            != plan.materialization_plan_hash
            for binding_set in normalized
        )
    ):
        _error(
            "MATERIALIZATION_BINDING_MISMATCH",
            "provider binding sets do not exactly cover the MaterializationPlan",
        )

    intent_by_id = {
        intent.materialization_id: intent for intent in plan.intents
    }
    for binding_set in normalized:
        intent = intent_by_id[binding_set.materialization_id]
        for binding in binding_set.bindings:
            native_semantic_ids = {
                target.semantic_id for target in binding.native_targets
            }
            if (
                binding.materialization_id != intent.materialization_id
                or binding.materialization_plan_hash
                != plan.materialization_plan_hash
                or native_semantic_ids != set(intent.semantic_targets)
            ):
                _error(
                    "MATERIALIZATION_BINDING_MISMATCH",
                    "binding native identity does not match materialization intent",
                )


__all__ = [
    "ProviderBindingSetV2",
    "ProviderBindingV2",
    "ProviderExecutionSnapshotV2",
    "compute_provider_snapshot_hash_v2",
    "resolve_provider_bindings_v2",
    "validate_cross_materialization_identity",
    "validate_provider_binding_set_v2",
]
