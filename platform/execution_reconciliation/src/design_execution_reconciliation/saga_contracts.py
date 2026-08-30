"""Immutable provider-neutral contracts for the Step33 Saga definition."""

from __future__ import annotations

import re
from dataclasses import dataclass

from semantic_runtime import SemanticEnvironmentRef

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _digest(value: object, field_name: str) -> str:
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _texts(values, field_name: str) -> tuple[str, ...]:
    return tuple(sorted({_text(value, field_name) for value in values}))


def _digests(values, field_name: str) -> tuple[str, ...]:
    normalized = tuple(_digest(value, field_name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} values must be unique")
    return normalized


@dataclass(frozen=True, slots=True)
class SliceDependency:
    predecessor_slice_hash: str
    successor_slice_hash: str
    reason_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "predecessor_slice_hash",
            _digest(self.predecessor_slice_hash, "predecessor_slice_hash"),
        )
        object.__setattr__(
            self,
            "successor_slice_hash",
            _digest(self.successor_slice_hash, "successor_slice_hash"),
        )
        if self.predecessor_slice_hash == self.successor_slice_hash:
            raise ValueError("SliceDependency cannot self-reference")
        reasons = _texts(self.reason_refs, "reason_ref")
        if not reasons:
            raise ValueError("SliceDependency requires at least one reason_ref")
        object.__setattr__(self, "reason_refs", reasons)


@dataclass(frozen=True, slots=True)
class SliceValidationAssignment:
    execution_slice_hash: str
    validation_task_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "execution_slice_hash",
            _digest(self.execution_slice_hash, "execution_slice_hash"),
        )
        object.__setattr__(
            self,
            "validation_task_ids",
            _texts(self.validation_task_ids, "validation_task_id"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionSagaDefinition:
    saga_id: str
    changeset_hash: str
    approved_scope_hash: str
    semantic_environment_ref: SemanticEnvironmentRef
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

        ordered = _digests(self.ordered_slice_hashes, "ordered_slice_hash")
        if not ordered:
            raise ValueError("ordered_slice_hashes requires at least one Slice")
        object.__setattr__(self, "ordered_slice_hashes", ordered)

        dependencies = tuple(self.slice_dependencies)
        if any(not isinstance(item, SliceDependency) for item in dependencies):
            raise TypeError("slice_dependencies contains invalid values")
        dependency_keys = [
            (item.predecessor_slice_hash, item.successor_slice_hash)
            for item in dependencies
        ]
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
        assignment_hashes = [item.execution_slice_hash for item in assignments]
        if len(set(assignment_hashes)) != len(assignment_hashes):
            raise ValueError("each Slice may have only one validation assignment")
        object.__setattr__(
            self,
            "slice_validation_assignments",
            tuple(sorted(assignments, key=lambda item: item.execution_slice_hash)),
        )


__all__ = [
    "ExecutionSagaDefinition",
    "SliceDependency",
    "SliceValidationAssignment",
]
