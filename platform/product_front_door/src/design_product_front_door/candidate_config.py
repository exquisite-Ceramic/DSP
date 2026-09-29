"""Versioned configured-Revit candidate authority 的最小 source-only 实现。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from design_changeset import canonical_hash

from .contracts import ConfiguredRevitCandidate, configured_revit_candidate_hash_body

_CONFIG_VERSION = "DSP_REVIT_CANDIDATES_V1"
_CANDIDATE_FIELDS = frozenset(
    {
        "candidate_key",
        "project_id",
        "transport_locator",
        "document_id",
        "semantic_target_id",
        "native_target_unique_id",
    }
)


def _config_error(message: str) -> ValueError:
    """统一 candidate config 的结构错误码，避免调用方依赖 Python 解析异常文本。"""

    return ValueError(f"FRONT_DOOR_CANDIDATE_CONFIG_INVALID: {message}")


def _candidate_body(raw_candidate: object) -> dict[str, str]:
    """把一个配置条目收敛成 exact v1 authority body，不接受未知或缺失字段。"""

    if not isinstance(raw_candidate, Mapping):
        raise _config_error("candidate entry must be a mapping")
    if set(raw_candidate) != _CANDIDATE_FIELDS:
        raise _config_error("candidate entry keys do not match DSP_REVIT_CANDIDATES_V1")

    body: dict[str, str] = {}
    for field_name in _CANDIDATE_FIELDS:
        value = raw_candidate[field_name]
        if not isinstance(value, str) or not value.strip():
            raise _config_error(f"{field_name} must be a non-blank string")
        body[field_name] = value.strip()
    return body


@dataclass(frozen=True, slots=True)
class ConfiguredRevitCandidateCatalog:
    """按 exact candidate_key 提供 deterministic configured candidate 的内存 catalog。"""

    _candidates: Mapping[str, ConfiguredRevitCandidate]

    @classmethod
    def from_mapping(cls, payload: object) -> ConfiguredRevitCandidateCatalog:
        """解析冻结的 V1 配置形状；不读取环境状态，也不从 Revit 路径推断 project_id。"""

        if not isinstance(payload, Mapping):
            raise _config_error("candidate config must be a mapping")
        if set(payload) != {"version", "candidates"}:
            raise _config_error("top-level keys must be exactly version and candidates")
        if payload.get("version") != _CONFIG_VERSION:
            raise ValueError(
                "FRONT_DOOR_CANDIDATE_CONFIG_VERSION_INVALID: unsupported candidate config version"
            )

        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            raise _config_error("candidates must be a list")

        candidates: dict[str, ConfiguredRevitCandidate] = {}
        for raw_candidate in raw_candidates:
            body = _candidate_body(raw_candidate)
            candidate_key = body["candidate_key"]
            if candidate_key in candidates:
                raise ValueError(
                    "FRONT_DOOR_CANDIDATE_KEY_DUPLICATE: candidate_key must be unique"
                )

            # 只对规范化后的 authority body 使用仓库 canonical_hash；配置中不接受调用方
            # 自带 hash，从而避免把未经验证的 digest 提升为 candidate authority。
            hash_body = configured_revit_candidate_hash_body(
                candidate_key=body["candidate_key"],
                project_id=body["project_id"],
                transport_locator=body["transport_locator"],
                document_id=body["document_id"],
                semantic_target_id=body["semantic_target_id"],
                native_target_unique_id=body["native_target_unique_id"],
            )
            candidate = ConfiguredRevitCandidate(
                **body,
                candidate_hash=canonical_hash(hash_body),
            )
            candidates[candidate_key] = candidate

        return cls(_candidates=MappingProxyType(candidates))

    def get(self, candidate_key: str) -> ConfiguredRevitCandidate | None:
        """按 exact key 读取 candidate；未知 key 返回 None，禁止 latest/fuzzy fallback。"""

        if not isinstance(candidate_key, str) or not candidate_key.strip():
            return None
        return self._candidates.get(candidate_key.strip())


__all__ = ["ConfiguredRevitCandidateCatalog"]
