"""Phase I Step33 V2 的不可变 Saga 定义契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from design_changeset import canonical_hash
from semantic_runtime import SemanticEnvironmentRef

from .saga_contracts import SliceDependency, SliceValidationAssignment

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _text(value: object, field_name: str) -> str:
    """规范化不可为空的文本字段。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _digest(value: object, field_name: str) -> str:
    """规范化 SHA-256 小写十六进制摘要。"""
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _digests(values, field_name: str) -> tuple[str, ...]:
    """保留调用方给出的顺序，同时拒绝重复 Slice 摘要。"""
    normalized = tuple(_digest(value, field_name) for value in values)
    if not normalized:
        raise ValueError(f"{field_name} requires at least one value")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} values must be unique")
    return normalized


def _environment_payload(value: SemanticEnvironmentRef) -> dict[str, str]:
    """把语义环境身份投影为稳定哈希载荷。"""
    return {
        "environment_id": value.environment_id,
        "content_hash": value.content_hash,
    }


def _dependency_payload(value: SliceDependency) -> dict[str, object]:
    """把 Slice 依赖投影为稳定哈希载荷。"""
    return {
        "predecessor_slice_hash": value.predecessor_slice_hash,
        "successor_slice_hash": value.successor_slice_hash,
        "reason_refs": list(value.reason_refs),
    }


def _assignment_payload(value: SliceValidationAssignment) -> dict[str, object]:
    """把本地验证任务分配投影为稳定哈希载荷。"""
    return {
        "execution_slice_hash": value.execution_slice_hash,
        "validation_task_ids": list(value.validation_task_ids),
    }


@dataclass(frozen=True, slots=True)
class ExecutionSagaDefinitionV2:
    """绑定 REQUIRED materialization 集合与本地执行顺序的 Saga V2 定义。"""

    saga_id: str
    changeset_hash: str
    approved_scope_hash: str
    semantic_environment_ref: SemanticEnvironmentRef
    materialization_plan_hash: str
    required_set_hash: str
    execution_plan_hash: str
    ordered_slice_hashes: tuple[str, ...]
    slice_dependencies: tuple[SliceDependency, ...]
    slice_validation_assignments: tuple[SliceValidationAssignment, ...]
    saga_definition_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "saga_id", _text(self.saga_id, "saga_id"))
        for field_name in (
            "changeset_hash",
            "approved_scope_hash",
            "materialization_plan_hash",
            "required_set_hash",
            "execution_plan_hash",
            "saga_definition_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _digest(getattr(self, field_name), field_name),
            )
        if not isinstance(self.semantic_environment_ref, SemanticEnvironmentRef):
            raise TypeError("semantic_environment_ref must be SemanticEnvironmentRef")
        object.__setattr__(
            self,
            "ordered_slice_hashes",
            _digests(self.ordered_slice_hashes, "ordered_slice_hash"),
        )

        dependencies = tuple(self.slice_dependencies)
        if any(not isinstance(item, SliceDependency) for item in dependencies):
            raise TypeError("slice_dependencies contains invalid values")
        dependency_keys = tuple(
            (item.predecessor_slice_hash, item.successor_slice_hash)
            for item in dependencies
        )
        if len(set(dependency_keys)) != len(dependency_keys):
            raise ValueError("slice_dependencies contains duplicate Slice edges")
        object.__setattr__(
            self,
            "slice_dependencies",
            tuple(
                sorted(
                    dependencies,
                    key=lambda item: (
                        item.predecessor_slice_hash,
                        item.successor_slice_hash,
                        item.reason_refs,
                    ),
                )
            ),
        )

        assignments = tuple(self.slice_validation_assignments)
        if any(not isinstance(item, SliceValidationAssignment) for item in assignments):
            raise TypeError("slice_validation_assignments contains invalid values")
        assignment_hashes = tuple(item.execution_slice_hash for item in assignments)
        if len(set(assignment_hashes)) != len(assignment_hashes):
            raise ValueError("each Slice may have only one validation assignment")
        object.__setattr__(
            self,
            "slice_validation_assignments",
            tuple(sorted(assignments, key=lambda item: item.execution_slice_hash)),
        )


def compute_execution_saga_definition_hash_v2(
    definition: ExecutionSagaDefinitionV2,
) -> str:
    """对不含 construction id/hash 的 Saga V2 语义体计算 canonical hash。"""
    if not isinstance(definition, ExecutionSagaDefinitionV2):
        raise TypeError("definition must be ExecutionSagaDefinitionV2")
    return canonical_hash(
        {
            "version": "EXECUTION_SAGA_DEFINITION_V2",
            "changeset_hash": definition.changeset_hash,
            "approved_scope_hash": definition.approved_scope_hash,
            "semantic_environment_ref": _environment_payload(
                definition.semantic_environment_ref
            ),
            "materialization_plan_hash": definition.materialization_plan_hash,
            "required_set_hash": definition.required_set_hash,
            "execution_plan_hash": definition.execution_plan_hash,
            "ordered_slice_hashes": list(definition.ordered_slice_hashes),
            "slice_dependencies": [
                _dependency_payload(item) for item in definition.slice_dependencies
            ],
            "slice_validation_assignments": [
                _assignment_payload(item)
                for item in definition.slice_validation_assignments
            ],
        }
    )


__all__ = [
    "ExecutionSagaDefinitionV2",
    "compute_execution_saga_definition_hash_v2",
]
