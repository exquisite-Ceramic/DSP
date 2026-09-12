"""Phase I 面向 materialization 的 Step30 V2 确定性执行计划。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from design_approval_scope import (
    ApprovalScopeBoundaryV2,
    ApprovalScopeError,
    CreationRule,
    DeletionRule,
    ExecutionSliceScopeRule,
    ExistingEntityRule,
    validate_approval_scope_boundary_v2,
)
from design_changeset import (
    CanonicalChangeOperation,
    CanonicalChangeSet,
    ChangePrecondition,
    ChangeSetError,
    canonical_hash,
    compute_operation_semantic_hash,
    compute_scope_rule_fingerprint,
    validate_changeset_integrity_v2,
)
from design_materialization_planning import (
    MaterializationIntent,
    MaterializationPlan,
    compute_materialization_intent_hash,
    compute_materialization_plan_hash,
    compute_required_set_hash,
)
from design_materialization_topology import (
    MaterializationRequirement,
    MaterializationSlot,
    MaterializationTopologyError,
    MaterializationTopologySnapshot,
    validate_materialization_topology_snapshot,
)

from .contracts import (
    ApprovalScopeRef,
    ApprovedExecutionScopeRef,
    ExecutionPlanningError,
    HostRuntimeRef,
    _aspects,
    _digest,
    _existence_effects,
    _readonly_mapping,
    _text,
    _texts,
    _typed_tuple,
)

_ORDERING_POLICY = "stable_host_type_then_slot.v1"
ScopeRule = ExistingEntityRule | CreationRule | DeletionRule


def _error(code: str, message: str) -> None:
    """统一抛出 Step30 V2 的稳定领域错误。"""
    raise ExecutionPlanningError(code, message)


def _runtime_ref_payload(ref: HostRuntimeRef) -> dict[str, str]:
    """把运行时引用投影为可哈希的 provider-neutral 语义体。"""
    return {
        "host_type": ref.host_type,
        "host_instance_id": ref.host_instance_id,
        "document_ref": ref.document_ref,
    }


def _effect_values(values: Iterable[object]) -> tuple[str, ...]:
    """把 canonical effect 枚举规范化为稳定字符串元组。"""
    return tuple(
        sorted(
            {
                value.value if isinstance(value, Enum) else str(value)
                for value in values
            }
        )
    )


def _precondition_payload(precondition: ChangePrecondition) -> dict[str, str]:
    """把 Step29 precondition 投影为稳定哈希载荷。"""
    return {
        "kind": precondition.kind.value,
        "subject_ref": precondition.subject_ref,
        "evidence_ref": precondition.evidence_ref,
    }


@dataclass(frozen=True, slots=True)
class MaterializationRuntimeRoute:
    """把一个 materialization id 绑定到一个精确运行时文档。"""

    materialization_id: str
    host_runtime_ref: HostRuntimeRef

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "materialization_id",
            _text(self.materialization_id, "materialization_id"),
        )
        if not isinstance(self.host_runtime_ref, HostRuntimeRef):
            raise TypeError("host_runtime_ref must be HostRuntimeRef")


@dataclass(frozen=True, slots=True)
class MaterializationRoutingEvidence:
    """对完整 materialization 路由集合进行内容寻址的不可变快照。"""

    routing_snapshot_id: str
    routes: tuple[MaterializationRuntimeRoute, ...]
    routing_snapshot_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "routing_snapshot_id",
            _text(self.routing_snapshot_id, "routing_snapshot_id"),
        )
        object.__setattr__(
            self,
            "routes",
            _typed_tuple(self.routes, MaterializationRuntimeRoute, "routes"),
        )
        object.__setattr__(
            self,
            "routing_snapshot_hash",
            _digest(self.routing_snapshot_hash, "routing_snapshot_hash"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionUnitV2:
    """一个 materialization intent 对应的唯一不可变执行单元。"""

    execution_unit_id: str
    materialization_id: str
    materialization_plan_hash: str
    materialization_slot_id: str
    required_host_type: str
    source_operation_id: str
    source_operation_hash: str
    canonical_operation: str
    canonical_operation_version: str
    canonical_definition_fingerprint: str
    targets: tuple[str, ...]
    arguments: Mapping[str, Any]
    preconditions: tuple[ChangePrecondition, ...]
    expected_effects: tuple[object, ...]
    scope_rule_ids: tuple[str, ...]
    execution_unit_hash: str
    expected_existence_effects: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "execution_unit_id",
            "materialization_id",
            "materialization_slot_id",
            "required_host_type",
            "source_operation_id",
            "canonical_operation",
            "canonical_operation_version",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "materialization_plan_hash",
            "source_operation_hash",
            "canonical_definition_fingerprint",
            "execution_unit_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(self, "targets", _texts(self.targets, "target", required=True))
        object.__setattr__(self, "arguments", _readonly_mapping(self.arguments, "arguments"))
        object.__setattr__(
            self,
            "preconditions",
            _typed_tuple(self.preconditions, ChangePrecondition, "preconditions"),
        )
        expected_effects = _aspects(self.expected_effects)
        expected_existence_effects = _existence_effects(self.expected_existence_effects)
        if not expected_effects and not expected_existence_effects:
            raise ValueError("execution unit requires expected effect authority")
        object.__setattr__(self, "expected_effects", expected_effects)
        object.__setattr__(
            self,
            "expected_existence_effects",
            expected_existence_effects,
        )
        object.__setattr__(
            self,
            "scope_rule_ids",
            _texts(self.scope_rule_ids, "scope_rule_id", required=True),
        )


@dataclass(frozen=True, slots=True)
class ExecutionSliceV2:
    """一个 REQUIRED materialization 的单单元执行切片。"""

    execution_slice_id: str
    changeset_id: str
    changeset_hash: str
    materialization_id: str
    materialization_plan_hash: str
    materialization_slot_id: str
    host_runtime_ref: HostRuntimeRef
    approved_scope_ref: ApprovedExecutionScopeRef
    execution_units: tuple[ExecutionUnitV2, ...]
    execution_slice_hash: str

    def __post_init__(self) -> None:
        for name in (
            "execution_slice_id",
            "changeset_id",
            "materialization_id",
            "materialization_slot_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "changeset_hash",
            "materialization_plan_hash",
            "execution_slice_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        if not isinstance(self.host_runtime_ref, HostRuntimeRef):
            raise TypeError("host_runtime_ref must be HostRuntimeRef")
        if not isinstance(self.approved_scope_ref, ApprovedExecutionScopeRef):
            raise TypeError("approved_scope_ref must be ApprovedExecutionScopeRef")
        units = _typed_tuple(
            self.execution_units,
            ExecutionUnitV2,
            "execution_units",
            required=True,
        )
        if len(units) != 1:
            raise ValueError("ExecutionSliceV2 requires exactly one ExecutionUnitV2")
        object.__setattr__(self, "execution_units", units)


@dataclass(frozen=True, slots=True)
class ExecutionPlanV2:
    """绑定 materialization required set 与确定性执行顺序的 Step30 V2 计划。"""

    execution_plan_id: str
    changeset_id: str
    changeset_hash: str
    approval_scope_ref: ApprovalScopeRef
    materialization_plan_hash: str
    required_set_hash: str
    convergence_profile_hash: str
    topology_snapshot_hash: str
    routing_snapshot_id: str
    routing_snapshot_hash: str
    ordering_policy: str
    execution_slices: tuple[ExecutionSliceV2, ...]
    execution_plan_hash: str

    def __post_init__(self) -> None:
        for name in (
            "execution_plan_id",
            "changeset_id",
            "routing_snapshot_id",
            "ordering_policy",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "changeset_hash",
            "materialization_plan_hash",
            "required_set_hash",
            "convergence_profile_hash",
            "topology_snapshot_hash",
            "routing_snapshot_hash",
            "execution_plan_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        if not isinstance(self.approval_scope_ref, ApprovalScopeRef):
            raise TypeError("approval_scope_ref must be ApprovalScopeRef")
        object.__setattr__(
            self,
            "execution_slices",
            _typed_tuple(
                self.execution_slices,
                ExecutionSliceV2,
                "execution_slices",
                required=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutionPlanningRequestV2:
    """Step30 V2 的五项冻结输入。"""

    canonical_changeset: CanonicalChangeSet
    approval_scope_boundary: ApprovalScopeBoundaryV2
    materialization_plan: MaterializationPlan
    topology_snapshot: MaterializationTopologySnapshot
    runtime_routing_evidence: MaterializationRoutingEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_changeset, CanonicalChangeSet):
            raise TypeError("canonical_changeset must be CanonicalChangeSet")
        if not isinstance(self.approval_scope_boundary, ApprovalScopeBoundaryV2):
            raise TypeError("approval_scope_boundary must be ApprovalScopeBoundaryV2")
        if not isinstance(self.materialization_plan, MaterializationPlan):
            raise TypeError("materialization_plan must be MaterializationPlan")
        if not isinstance(self.topology_snapshot, MaterializationTopologySnapshot):
            raise TypeError("topology_snapshot must be MaterializationTopologySnapshot")
        if not isinstance(self.runtime_routing_evidence, MaterializationRoutingEvidence):
            raise TypeError(
                "runtime_routing_evidence must be MaterializationRoutingEvidence"
            )


def compute_materialization_routing_hash(
    routes: Iterable[MaterializationRuntimeRoute],
) -> str:
    """对 materialization 路由做顺序无关的 canonical hash。"""
    normalized = tuple(routes)
    if any(not isinstance(route, MaterializationRuntimeRoute) for route in normalized):
        raise TypeError("routes must contain MaterializationRuntimeRoute values")
    payloads = [
        {
            "materialization_id": route.materialization_id,
            "host_runtime_ref": _runtime_ref_payload(route.host_runtime_ref),
        }
        for route in normalized
    ]
    payloads.sort(
        key=lambda item: (
            item["materialization_id"],
            item["host_runtime_ref"]["host_type"],
            item["host_runtime_ref"]["host_instance_id"],
            item["host_runtime_ref"]["document_ref"],
        )
    )
    return canonical_hash(
        {
            "version": "MATERIALIZATION_ROUTING_V1",
            "routes": payloads,
        }
    )


def _compute_execution_unit_hash_v2(
    *,
    changeset_hash: str,
    materialization_id: str,
    materialization_plan_hash: str,
    materialization_slot_id: str,
    required_host_type: str,
    source_operation_hash: str,
    canonical_operation: str,
    canonical_operation_version: str,
    canonical_definition_fingerprint: str,
    targets: Iterable[str],
    arguments: Mapping[str, Any],
    preconditions: Iterable[ChangePrecondition],
    expected_effects: Iterable[object],
    expected_existence_effects: Iterable[object],
    scope_rule_ids: Iterable[str],
) -> str:
    """计算单个 V2 execution unit 的不可变内容哈希。"""
    return canonical_hash(
        {
            "version": "EXECUTION_UNIT_V2",
            "changeset_hash": changeset_hash,
            "materialization_id": materialization_id,
            "materialization_plan_hash": materialization_plan_hash,
            "materialization_slot_id": materialization_slot_id,
            "required_host_type": required_host_type,
            "source_operation_hash": source_operation_hash,
            "canonical_operation": canonical_operation,
            "canonical_operation_version": canonical_operation_version,
            "canonical_definition_fingerprint": canonical_definition_fingerprint,
            "targets": sorted(set(targets)),
            "arguments": arguments,
            "preconditions": sorted(
                (_precondition_payload(item) for item in preconditions),
                key=lambda item: (
                    item["kind"],
                    item["subject_ref"],
                    item["evidence_ref"],
                ),
            ),
            "expected_effects": sorted(set(_effect_values(expected_effects))),
            "expected_existence_effects": sorted(
                set(_effect_values(expected_existence_effects))
            ),
            "scope_rule_ids": sorted(set(scope_rule_ids)),
        }
    )


def _compute_execution_slice_hash_v2(
    *,
    changeset_hash: str,
    scope_hash: str,
    execution_slice_scope_rule_id: str,
    materialization_id: str,
    materialization_plan_hash: str,
    materialization_slot_id: str,
    host_runtime_ref: HostRuntimeRef,
    execution_unit_hash: str,
) -> str:
    """计算一个 materialization Slice 的不可变内容哈希。"""
    return canonical_hash(
        {
            "version": "EXECUTION_SLICE_V2",
            "changeset_hash": changeset_hash,
            "scope_hash": scope_hash,
            "execution_slice_scope_rule_id": execution_slice_scope_rule_id,
            "materialization_id": materialization_id,
            "materialization_plan_hash": materialization_plan_hash,
            "materialization_slot_id": materialization_slot_id,
            "host_runtime_ref": _runtime_ref_payload(host_runtime_ref),
            "execution_unit_hash": execution_unit_hash,
        }
    )


def _compute_execution_plan_hash_v2(
    *,
    changeset_hash: str,
    scope_hash: str,
    materialization_plan_hash: str,
    required_set_hash: str,
    convergence_profile_hash: str,
    topology_snapshot_hash: str,
    routing_snapshot_hash: str,
    ordering_policy: str,
    execution_slice_hashes: Iterable[str],
) -> str:
    """把 V2 执行计划全部 lineage 与执行顺序绑定进内容哈希。"""
    return canonical_hash(
        {
            "version": "EXECUTION_PLAN_V2",
            "changeset_hash": changeset_hash,
            "scope_hash": scope_hash,
            "materialization_plan_hash": materialization_plan_hash,
            "required_set_hash": required_set_hash,
            "convergence_profile_hash": convergence_profile_hash,
            "topology_snapshot_hash": topology_snapshot_hash,
            "routing_snapshot_hash": routing_snapshot_hash,
            "ordering_policy": ordering_policy,
            "execution_slice_hashes": list(execution_slice_hashes),
        }
    )


def _scope_rule_index(boundary: ApprovalScopeBoundaryV2) -> dict[str, ScopeRule]:
    """建立 Step28 三类规则的闭世界索引。"""
    result: dict[str, ScopeRule] = {}
    for rule in (
        *boundary.existing_entity_rules,
        *boundary.creation_rules,
        *boundary.deletion_rules,
    ):
        if rule.rule_id in result:
            _error(
                "EXECUTION_SCOPE_MISMATCH",
                f"duplicate Step28 scope rule id: {rule.rule_id}",
            )
        result[rule.rule_id] = rule
    return result


def _source_operation_hash(
    operation: CanonicalChangeOperation,
    boundary: ApprovalScopeBoundaryV2,
) -> str:
    """复用 Step29 公共 primitive 重建 canonical operation 语义哈希。"""
    rules = _scope_rule_index(boundary)
    try:
        fingerprints = tuple(
            sorted(
                compute_scope_rule_fingerprint(rules[rule_id])
                for rule_id in operation.scope_rule_ids
            )
        )
    except KeyError as exc:
        _error(
            "EXECUTION_SCOPE_MISMATCH",
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
            "EXECUTION_OPERATION_MISMATCH",
            "canonical operation id does not match its Step29 semantic hash",
        )
    return operation_hash


def _partition_required_scope_ids(
    scope_rule_ids: Iterable[str],
    boundary: ApprovalScopeBoundaryV2,
) -> tuple[set[str], set[str], set[str]]:
    """按 Step28 规则类别拆分 operation 的精确授权集合。"""
    requested = set(scope_rule_ids)
    existing_ids = {rule.rule_id for rule in boundary.existing_entity_rules}
    creation_ids = {rule.rule_id for rule in boundary.creation_rules}
    deletion_ids = {rule.rule_id for rule in boundary.deletion_rules}
    known = existing_ids | creation_ids | deletion_ids
    unknown = requested - known
    if unknown:
        _error(
            "EXECUTION_SCOPE_MISMATCH",
            f"canonical operation references unknown Step28 rules: {sorted(unknown)}",
        )
    return (
        requested & existing_ids,
        requested & creation_ids,
        requested & deletion_ids,
    )


def _resolve_exact_scope_rule_ids(
    scope_rule_ids: Iterable[str],
    document_ref: str,
    boundary: ApprovalScopeBoundaryV2,
) -> ExecutionSliceScopeRule:
    """只接受 document 与三类 rule-id 集合完全相等的 Slice scope。"""
    required_existing, required_creation, required_deletion = (
        _partition_required_scope_ids(scope_rule_ids, boundary)
    )
    candidates = [
        candidate
        for candidate in boundary.execution_slice_scopes
        if candidate.document_ref == document_ref
        and set(candidate.existing_rule_ids) == required_existing
        and set(candidate.creation_rule_ids) == required_creation
        and set(candidate.deletion_rule_ids) == required_deletion
    ]
    if not candidates:
        _error(
            "EXECUTION_SCOPE_UNCOVERED",
            "no exact document-scoped execution authority matches this materialization",
        )
    if len(candidates) > 1:
        _error(
            "EXECUTION_SCOPE_AMBIGUOUS",
            "multiple exact document-scoped execution authorities match this materialization",
        )
    return candidates[0]


def _resolve_exact_execution_slice_scope(
    operation: CanonicalChangeOperation,
    document_ref: str,
    boundary: ApprovalScopeBoundaryV2,
) -> ExecutionSliceScopeRule:
    """供 V2 planner 与 focused contract tests 共用的精确 scope resolver。"""
    if not isinstance(operation, CanonicalChangeOperation):
        raise TypeError("operation must be CanonicalChangeOperation")
    if not isinstance(boundary, ApprovalScopeBoundaryV2):
        raise TypeError("boundary must be ApprovalScopeBoundaryV2")
    return _resolve_exact_scope_rule_ids(
        operation.scope_rule_ids,
        _text(document_ref, "document_ref"),
        boundary,
    )


def _resolve_slot(
    topology: MaterializationTopologySnapshot,
    materialization_slot_id: str,
) -> MaterializationSlot:
    """按 materialization_slot_id 精确解析且拒绝缺失或重复槽。"""
    matches = [
        slot
        for slot in topology.slots
        if slot.materialization_slot_id == materialization_slot_id
    ]
    if not matches:
        _error(
            "MATERIALIZATION_SLOT_UNRESOLVED",
            f"materialization slot is absent: {materialization_slot_id}",
        )
    if len(matches) > 1:
        _error(
            "MATERIALIZATION_SLOT_AMBIGUOUS",
            f"materialization slot id is duplicated: {materialization_slot_id}",
        )
    return matches[0]


def _reconstruct_intent_from_unit(unit: ExecutionUnitV2) -> MaterializationIntent:
    """从 V2 unit 重建 Task5 intent，使下游 validator 可复核 required set。"""
    draft = MaterializationIntent(
        materialization_id=unit.materialization_id,
        source_operation_id=unit.source_operation_id,
        source_operation_hash=unit.source_operation_hash,
        semantic_targets=unit.targets,
        materialization_slot_id=unit.materialization_slot_id,
        required_host_type=unit.required_host_type,
        expected_effects=_effect_values(unit.expected_effects),
        intent_hash="0" * 64,
    )
    intent_hash = compute_materialization_intent_hash(draft)
    if unit.materialization_id != f"MAT-{intent_hash[:12]}":
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "materialization id cannot be reconstructed from the V2 unit",
        )
    return MaterializationIntent(
        materialization_id=unit.materialization_id,
        source_operation_id=unit.source_operation_id,
        source_operation_hash=unit.source_operation_hash,
        semantic_targets=unit.targets,
        materialization_slot_id=unit.materialization_slot_id,
        required_host_type=unit.required_host_type,
        expected_effects=_effect_values(unit.expected_effects),
        intent_hash=intent_hash,
    )


def _validate_materialization_plan(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundaryV2,
    topology: MaterializationTopologySnapshot,
    plan: MaterializationPlan,
) -> dict[str, CanonicalChangeOperation]:
    """在 Step30 投影前完整重建 Task5 plan 的 owner-owned lineage。"""
    if plan.changeset_hash != changeset.changeset_hash:
        _error(
            "MATERIALIZATION_PLAN_MISMATCH",
            "materialization plan does not bind this ChangeSet",
        )
    if plan.approved_scope_hash != boundary.scope_hash:
        _error(
            "MATERIALIZATION_PLAN_MISMATCH",
            "materialization plan does not bind this approval scope",
        )
    if plan.topology_snapshot_hash != topology.topology_snapshot_hash:
        _error(
            "MATERIALIZATION_PLAN_MISMATCH",
            "materialization plan does not bind this topology snapshot",
        )

    intents = tuple(plan.intents)
    for intent in intents:
        expected_intent_hash = compute_materialization_intent_hash(intent)
        if intent.intent_hash != expected_intent_hash:
            _error(
                "MATERIALIZATION_PLAN_INTEGRITY_INVALID",
                "materialization intent does not match its content hash",
            )
        if intent.materialization_id != f"MAT-{expected_intent_hash[:12]}":
            _error(
                "MATERIALIZATION_PLAN_INTEGRITY_INVALID",
                "materialization id does not match its content hash",
            )
    expected_required_set_hash = compute_required_set_hash(intents)
    if plan.required_set_hash != expected_required_set_hash:
        _error(
            "MATERIALIZATION_PLAN_INTEGRITY_INVALID",
            "required materialization set does not match its content hash",
        )
    expected_plan_hash = compute_materialization_plan_hash(
        changeset_hash=plan.changeset_hash,
        approved_scope_hash=plan.approved_scope_hash,
        topology_snapshot_hash=plan.topology_snapshot_hash,
        intents=intents,
        required_set_hash=plan.required_set_hash,
        convergence_profile_hash=plan.convergence_profile_hash,
    )
    if plan.materialization_plan_hash != expected_plan_hash:
        _error(
            "MATERIALIZATION_PLAN_INTEGRITY_INVALID",
            "materialization plan does not match its content hash",
        )

    operations = (changeset.root_operation, *changeset.derived_operations)
    operations_by_id = {operation.operation_id: operation for operation in operations}
    if len(operations_by_id) != len(operations):
        _error(
            "EXECUTION_OPERATION_MISMATCH",
            "Step29 operation ids must be unique",
        )

    required_slots = tuple(
        slot
        for slot in topology.slots
        if slot.requirement is MaterializationRequirement.REQUIRED
    )
    required_slot_ids = {slot.materialization_slot_id for slot in required_slots}
    intent_slot_ids = {intent.materialization_slot_id for intent in intents}
    if intent_slot_ids != required_slot_ids or len(intents) != len(required_slots):
        _error(
            "MATERIALIZATION_PLAN_MISMATCH",
            "materialization plan must cover the exact REQUIRED topology slot set",
        )

    for intent in intents:
        operation = operations_by_id.get(intent.source_operation_id)
        if operation is None:
            _error(
                "MATERIALIZATION_PLAN_MISMATCH",
                "materialization intent references an unknown canonical operation",
            )
        operation_hash = _source_operation_hash(operation, boundary)
        if intent.source_operation_hash != operation_hash:
            _error(
                "MATERIALIZATION_PLAN_MISMATCH",
                "materialization intent source hash differs from Step29",
            )
        if tuple(intent.semantic_targets) != tuple(operation.targets):
            _error(
                "MATERIALIZATION_PLAN_MISMATCH",
                "materialization intent targets differ from its source operation",
            )
        if tuple(intent.expected_effects) != _effect_values(operation.expected_effects):
            _error(
                "MATERIALIZATION_PLAN_MISMATCH",
                "materialization intent effects differ from its source operation",
            )
        slot = _resolve_slot(topology, intent.materialization_slot_id)
        if slot.requirement is not MaterializationRequirement.REQUIRED:
            _error(
                "MATERIALIZATION_PLAN_MISMATCH",
                "materialization intent references a non-REQUIRED topology slot",
            )
        if len(intent.semantic_targets) != 1:
            _error(
                "UNSUPPORTED_MATERIALIZATION_CARDINALITY",
                "Step30 V2 supports one semantic target per materialization intent",
            )
        if slot.semantic_target_ref != intent.semantic_targets[0]:
            _error(
                "MATERIALIZATION_PLAN_MISMATCH",
                "materialization intent target differs from its topology slot",
            )
        if slot.required_host_type != intent.required_host_type:
            _error(
                "MATERIALIZATION_PLAN_MISMATCH",
                "materialization intent Host type differs from its topology slot",
            )
    return operations_by_id


def _normalize_routes(
    evidence: MaterializationRoutingEvidence,
    plan: MaterializationPlan,
    topology: MaterializationTopologySnapshot,
) -> dict[str, HostRuntimeRef]:
    """闭世界验证每个 REQUIRED materialization 的唯一运行时路由。"""
    expected_hash = compute_materialization_routing_hash(evidence.routes)
    if evidence.routing_snapshot_hash != expected_hash:
        _error(
            "MATERIALIZATION_ROUTING_HASH_MISMATCH",
            "materialization routing snapshot does not match its content hash",
        )

    route_index: dict[str, HostRuntimeRef] = {}
    for route in evidence.routes:
        if route.materialization_id in route_index:
            _error(
                "MATERIALIZATION_ROUTE_CONFLICT",
                f"duplicate route for materialization: {route.materialization_id}",
            )
        route_index[route.materialization_id] = route.host_runtime_ref

    expected_ids = {intent.materialization_id for intent in plan.intents}
    actual_ids = set(route_index)
    missing = expected_ids - actual_ids
    if missing:
        _error(
            "MATERIALIZATION_ROUTE_UNRESOLVED",
            f"missing REQUIRED materialization routes: {sorted(missing)}",
        )
    extra = actual_ids - expected_ids
    if extra:
        _error(
            "MATERIALIZATION_ROUTE_EXTRANEOUS",
            f"routing contains unrelated materializations: {sorted(extra)}",
        )

    intent_by_id = {intent.materialization_id: intent for intent in plan.intents}
    for materialization_id, runtime_ref in route_index.items():
        intent = intent_by_id[materialization_id]
        slot = _resolve_slot(topology, intent.materialization_slot_id)
        if (
            runtime_ref.host_type != slot.required_host_type
            or runtime_ref.document_ref != slot.document_ref
        ):
            _error(
                "MATERIALIZATION_ROUTE_MISMATCH",
                "runtime Host/document does not match the authoritative topology slot",
            )
    return route_index


def _build_unit_with_plan(
    changeset: CanonicalChangeSet,
    operation: CanonicalChangeOperation,
    intent: MaterializationIntent,
    materialization_plan_hash: str,
) -> ExecutionUnitV2:
    """使用精确 Task5 plan hash 构造最终 V2 unit。"""
    unit_hash = _compute_execution_unit_hash_v2(
        changeset_hash=changeset.changeset_hash,
        materialization_id=intent.materialization_id,
        materialization_plan_hash=materialization_plan_hash,
        materialization_slot_id=intent.materialization_slot_id,
        required_host_type=intent.required_host_type,
        source_operation_hash=intent.source_operation_hash,
        canonical_operation=operation.canonical_operation,
        canonical_operation_version=operation.canonical_operation_version,
        canonical_definition_fingerprint=operation.canonical_definition_fingerprint,
        targets=operation.targets,
        arguments=operation.arguments,
        preconditions=changeset.preconditions,
        expected_effects=operation.expected_effects,
        expected_existence_effects=operation.expected_existence_effects,
        scope_rule_ids=operation.scope_rule_ids,
    )
    return ExecutionUnitV2(
        execution_unit_id=f"EUV2-{unit_hash[:12]}",
        materialization_id=intent.materialization_id,
        materialization_plan_hash=materialization_plan_hash,
        materialization_slot_id=intent.materialization_slot_id,
        required_host_type=intent.required_host_type,
        source_operation_id=operation.operation_id,
        source_operation_hash=intent.source_operation_hash,
        canonical_operation=operation.canonical_operation,
        canonical_operation_version=operation.canonical_operation_version,
        canonical_definition_fingerprint=operation.canonical_definition_fingerprint,
        targets=operation.targets,
        arguments=operation.arguments,
        preconditions=changeset.preconditions,
        expected_effects=operation.expected_effects,
        expected_existence_effects=operation.expected_existence_effects,
        scope_rule_ids=operation.scope_rule_ids,
        execution_unit_hash=unit_hash,
    )


def _intent_sort_key(intent: MaterializationIntent) -> tuple[str, str, str]:
    """冻结 Step30 V2 的 host-type / slot / materialization 顺序。"""
    return (
        intent.required_host_type,
        intent.materialization_slot_id,
        intent.materialization_id,
    )


def _build_slice(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundaryV2,
    intent: MaterializationIntent,
    operation: CanonicalChangeOperation,
    runtime_ref: HostRuntimeRef,
    materialization_plan_hash: str,
) -> ExecutionSliceV2:
    """为一个 intent 生成一张且仅一张 V2 Slice。"""
    scope_rule = _resolve_exact_execution_slice_scope(
        operation,
        runtime_ref.document_ref,
        boundary,
    )
    unit = _build_unit_with_plan(
        changeset,
        operation,
        intent,
        materialization_plan_hash,
    )
    slice_hash = _compute_execution_slice_hash_v2(
        changeset_hash=changeset.changeset_hash,
        scope_hash=boundary.scope_hash,
        execution_slice_scope_rule_id=scope_rule.slice_scope_rule_id,
        materialization_id=intent.materialization_id,
        materialization_plan_hash=materialization_plan_hash,
        materialization_slot_id=intent.materialization_slot_id,
        host_runtime_ref=runtime_ref,
        execution_unit_hash=unit.execution_unit_hash,
    )
    return ExecutionSliceV2(
        execution_slice_id=f"XSV2-{slice_hash[:12]}",
        changeset_id=changeset.changeset_id,
        changeset_hash=changeset.changeset_hash,
        materialization_id=intent.materialization_id,
        materialization_plan_hash=materialization_plan_hash,
        materialization_slot_id=intent.materialization_slot_id,
        host_runtime_ref=runtime_ref,
        approved_scope_ref=ApprovedExecutionScopeRef(
            boundary.scope_id,
            boundary.scope_hash,
            scope_rule.slice_scope_rule_id,
        ),
        execution_units=(unit,),
        execution_slice_hash=slice_hash,
    )


def _validate_owner_inputs(request: ExecutionPlanningRequestV2) -> None:
    """调用各 owner validator，禁止 Step30 V2 自行替代上游完整性判断。"""
    try:
        validate_approval_scope_boundary_v2(request.approval_scope_boundary)
    except ApprovalScopeError as exc:
        _error(
            "EXECUTION_SCOPE_INTEGRITY_INVALID",
            f"Step28 V2 boundary integrity failed: {exc.code}",
        )
    try:
        validate_changeset_integrity_v2(
            request.canonical_changeset,
            request.approval_scope_boundary,
        )
    except ChangeSetError as exc:
        _error(
            "EXECUTION_CHANGESET_INTEGRITY_INVALID",
            f"Step29 V2 ChangeSet integrity failed: {exc.code}",
        )
    try:
        validate_materialization_topology_snapshot(request.topology_snapshot)
    except MaterializationTopologyError as exc:
        _error(
            "EXECUTION_TOPOLOGY_INTEGRITY_INVALID",
            f"materialization topology integrity failed: {exc.code}",
        )
    if (
        request.approval_scope_boundary.topology_snapshot_hash
        != request.topology_snapshot.topology_snapshot_hash
    ):
        _error(
            "EXECUTION_TOPOLOGY_MISMATCH",
            "approval scope does not bind the supplied topology snapshot",
        )


def plan_materialized_execution(
    request: ExecutionPlanningRequestV2,
) -> ExecutionPlanV2:
    """把冻结 MaterializationPlan 投影为确定性 Step30 V2 执行计划。"""
    if not isinstance(request, ExecutionPlanningRequestV2):
        raise TypeError("request must be ExecutionPlanningRequestV2")
    _validate_owner_inputs(request)

    changeset = request.canonical_changeset
    boundary = request.approval_scope_boundary
    topology = request.topology_snapshot
    materialization_plan = request.materialization_plan

    operations_by_id = _validate_materialization_plan(
        changeset,
        boundary,
        topology,
        materialization_plan,
    )
    if changeset.change_dependencies:
        _error(
            "EXECUTION_DEPENDENCY_UNSUPPORTED_V2",
            "Phase I Step30 V2 does not project inter-operation dependencies",
        )
    route_index = _normalize_routes(
        request.runtime_routing_evidence,
        materialization_plan,
        topology,
    )

    ordered_intents = tuple(sorted(materialization_plan.intents, key=_intent_sort_key))
    slices = tuple(
        _build_slice(
            changeset,
            boundary,
            intent,
            operations_by_id[intent.source_operation_id],
            route_index[intent.materialization_id],
            materialization_plan.materialization_plan_hash,
        )
        for intent in ordered_intents
    )
    plan_hash = _compute_execution_plan_hash_v2(
        changeset_hash=changeset.changeset_hash,
        scope_hash=boundary.scope_hash,
        materialization_plan_hash=materialization_plan.materialization_plan_hash,
        required_set_hash=materialization_plan.required_set_hash,
        convergence_profile_hash=materialization_plan.convergence_profile_hash,
        topology_snapshot_hash=topology.topology_snapshot_hash,
        routing_snapshot_hash=request.runtime_routing_evidence.routing_snapshot_hash,
        ordering_policy=_ORDERING_POLICY,
        execution_slice_hashes=(
            execution_slice.execution_slice_hash for execution_slice in slices
        ),
    )
    execution_plan = ExecutionPlanV2(
        execution_plan_id=f"XPV2-{plan_hash[:12]}",
        changeset_id=changeset.changeset_id,
        changeset_hash=changeset.changeset_hash,
        approval_scope_ref=ApprovalScopeRef(boundary.scope_id, boundary.scope_hash),
        materialization_plan_hash=materialization_plan.materialization_plan_hash,
        required_set_hash=materialization_plan.required_set_hash,
        convergence_profile_hash=materialization_plan.convergence_profile_hash,
        topology_snapshot_hash=topology.topology_snapshot_hash,
        routing_snapshot_id=request.runtime_routing_evidence.routing_snapshot_id,
        routing_snapshot_hash=request.runtime_routing_evidence.routing_snapshot_hash,
        ordering_policy=_ORDERING_POLICY,
        execution_slices=slices,
        execution_plan_hash=plan_hash,
    )
    validate_execution_plan_v2(execution_plan, topology, boundary)
    return execution_plan


def _validate_unit_integrity(
    unit: ExecutionUnitV2,
    execution_slice: ExecutionSliceV2,
) -> None:
    """重算单个 V2 unit 并验证其 materialization lineage。"""
    if unit.materialization_id != execution_slice.materialization_id:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "unit materialization differs from its Slice",
        )
    if unit.materialization_plan_hash != execution_slice.materialization_plan_hash:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "unit materialization plan differs from its Slice",
        )
    if unit.materialization_slot_id != execution_slice.materialization_slot_id:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "unit materialization slot differs from its Slice",
        )
    if unit.required_host_type != execution_slice.host_runtime_ref.host_type:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "unit required Host type differs from its Slice runtime",
        )
    expected_hash = _compute_execution_unit_hash_v2(
        changeset_hash=execution_slice.changeset_hash,
        materialization_id=unit.materialization_id,
        materialization_plan_hash=unit.materialization_plan_hash,
        materialization_slot_id=unit.materialization_slot_id,
        required_host_type=unit.required_host_type,
        source_operation_hash=unit.source_operation_hash,
        canonical_operation=unit.canonical_operation,
        canonical_operation_version=unit.canonical_operation_version,
        canonical_definition_fingerprint=unit.canonical_definition_fingerprint,
        targets=unit.targets,
        arguments=unit.arguments,
        preconditions=unit.preconditions,
        expected_effects=unit.expected_effects,
        expected_existence_effects=unit.expected_existence_effects,
        scope_rule_ids=unit.scope_rule_ids,
    )
    if unit.execution_unit_hash != expected_hash:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "ExecutionUnitV2 body does not match its content hash",
        )
    if unit.execution_unit_id != f"EUV2-{expected_hash[:12]}":
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "ExecutionUnitV2 id does not match its content hash",
        )


def validate_execution_plan_v2(
    plan: ExecutionPlanV2,
    topology_snapshot: MaterializationTopologySnapshot,
    boundary: ApprovalScopeBoundaryV2,
) -> None:
    """仅用 V2 plan、拓扑与批准边界重建可验证的 Step30 lineage。"""
    if not isinstance(plan, ExecutionPlanV2):
        raise TypeError("plan must be ExecutionPlanV2")
    if not isinstance(topology_snapshot, MaterializationTopologySnapshot):
        raise TypeError("topology_snapshot must be MaterializationTopologySnapshot")
    if not isinstance(boundary, ApprovalScopeBoundaryV2):
        raise TypeError("boundary must be ApprovalScopeBoundaryV2")

    try:
        validate_approval_scope_boundary_v2(boundary)
    except ApprovalScopeError as exc:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            f"Step28 V2 boundary integrity failed: {exc.code}",
        )
    try:
        validate_materialization_topology_snapshot(topology_snapshot)
    except MaterializationTopologyError as exc:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            f"materialization topology integrity failed: {exc.code}",
        )

    if plan.changeset_hash != boundary.changeset_hash:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "execution plan ChangeSet differs from the approval boundary",
        )
    if (
        plan.approval_scope_ref.scope_id != boundary.scope_id
        or plan.approval_scope_ref.scope_hash != boundary.scope_hash
    ):
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "execution plan scope reference differs from the approval boundary",
        )
    if (
        plan.topology_snapshot_hash != topology_snapshot.topology_snapshot_hash
        or boundary.topology_snapshot_hash != topology_snapshot.topology_snapshot_hash
    ):
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "execution plan topology lineage is inconsistent",
        )
    if plan.ordering_policy != _ORDERING_POLICY:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "execution plan ordering policy is unsupported",
        )

    reconstructed_intents: list[MaterializationIntent] = []
    slot_ids: set[str] = set()
    materialization_ids: set[str] = set()
    for execution_slice in plan.execution_slices:
        if execution_slice.changeset_id != plan.changeset_id:
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "Slice ChangeSet id differs from its execution plan",
            )
        if execution_slice.changeset_hash != plan.changeset_hash:
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "Slice ChangeSet differs from its execution plan",
            )
        if execution_slice.materialization_plan_hash != plan.materialization_plan_hash:
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "Slice materialization plan differs from its execution plan",
            )
        if (
            execution_slice.approved_scope_ref.scope_id != boundary.scope_id
            or execution_slice.approved_scope_ref.scope_hash != boundary.scope_hash
        ):
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "Slice approval scope differs from its execution plan",
            )
        if execution_slice.materialization_id in materialization_ids:
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "duplicate materialization id across V2 Slices",
            )
        if execution_slice.materialization_slot_id in slot_ids:
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "duplicate materialization slot across V2 Slices",
            )
        materialization_ids.add(execution_slice.materialization_id)
        slot_ids.add(execution_slice.materialization_slot_id)

        slot = _resolve_slot(
            topology_snapshot,
            execution_slice.materialization_slot_id,
        )
        if slot.requirement is not MaterializationRequirement.REQUIRED:
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "V2 Slice references a non-REQUIRED topology slot",
            )
        if (
            execution_slice.host_runtime_ref.host_type != slot.required_host_type
            or execution_slice.host_runtime_ref.document_ref != slot.document_ref
        ):
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "V2 Slice runtime does not match its topology slot",
            )

        unit = execution_slice.execution_units[0]
        _validate_unit_integrity(unit, execution_slice)
        if len(unit.targets) != 1 or unit.targets[0] != slot.semantic_target_ref:
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "V2 unit target does not match its topology slot",
            )
        exact_scope = _resolve_exact_scope_rule_ids(
            unit.scope_rule_ids,
            slot.document_ref,
            boundary,
        )
        if (
            execution_slice.approved_scope_ref.execution_slice_scope_rule_id
            != exact_scope.slice_scope_rule_id
        ):
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "V2 Slice does not bind the exact document-scoped authority",
            )

        expected_slice_hash = _compute_execution_slice_hash_v2(
            changeset_hash=execution_slice.changeset_hash,
            scope_hash=execution_slice.approved_scope_ref.scope_hash,
            execution_slice_scope_rule_id=(
                execution_slice.approved_scope_ref.execution_slice_scope_rule_id
            ),
            materialization_id=execution_slice.materialization_id,
            materialization_plan_hash=execution_slice.materialization_plan_hash,
            materialization_slot_id=execution_slice.materialization_slot_id,
            host_runtime_ref=execution_slice.host_runtime_ref,
            execution_unit_hash=unit.execution_unit_hash,
        )
        if execution_slice.execution_slice_hash != expected_slice_hash:
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "ExecutionSliceV2 body does not match its content hash",
            )
        if execution_slice.execution_slice_id != f"XSV2-{expected_slice_hash[:12]}":
            _error(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "ExecutionSliceV2 id does not match its content hash",
            )
        reconstructed_intents.append(_reconstruct_intent_from_unit(unit))

    required_slot_ids = {
        slot.materialization_slot_id
        for slot in topology_snapshot.slots
        if slot.requirement is MaterializationRequirement.REQUIRED
    }
    if slot_ids != required_slot_ids:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "V2 Slices do not cover the exact REQUIRED topology slot set",
        )

    reconstructed_tuple = tuple(reconstructed_intents)
    expected_required_set_hash = compute_required_set_hash(reconstructed_tuple)
    if plan.required_set_hash != expected_required_set_hash:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "execution plan required set cannot be reconstructed",
        )
    expected_materialization_plan_hash = compute_materialization_plan_hash(
        changeset_hash=plan.changeset_hash,
        approved_scope_hash=plan.approval_scope_ref.scope_hash,
        topology_snapshot_hash=plan.topology_snapshot_hash,
        intents=reconstructed_tuple,
        required_set_hash=plan.required_set_hash,
        convergence_profile_hash=plan.convergence_profile_hash,
    )
    if plan.materialization_plan_hash != expected_materialization_plan_hash:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "execution plan materialization lineage cannot be reconstructed",
        )

    expected_order = tuple(
        sorted(
            plan.execution_slices,
            key=lambda item: (
                item.host_runtime_ref.host_type,
                item.materialization_slot_id,
                item.materialization_id,
            ),
        )
    )
    if plan.execution_slices != expected_order:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "execution slices violate the frozen ordering policy",
        )

    expected_plan_hash = _compute_execution_plan_hash_v2(
        changeset_hash=plan.changeset_hash,
        scope_hash=plan.approval_scope_ref.scope_hash,
        materialization_plan_hash=plan.materialization_plan_hash,
        required_set_hash=plan.required_set_hash,
        convergence_profile_hash=plan.convergence_profile_hash,
        topology_snapshot_hash=plan.topology_snapshot_hash,
        routing_snapshot_hash=plan.routing_snapshot_hash,
        ordering_policy=plan.ordering_policy,
        execution_slice_hashes=(
            execution_slice.execution_slice_hash
            for execution_slice in plan.execution_slices
        ),
    )
    if plan.execution_plan_hash != expected_plan_hash:
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "ExecutionPlanV2 body does not match its content hash",
        )
    if plan.execution_plan_id != f"XPV2-{expected_plan_hash[:12]}":
        _error(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "ExecutionPlanV2 id does not match its content hash",
        )


__all__ = [
    "ExecutionPlanV2",
    "ExecutionPlanningRequestV2",
    "ExecutionSliceV2",
    "ExecutionUnitV2",
    "MaterializationRoutingEvidence",
    "MaterializationRuntimeRoute",
    "compute_materialization_routing_hash",
    "plan_materialized_execution",
    "validate_execution_plan_v2",
]
