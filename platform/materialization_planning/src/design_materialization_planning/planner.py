"""Phase I provider-neutral 确定性 MaterializationPlanner。"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum

from design_approval_scope import (
    ApprovalScopeBoundaryV2,
    validate_approval_scope_boundary_v2,
)
from design_changeset import (
    CanonicalChangeOperation,
    CanonicalChangeSet,
    compute_operation_semantic_hash,
    compute_scope_rule_fingerprint,
    validate_changeset_integrity_v2,
)
from design_convergence import (
    ConvergenceComparisonProfile,
    compute_convergence_profile_hash,
)
from design_materialization_topology import (
    MaterializationRequirement,
    MaterializationTopologyError,
    MaterializationTopologySnapshot,
    validate_materialization_topology_snapshot,
)

from .contracts import (
    MaterializationIntent,
    MaterializationPlan,
    MaterializationPlanningError,
    MaterializationPlanningRequest,
)
from .hashing import (
    compute_materialization_intent_hash,
    compute_materialization_plan_hash,
    compute_required_set_hash,
)


def _error(code: str, message: str) -> None:
    """统一抛出稳定错误码。"""
    raise MaterializationPlanningError(code, message)


def _rule_index(boundary: ApprovalScopeBoundaryV2) -> dict[str, object]:
    """建立 Step28 规则索引并拒绝跨规则类别的重复 id。"""
    result: dict[str, object] = {}
    for rule in (
        *boundary.existing_entity_rules,
        *boundary.creation_rules,
        *boundary.deletion_rules,
    ):
        if rule.rule_id in result:
            _error(
                "MATERIALIZATION_SCOPE_LINEAGE_INVALID",
                f"duplicate Step28 scope rule id: {rule.rule_id}",
            )
        result[rule.rule_id] = rule
    return result


def _operation_hash(
    operation: CanonicalChangeOperation,
    boundary: ApprovalScopeBoundaryV2,
) -> str:
    """调用 Step29 公共 hash primitive 重建 source operation 的精确语义哈希。"""
    rules = _rule_index(boundary)
    try:
        fingerprints = tuple(
            sorted(
                compute_scope_rule_fingerprint(rules[rule_id])
                for rule_id in operation.scope_rule_ids
            )
        )
    except KeyError as exc:
        _error(
            "MATERIALIZATION_SCOPE_LINEAGE_INVALID",
            f"unresolved Step28 scope rule: {exc.args[0]}",
        )
    operation_hash = compute_operation_semantic_hash(
        origin=operation.origin,
        canonical_operation=operation.canonical_operation,
        canonical_operation_version=operation.canonical_operation_version,
        canonical_definition_fingerprint=operation.canonical_definition_fingerprint,
        targets=operation.targets,
        arguments=operation.arguments,
        expected_effects=operation.expected_effects,
        scope_rule_fingerprints=fingerprints,
        source_evidence=operation.source_evidence,
        expected_existence_effects=operation.expected_existence_effects,
    )
    if operation.operation_id != f"COP-{operation_hash[:12]}":
        _error(
            "MATERIALIZATION_CHANGESET_LINEAGE_INVALID",
            "source operation id does not match its Step29 semantic hash",
        )
    return operation_hash


def _effect_values(operation: CanonicalChangeOperation) -> tuple[str, ...]:
    """把 canonical effect 枚举规范化为稳定字符串。"""
    return tuple(
        sorted(
            {
                effect.value if isinstance(effect, Enum) else str(effect)
                for effect in operation.expected_effects
            }
        )
    )


def _validate_convergence_profile(profile: ConvergenceComparisonProfile) -> None:
    """重算 Task4 profile hash，拒绝被替换或陈旧的比较契约。"""
    expected = compute_convergence_profile_hash(
        profile.profile_version,
        profile.field_rules,
    )
    if expected != profile.profile_hash:
        _error(
            "CONVERGENCE_PROFILE_INTEGRITY_INVALID",
            "convergence profile does not match its content hash",
        )


def _validate_lineage(request: MaterializationPlanningRequest) -> None:
    """按 owner 顺序验证 Step28/29、拓扑和 convergence lineage。"""
    if not isinstance(request.canonical_changeset, CanonicalChangeSet):
        raise TypeError("canonical_changeset must be CanonicalChangeSet")
    if not isinstance(request.approval_scope_boundary, ApprovalScopeBoundaryV2):
        raise TypeError("approval_scope_boundary must be ApprovalScopeBoundaryV2")
    if not isinstance(request.topology_snapshot, MaterializationTopologySnapshot):
        raise TypeError("topology_snapshot must be MaterializationTopologySnapshot")
    if not isinstance(request.convergence_profile, ConvergenceComparisonProfile):
        raise TypeError("convergence_profile must be ConvergenceComparisonProfile")

    boundary = request.approval_scope_boundary
    topology = request.topology_snapshot
    validate_approval_scope_boundary_v2(boundary)
    validate_changeset_integrity_v2(request.canonical_changeset, boundary)
    try:
        validate_materialization_topology_snapshot(topology)
    except MaterializationTopologyError as exc:
        _error(
            "MATERIALIZATION_TOPOLOGY_MISMATCH",
            f"materialization topology integrity failed: {exc.code}",
        )
    if boundary.topology_snapshot_hash != topology.topology_snapshot_hash:
        _error(
            "MATERIALIZATION_TOPOLOGY_MISMATCH",
            "ApprovalScopeBoundaryV2 does not bind this topology snapshot",
        )
    _validate_convergence_profile(request.convergence_profile)


def _operations(changeset: CanonicalChangeSet) -> tuple[CanonicalChangeOperation, ...]:
    """返回完整 Step29 canonical operation 集合。"""
    return (changeset.root_operation, *changeset.derived_operations)


def _validate_required_slot_coverage(
    operations: tuple[CanonicalChangeOperation, ...],
    topology: MaterializationTopologySnapshot,
) -> None:
    """先验证 REQUIRED 槽 closed-world 与 target 全覆盖，再检查 MVP cardinality。"""
    operation_targets = {
        target
        for operation in operations
        for target in operation.targets
    }
    required_slots = tuple(
        slot
        for slot in topology.slots
        if slot.requirement is MaterializationRequirement.REQUIRED
    )
    extra_targets = sorted(
        {
            slot.semantic_target_ref
            for slot in required_slots
            if slot.semantic_target_ref not in operation_targets
        }
    )
    if extra_targets:
        _error(
            "MATERIALIZATION_TARGET_NOT_IN_CHANGESET",
            f"topology contains REQUIRED targets absent from ChangeSet: {extra_targets}",
        )

    covered_targets = {slot.semantic_target_ref for slot in required_slots}
    missing_targets = sorted(operation_targets - covered_targets)
    if missing_targets:
        _error(
            "MATERIALIZATION_REQUIRED_SLOT_MISSING",
            f"ChangeSet targets lack REQUIRED materialization slots: {missing_targets}",
        )

    if any(len(operation.targets) != 1 for operation in operations):
        _error(
            "UNSUPPORTED_MATERIALIZATION_CARDINALITY",
            "Phase I supports exactly one semantic target per canonical operation",
        )

    target_owners: dict[str, str] = {}
    for operation in operations:
        target = operation.targets[0]
        previous = target_owners.get(target)
        if previous is not None and previous != operation.operation_id:
            _error(
                "UNSUPPORTED_MATERIALIZATION_CARDINALITY",
                "one semantic target cannot be owned by multiple canonical operations",
            )
        target_owners[target] = operation.operation_id


def _build_intent(
    operation: CanonicalChangeOperation,
    operation_hash: str,
    slot,
) -> MaterializationIntent:
    """从一个 source operation 与一个 REQUIRED topology slot 构造 intent。"""
    draft = MaterializationIntent(
        materialization_id="MAT-DRAFT",
        source_operation_id=operation.operation_id,
        source_operation_hash=operation_hash,
        semantic_targets=tuple(operation.targets),
        materialization_slot_id=slot.materialization_slot_id,
        required_host_type=slot.required_host_type,
        expected_effects=_effect_values(operation),
        intent_hash="0" * 64,
    )
    intent_hash = compute_materialization_intent_hash(draft)
    return replace(
        draft,
        materialization_id=f"MAT-{intent_hash[:12]}",
        intent_hash=intent_hash,
    )


def _intent_sort_key(intent: MaterializationIntent) -> tuple[str, str, str]:
    """冻结 Task5 intent 输出顺序。"""
    return (
        intent.required_host_type,
        intent.materialization_slot_id,
        intent.materialization_id,
    )


class MaterializationPlanner:
    """把不可变 canonical transaction 投影成完整 REQUIRED materialization 集合。"""

    def plan(self, request: MaterializationPlanningRequest) -> MaterializationPlan:
        """构造一个不受运行时 availability 影响的确定性 MaterializationPlan。"""
        if not isinstance(request, MaterializationPlanningRequest):
            raise TypeError("request must be MaterializationPlanningRequest")
        _validate_lineage(request)

        changeset = request.canonical_changeset
        boundary = request.approval_scope_boundary
        topology = request.topology_snapshot
        operations = _operations(changeset)
        _validate_required_slot_coverage(operations, topology)

        operation_by_target = {
            operation.targets[0]: operation
            for operation in operations
        }
        operation_hashes = {
            operation.operation_id: _operation_hash(operation, boundary)
            for operation in operations
        }

        intents = tuple(
            sorted(
                (
                    _build_intent(
                        operation_by_target[slot.semantic_target_ref],
                        operation_hashes[
                            operation_by_target[slot.semantic_target_ref].operation_id
                        ],
                        slot,
                    )
                    for slot in topology.slots
                    if slot.requirement is MaterializationRequirement.REQUIRED
                ),
                key=_intent_sort_key,
            )
        )
        required_set_hash = compute_required_set_hash(intents)
        plan_hash = compute_materialization_plan_hash(
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
            topology_snapshot_hash=topology.topology_snapshot_hash,
            intents=intents,
            required_set_hash=required_set_hash,
            convergence_profile_hash=request.convergence_profile.profile_hash,
        )
        return MaterializationPlan(
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
            topology_snapshot_hash=topology.topology_snapshot_hash,
            intents=intents,
            required_set_hash=required_set_hash,
            convergence_profile_hash=request.convergence_profile.profile_hash,
            materialization_plan_hash=plan_hash,
        )


__all__ = ["MaterializationPlanner"]
