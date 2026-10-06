"""Cross-Host Operation Proposal 的 immutable human-subject artifacts。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

_SHA256_HEX = frozenset("0123456789abcdef")
_REQUIRED_HOSTS = ("AUTOCAD", "REVIT")
_ERROR = "CROSS_HOST_PROPOSAL_SUBJECT_INVALID"


def _text(value: object, field_name: str) -> str:
    """规范化 human-subject identity 文本，拒绝空白 locator。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{_ERROR}: {field_name} must be a non-blank string")
    return value.strip()


def _sha256(value: object, field_name: str) -> str:
    """只接受 canonical lowercase SHA-256 lineage。"""

    normalized = _text(value, field_name)
    if len(normalized) != 64 or any(char not in _SHA256_HEX for char in normalized):
        raise ValueError(f"{_ERROR}: {field_name} must be lowercase SHA-256")
    return normalized


def _revision(value: object) -> int:
    """Host revision 必须是非负整数；bool 不得借 Python int 兼容性混入。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{_ERROR}: host_revision must be a non-negative integer")
    return value


def _thickness(value: object) -> float:
    """展示给用户的规范墙厚必须是有限正数毫米值。"""

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise ValueError(
            f"{_ERROR}: normalized_thickness_mm must be a finite positive number"
        )
    return float(value)


def _freeze_json(value: object, *, context: str) -> object:
    """递归冻结 canonical operation arguments，禁止调用方在 hash 后改写 subject。"""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{_ERROR}: {context} contains non-finite number")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{_ERROR}: {context} requires string keys")
        return MappingProxyType(
            {
                key: _freeze_json(value[key], context=f"{context}.{key}")
                for key in sorted(value)
            }
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(
            _freeze_json(item, context=f"{context}[]")
            for item in value
        )
    raise ValueError(
        f"{_ERROR}: {context} contains unsupported value type {type(value).__name__}"
    )


def _plain_json(value: object) -> object:
    """把冻结 arguments 投影为 canonical JSON-compatible body。"""

    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {key: _plain_json(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    raise TypeError(f"unsupported frozen JSON value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class CrossHostProposalObservationV2:
    """用户 proposal 中实际展示的一条 Host observation。

    observed_at 与 command_id 属于不可变审计 provenance，会进入完整 subject hash；
    stable_state_body() 则只返回后续 Gate A/B 连续性比较允许使用的稳定状态字段。
    """

    host_kind: str
    host_instance_id: str
    document_id: str
    native_target_id: str
    semantic_target_id: str
    host_revision: int
    normalized_thickness_mm: float
    observed_at: str
    command_id: str

    def __post_init__(self) -> None:
        """规范化 exact Host identity、revision、厚度与 provenance。"""

        host_kind = _text(self.host_kind, "host_kind")
        if host_kind not in _REQUIRED_HOSTS:
            raise ValueError(f"{_ERROR}: host_kind must be AUTOCAD or REVIT")
        object.__setattr__(self, "host_kind", host_kind)
        object.__setattr__(
            self,
            "host_instance_id",
            _text(self.host_instance_id, "host_instance_id"),
        )
        object.__setattr__(self, "document_id", _text(self.document_id, "document_id"))
        object.__setattr__(
            self,
            "native_target_id",
            _text(self.native_target_id, "native_target_id"),
        )
        object.__setattr__(
            self,
            "semantic_target_id",
            _text(self.semantic_target_id, "semantic_target_id"),
        )
        object.__setattr__(self, "host_revision", _revision(self.host_revision))
        object.__setattr__(
            self,
            "normalized_thickness_mm",
            _thickness(self.normalized_thickness_mm),
        )
        object.__setattr__(self, "observed_at", _text(self.observed_at, "observed_at"))
        object.__setattr__(self, "command_id", _text(self.command_id, "command_id"))

    def stable_state_body(self) -> dict[str, object]:
        """返回 Gate A/B 比较体；明确排除重新采集会变化的 provenance 字段。"""

        return {
            "host_kind": self.host_kind,
            "host_instance_id": self.host_instance_id,
            "document_id": self.document_id,
            "native_target_id": self.native_target_id,
            "semantic_target_id": self.semantic_target_id,
            "host_revision": self.host_revision,
            "normalized_thickness_mm": self.normalized_thickness_mm,
        }


def _canonical_observations(
    observations: Sequence[CrossHostProposalObservationV2],
) -> tuple[CrossHostProposalObservationV2, CrossHostProposalObservationV2]:
    """要求 exact AutoCAD+Revit observations，并按 Host kind 固定顺序。"""

    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise TypeError(f"{_ERROR}: observations must be a sequence")
    values = tuple(observations)
    if len(values) != 2 or any(
        not isinstance(item, CrossHostProposalObservationV2) for item in values
    ):
        raise ValueError(
            f"{_ERROR}: observations must contain exactly two proposal observations"
        )
    by_kind = {item.host_kind: item for item in values}
    if len(by_kind) != 2 or set(by_kind) != set(_REQUIRED_HOSTS):
        raise ValueError(
            f"{_ERROR}: observations must contain exactly AUTOCAD and REVIT"
        )
    return by_kind["AUTOCAD"], by_kind["REVIT"]


@dataclass(frozen=True, slots=True)
class CrossHostOperationProposalSubjectV2:
    """一次 human decision 所针对的 immutable cross-Host proposal subject。"""

    request_hash: str
    session_binding_hash: str
    topology_snapshot_hash: str
    semantic_target_id: str
    semantic_environment_id: str
    semantic_environment_hash: str
    canonical_operation: str
    canonical_arguments: Mapping[str, object]
    observations: tuple[
        CrossHostProposalObservationV2,
        CrossHostProposalObservationV2,
    ]

    def __post_init__(self) -> None:
        """冻结 request/binding/topology/operation 与用户实际看到的两端 observation。"""

        request_hash = _sha256(self.request_hash, "request_hash")
        session_binding_hash = _sha256(
            self.session_binding_hash,
            "session_binding_hash",
        )
        topology_snapshot_hash = _sha256(
            self.topology_snapshot_hash,
            "topology_snapshot_hash",
        )
        semantic_target_id = _text(self.semantic_target_id, "semantic_target_id")
        semantic_environment_id = _text(
            self.semantic_environment_id,
            "semantic_environment_id",
        )
        semantic_environment_hash = _sha256(
            self.semantic_environment_hash,
            "semantic_environment_hash",
        )
        canonical_operation = _text(self.canonical_operation, "canonical_operation")
        if not isinstance(self.canonical_arguments, Mapping):
            raise TypeError(f"{_ERROR}: canonical_arguments must be a mapping")
        frozen_arguments = _freeze_json(
            self.canonical_arguments,
            context="canonical_arguments",
        )
        if not isinstance(frozen_arguments, Mapping):
            raise TypeError(f"{_ERROR}: canonical_arguments must remain a mapping")
        observations = _canonical_observations(self.observations)
        if any(item.semantic_target_id != semantic_target_id for item in observations):
            raise ValueError(
                f"{_ERROR}: observation semantic target does not match proposal subject"
            )

        object.__setattr__(self, "request_hash", request_hash)
        object.__setattr__(self, "session_binding_hash", session_binding_hash)
        object.__setattr__(self, "topology_snapshot_hash", topology_snapshot_hash)
        object.__setattr__(self, "semantic_target_id", semantic_target_id)
        object.__setattr__(self, "semantic_environment_id", semantic_environment_id)
        object.__setattr__(
            self,
            "semantic_environment_hash",
            semantic_environment_hash,
        )
        object.__setattr__(self, "canonical_operation", canonical_operation)
        object.__setattr__(self, "canonical_arguments", frozen_arguments)
        object.__setattr__(self, "observations", observations)

    def canonical_arguments_body(self) -> dict[str, object]:
        """返回 codec/hash 可使用的普通 JSON body，不暴露内部可变引用。"""

        body = _plain_json(self.canonical_arguments)
        if not isinstance(body, dict):
            raise TypeError("canonical_arguments did not decode to an object")
        return body


__all__ = [
    "CrossHostOperationProposalSubjectV2",
    "CrossHostProposalObservationV2",
]
