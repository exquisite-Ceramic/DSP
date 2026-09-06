"""Convergence comparison profile 的 canonical SHA-256 哈希。"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .profile import ConvergenceFieldRule


def _required_text(value: object, *, field_name: str) -> str:
    """规范化哈希输入中的必填文本。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _rule_payload(rule: ConvergenceFieldRule) -> dict[str, str]:
    """把规则投影成与 dataclass 实现细节无关的 canonical payload。"""
    from .profile import ConvergenceFieldRule

    if not isinstance(rule, ConvergenceFieldRule):
        raise TypeError("field_rules entries must be ConvergenceFieldRule")
    return {
        "subjects_from_argument": rule.subjects_from_argument,
        "path": rule.path,
        "expected_argument": rule.expected_argument,
        "measurement_unit": rule.measurement_unit,
        "comparison_mode": rule.comparison_mode.value,
    }


def compute_convergence_profile_hash(
    profile_version: str,
    field_rules: tuple[ConvergenceFieldRule, ...],
) -> str:
    """按语义内容排序规则后计算稳定 SHA-256。"""
    version = _required_text(profile_version, field_name="profile_version")
    rules = tuple(field_rules)
    if not rules:
        raise ValueError("field_rules requires at least one rule")
    payloads = sorted(
        (_rule_payload(rule) for rule in rules),
        key=lambda item: (
            item["subjects_from_argument"],
            item["path"],
            item["expected_argument"],
            item["measurement_unit"],
            item["comparison_mode"],
        ),
    )
    material = {
        "profile_version": version,
        "field_rules": payloads,
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


__all__ = ["compute_convergence_profile_hash"]
