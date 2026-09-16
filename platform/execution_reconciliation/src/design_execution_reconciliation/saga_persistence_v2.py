"""Execution Saga V2 的显式、版本化 PostgreSQL 持久化编解码。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from semantic_runtime import SemanticEnvironmentRef

from .saga_contracts import SliceDependency, SliceValidationAssignment
from .saga_contracts_v2 import ExecutionSagaDefinitionV2
from .saga_state_v2 import (
    ExecutionSagaStatusV2,
    SagaConvergenceOutcome,
    SliceReconciliationStateV2,
    SliceReconciliationStatusV2,
    StoredExecutionSagaV2,
)

_SCHEMA_VERSION = 1


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """只接受 JSON object 形态，避免隐式依赖 Python 对象布局。"""
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _array(value: object, field_name: str) -> Sequence[object]:
    """只接受 JSON array 形态；字符串不能被误当作字段序列。"""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _required(value: Mapping[str, object], key: str) -> object:
    """读取必需字段，并保留领域构造器对具体值的最终校验权。"""
    if key not in value:
        raise ValueError(f"missing persisted Saga V2 field: {key}")
    return value[key]


def _optional_text(value: object, field_name: str) -> str | None:
    """规范化可空文本，拒绝持久化载荷中的非字符串值。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or null")
    return value


def _dependency_payload(value: SliceDependency) -> dict[str, object]:
    """把 Slice 依赖转换为显式 JSON-compatible 结构。"""
    return {
        "predecessor_slice_hash": value.predecessor_slice_hash,
        "successor_slice_hash": value.successor_slice_hash,
        "reason_refs": list(value.reason_refs),
    }


def _assignment_payload(value: SliceValidationAssignment) -> dict[str, object]:
    """把验证任务分配转换为显式 JSON-compatible 结构。"""
    return {
        "execution_slice_hash": value.execution_slice_hash,
        "validation_task_ids": list(value.validation_task_ids),
    }


def _definition_payload(value: ExecutionSagaDefinitionV2) -> dict[str, object]:
    """编码不可变 Saga 定义；不复制 Python dataclass 内部布局。"""
    return {
        "saga_id": value.saga_id,
        "changeset_hash": value.changeset_hash,
        "approved_scope_hash": value.approved_scope_hash,
        "semantic_environment_ref": {
            "environment_id": value.semantic_environment_ref.environment_id,
            "content_hash": value.semantic_environment_ref.content_hash,
        },
        "materialization_plan_hash": value.materialization_plan_hash,
        "required_set_hash": value.required_set_hash,
        "execution_plan_hash": value.execution_plan_hash,
        "ordered_slice_hashes": list(value.ordered_slice_hashes),
        "slice_dependencies": [
            _dependency_payload(item) for item in value.slice_dependencies
        ],
        "slice_validation_assignments": [
            _assignment_payload(item)
            for item in value.slice_validation_assignments
        ],
        "saga_definition_hash": value.saga_definition_hash,
    }


def _slice_state_payload(value: SliceReconciliationStateV2) -> dict[str, object]:
    """编码一个 Slice 的 durable reconciliation 投影。"""
    return {
        "execution_slice_hash": value.execution_slice_hash,
        "sequence_index": value.sequence_index,
        "materialization_plan_hash": value.materialization_plan_hash,
        "status": value.status.value,
        "materialization_id": value.materialization_id,
        "approval_hash": value.approval_hash,
        "grant_hash": value.grant_hash,
        "binding_set_hash": value.binding_set_hash,
        "admitted_host_instance_id": value.admitted_host_instance_id,
        "actual_delta_hash": value.actual_delta_hash,
        "scope_comparison_hash": value.scope_comparison_hash,
        "verification_hash": value.verification_hash,
        "reserved_at": value.reserved_at,
        "admitted_at": value.admitted_at,
        "committed_at": value.committed_at,
        "reconciled_at": value.reconciled_at,
        "failed_at": value.failed_at,
    }


def encode_stored_saga_v2(value: StoredExecutionSagaV2) -> dict[str, object]:
    """把已验证 Saga V2 快照编码成私有、版本化 JSON-compatible 载荷。"""
    if not isinstance(value, StoredExecutionSagaV2):
        raise TypeError("value must be StoredExecutionSagaV2")

    convergence_outcome = value.convergence_outcome
    return {
        "schema_version": _SCHEMA_VERSION,
        "definition": _definition_payload(value.definition),
        "saga_revision": value.saga_revision,
        "status": value.status.value,
        "slice_states": [_slice_state_payload(item) for item in value.slice_states],
        "convergence_outcome": (
            convergence_outcome.value if convergence_outcome is not None else None
        ),
        "convergence_result_hash": value.convergence_result_hash,
    }


def _decode_dependency(value: object) -> SliceDependency:
    """通过领域构造器恢复 Slice 依赖并重新执行其校验。"""
    payload = _mapping(value, "slice_dependency")
    return SliceDependency(
        predecessor_slice_hash=_required(payload, "predecessor_slice_hash"),
        successor_slice_hash=_required(payload, "successor_slice_hash"),
        reason_refs=tuple(_array(_required(payload, "reason_refs"), "reason_refs")),
    )


