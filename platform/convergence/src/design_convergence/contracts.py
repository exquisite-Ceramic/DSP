"""Phase I provider-neutral convergence 证据与结果契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ConvergenceVerificationError(ValueError):
    """携带稳定错误码的 convergence 验证失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _required_text(code, "code")


class ConvergenceStatus(str, Enum):
    """Phase I convergence 的闭集结果状态。"""

    CONVERGED = "CONVERGED"
    DIVERGED = "DIVERGED"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"


def _required_text(value: object, field_name: str) -> str:
    """规范化一个必填文本字段。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _required_digest(value: object, field_name: str) -> str:
    """验证一个小写 SHA-256 摘要。"""
    normalized = _required_text(value, field_name)
    if _HASH_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase 64-hex SHA-256")
    return normalized


@dataclass(frozen=True, slots=True)
class CanonicalFieldEvidence:
    """一个 profile 所要求的 canonical 字段值。"""

    path: str
    value: Any
    unit: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _required_text(self.path, "path"))
        object.__setattr__(self, "unit", _required_text(self.unit, "unit"))


@dataclass(frozen=True, slots=True)
class MaterializationCanonicalEvidence:
    """一个 REQUIRED materialization 的 canonical post-state 证据。"""

    materialization_id: str
    semantic_id: str
    execution_slice_hash: str
    actual_delta_hash: str
    verification_hash: str
    semantic_environment_ref: Any
    post_execution_projection_ref: Any
    canonical_kind: str
    verified_fields: tuple[CanonicalFieldEvidence, ...]
    evidence_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "materialization_id",
            _required_text(self.materialization_id, "materialization_id"),
        )
        object.__setattr__(self, "semantic_id", _required_text(self.semantic_id, "semantic_id"))
        object.__setattr__(self, "canonical_kind", _required_text(self.canonical_kind, "canonical_kind"))
        for field_name in (
            "execution_slice_hash",
            "actual_delta_hash",
            "verification_hash",
            "evidence_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_digest(getattr(self, field_name), field_name),
            )
        normalized = tuple(self.verified_fields)
        if not normalized or any(not isinstance(item, CanonicalFieldEvidence) for item in normalized):
            raise ValueError("verified_fields requires CanonicalFieldEvidence values")
        paths = tuple(item.path for item in normalized)
        if len(paths) != len(set(paths)):
            raise ValueError("verified_fields paths must be unique")
        object.__setattr__(
            self,
            "verified_fields",
            tuple(sorted(normalized, key=lambda item: item.path)),
        )


@dataclass(frozen=True, slots=True)
class ConvergenceEvidenceSet:
    """绑定 immutable required set 的完整 canonical convergence 证据集。"""

    materialization_plan_hash: str
    required_set_hash: str
    convergence_profile_hash: str
    semantic_environment_ref: Any
    evidence_items: tuple[MaterializationCanonicalEvidence, ...]
    evidence_set_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "materialization_plan_hash",
            "required_set_hash",
            "convergence_profile_hash",
            "evidence_set_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_digest(getattr(self, field_name), field_name),
            )
        normalized = tuple(self.evidence_items)
        if not normalized or any(
            not isinstance(item, MaterializationCanonicalEvidence) for item in normalized
        ):
            raise ValueError("evidence_items requires MaterializationCanonicalEvidence values")
        object.__setattr__(
            self,
            "evidence_items",
            tuple(sorted(normalized, key=lambda item: (item.materialization_id, item.semantic_id))),
        )


@dataclass(frozen=True, slots=True)
class ConvergenceResult:
    """内容寻址的 exact cross-materialization convergence 结果。"""

    status: ConvergenceStatus | str
    materialization_plan_hash: str
    required_set_hash: str
    convergence_profile_hash: str
    evidence_set_hash: str
    convergence_result_hash: str

    def __post_init__(self) -> None:
        status = self.status if isinstance(self.status, ConvergenceStatus) else ConvergenceStatus(str(self.status))
        object.__setattr__(self, "status", status)
        for field_name in (
            "materialization_plan_hash",
            "required_set_hash",
            "convergence_profile_hash",
            "evidence_set_hash",
            "convergence_result_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_digest(getattr(self, field_name), field_name),
            )


__all__ = [
    "CanonicalFieldEvidence",
    "ConvergenceEvidenceSet",
    "ConvergenceResult",
    "ConvergenceStatus",
    "ConvergenceVerificationError",
    "MaterializationCanonicalEvidence",
]