def _decode_assignment(value: object) -> SliceValidationAssignment:
    """通过领域构造器恢复验证任务分配。"""
    payload = _mapping(value, "slice_validation_assignment")
    return SliceValidationAssignment(
        execution_slice_hash=_required(payload, "execution_slice_hash"),
        validation_task_ids=tuple(
            _array(
                _required(payload, "validation_task_ids"),
                "validation_task_ids",
            )
        ),
    )


def _decode_definition(value: object) -> ExecutionSagaDefinitionV2:
    """恢复 Saga 定义；所有 hash/identity 再经过既有领域构造器校验。"""
    payload = _mapping(value, "definition")
    environment_payload = _mapping(
        _required(payload, "semantic_environment_ref"),
        "semantic_environment_ref",
    )
    dependencies = _array(
        _required(payload, "slice_dependencies"),
        "slice_dependencies",
    )
    assignments = _array(
        _required(payload, "slice_validation_assignments"),
        "slice_validation_assignments",
    )
    return ExecutionSagaDefinitionV2(
        saga_id=_required(payload, "saga_id"),
        changeset_hash=_required(payload, "changeset_hash"),
        approved_scope_hash=_required(payload, "approved_scope_hash"),
        semantic_environment_ref=SemanticEnvironmentRef(
            environment_id=_required(environment_payload, "environment_id"),
            content_hash=_required(environment_payload, "content_hash"),
        ),
        materialization_plan_hash=_required(payload, "materialization_plan_hash"),
        required_set_hash=_required(payload, "required_set_hash"),
        execution_plan_hash=_required(payload, "execution_plan_hash"),
        ordered_slice_hashes=tuple(
            _array(
                _required(payload, "ordered_slice_hashes"),
                "ordered_slice_hashes",
            )
        ),
        slice_dependencies=tuple(_decode_dependency(item) for item in dependencies),
        slice_validation_assignments=tuple(
            _decode_assignment(item) for item in assignments
        ),
        saga_definition_hash=_required(payload, "saga_definition_hash"),
    )


def _decode_slice_state(value: object) -> SliceReconciliationStateV2:
    """恢复 Slice 快照，并通过闭世界枚举/摘要校验拒绝坏数据。"""
    payload = _mapping(value, "slice_state")
    return SliceReconciliationStateV2(
        execution_slice_hash=_required(payload, "execution_slice_hash"),
        sequence_index=_required(payload, "sequence_index"),
        materialization_plan_hash=_required(payload, "materialization_plan_hash"),
        status=SliceReconciliationStatusV2(_required(payload, "status")),
        materialization_id=_optional_text(
            payload.get("materialization_id"),
            "materialization_id",
        ),
        approval_hash=_optional_text(payload.get("approval_hash"), "approval_hash"),
        grant_hash=_optional_text(payload.get("grant_hash"), "grant_hash"),
        binding_set_hash=_optional_text(
            payload.get("binding_set_hash"),
            "binding_set_hash",
        ),
        admitted_host_instance_id=_optional_text(
            payload.get("admitted_host_instance_id"),
            "admitted_host_instance_id",
        ),
        actual_delta_hash=_optional_text(
            payload.get("actual_delta_hash"),
            "actual_delta_hash",
        ),
        scope_comparison_hash=_optional_text(
            payload.get("scope_comparison_hash"),
            "scope_comparison_hash",
        ),
        verification_hash=_optional_text(
            payload.get("verification_hash"),
            "verification_hash",
        ),
        reserved_at=_optional_text(payload.get("reserved_at"), "reserved_at"),
        admitted_at=_optional_text(payload.get("admitted_at"), "admitted_at"),
        committed_at=_optional_text(payload.get("committed_at"), "committed_at"),
        reconciled_at=_optional_text(
            payload.get("reconciled_at"),
            "reconciled_at",
        ),
        failed_at=_optional_text(payload.get("failed_at"), "failed_at"),
    )


def decode_stored_saga_v2(payload: Mapping[str, object]) -> StoredExecutionSagaV2:
    """从 schema_version=1 的 JSON-compatible 载荷恢复并验证 Saga V2。"""
    normalized = _mapping(payload, "payload")
    schema_version = _required(normalized, "schema_version")
    if schema_version != _SCHEMA_VERSION or isinstance(schema_version, bool):
        raise ValueError(f"unsupported Saga V2 persistence schema: {schema_version!r}")

    slice_states = _array(
        _required(normalized, "slice_states"),
        "slice_states",
    )
    outcome_value = normalized.get("convergence_outcome")
    outcome = (
        None
        if outcome_value is None
        else SagaConvergenceOutcome(outcome_value)
    )
    return StoredExecutionSagaV2(
        definition=_decode_definition(_required(normalized, "definition")),
        saga_revision=_required(normalized, "saga_revision"),
        status=ExecutionSagaStatusV2(_required(normalized, "status")),
        slice_states=tuple(_decode_slice_state(item) for item in slice_states),
        convergence_outcome=outcome,
        convergence_result_hash=_optional_text(
            normalized.get("convergence_result_hash"),
            "convergence_result_hash",
        ),
    )


__all__ = ["decode_stored_saga_v2", "encode_stored_saga_v2"]
