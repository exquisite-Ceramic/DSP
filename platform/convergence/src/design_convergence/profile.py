"""Phase I 精确 canonical convergence profile 构造。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from design_approval_scope import ApprovalScopeBoundaryV2
from design_changeset import (
    CanonicalChangeSet,
    compute_contract_definition_fingerprint,
    validate_changeset_integrity_v2,
)
from design_orchestrator.canonical_operations import CanonicalOperationDefinition

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PROFILE_VERSION = "1.0.0"


class ConvergenceProfileError(ValueError):
    """带稳定错误码的 convergence profile 构造失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConvergenceComparisonMode(str, Enum):
    """Phase I 允许的 canonical 比较方式。"""

    EXACT_CANONICAL_VALUE = "EXACT_CANONICAL_VALUE"


def _required_text(value: object, *, field_name: str) -> str:
    """把 profile 字段规范化为非空文本。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


@dataclass(frozen=True, slots=True)
class ConvergenceFieldRule:
    """一条 provider-neutral canonical 字段比较规则。"""

    subjects_from_argument: str
    path: str
    expected_argument: str
    measurement_unit: str
    comparison_mode: ConvergenceComparisonMode

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subjects_from_argument",
            _required_text(self.subjects_from_argument, field_name="subjects_from_argument"),
        )
        object.__setattr__(self, "path", _required_text(self.path, field_name="path"))
        object.__setattr__(
            self,
            "expected_argument",
            _required_text(self.expected_argument, field_name="expected_argument"),
        )
        object.__setattr__(
            self,
            "measurement_unit",
            _required_text(self.measurement_unit, field_name="measurement_unit"),
        )
        if not isinstance(self.comparison_mode, ConvergenceComparisonMode):
            object.__setattr__(
                self,
                "comparison_mode",
                ConvergenceComparisonMode(str(self.comparison_mode)),
            )


@dataclass(frozen=True, slots=True)
class ConvergenceComparisonProfile:
    """内容寻址的 canonical convergence 比较契约。"""

    profile_version: str
    field_rules: tuple[ConvergenceFieldRule, ...]
    profile_hash: str

    def __post_init__(self) -> None:
        version = _required_text(self.profile_version, field_name="profile_version")
        rules = tuple(self.field_rules)
        if not rules or any(not isinstance(rule, ConvergenceFieldRule) for rule in rules):
            raise ValueError("field_rules requires at least one ConvergenceFieldRule")
        if not isinstance(self.profile_hash, str) or _HASH_PATTERN.fullmatch(self.profile_hash) is None:
            raise ValueError("profile_hash must be lowercase 64-hex")
        object.__setattr__(self, "profile_version", version)
        object.__setattr__(self, "field_rules", rules)


@dataclass(frozen=True, slots=True)
class ConvergenceProfileBuildRequest:
    """从已验证 ChangeSet/Scope 与 canonical definition 构造 profile 的请求。"""

    canonical_changeset: CanonicalChangeSet
    approval_scope_boundary: ApprovalScopeBoundaryV2
    canonical_operation_definition: CanonicalOperationDefinition


def _error(code: str, message: str) -> None:
    """统一抛出稳定错误码。"""
    raise ConvergenceProfileError(code, message)


def _contains_key(value: object, key: str) -> bool:
    """递归检查 verification contract 是否声明禁用字段。"""
    if isinstance(value, Mapping):
        if key in value:
            return True
        return any(_contains_key(item, key) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_key(item, key) for item in value)
    return False


def _schema_unit(definition: CanonicalOperationDefinition, argument_name: str) -> str:
    """只接受 canonical schema 明确 const 声明的测量单位。"""
    try:
        argument_schema = definition.input_schema["properties"][argument_name]
        unit_schema = argument_schema["properties"]["unit"]
        unit = unit_schema["const"]
    except (KeyError, TypeError):
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            f"{argument_name} does not expose an exact canonical unit const",
        )
    if not isinstance(unit, str) or not unit.strip():
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            f"{argument_name} canonical unit const must be a non-empty string",
        )
    return unit.strip()


def _validated_argument_unit(changeset: CanonicalChangeSet, argument_name: str) -> str:
    """从完整性已验证的 ChangeSet 读取 canonical argument 单位。"""
    argument = changeset.root_operation.arguments.get(argument_name)
    if not isinstance(argument, Mapping):
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            f"{argument_name} must be a unit-bearing canonical argument object",
        )
    unit = argument.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            f"{argument_name} must carry an explicit canonical unit",
        )
    return unit.strip()


def _validate_exact_definition(
    changeset: CanonicalChangeSet,
    definition: CanonicalOperationDefinition,
) -> None:
    """确认传入 definition 与 Step29 根操作的精确 canonical contract 一致。"""
    root = changeset.root_operation
    if (
        root.canonical_operation != definition.canonical_operation
        or root.canonical_operation_version != definition.version
    ):
        _error(
            "CONVERGENCE_PROFILE_OPERATION_CONTRACT_MISMATCH",
            "canonical operation identity/version does not match ChangeSet root operation",
        )


def _verification_assertions(
    definition: CanonicalOperationDefinition,
) -> tuple[Mapping[str, Any], ...]:
    """只接受 Phase I 冻结的 SEMANTIC_ASSERTIONS_V1 精确形状。"""
    contract = definition.verification_contract
    if _contains_key(contract, "tolerance"):
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            "canonical verification contract must not declare tolerance",
        )
    if contract.get("type") != "SEMANTIC_ASSERTIONS_V1" or contract.get("version") != "1.0.0":
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            "only SEMANTIC_ASSERTIONS_V1@1.0.0 is supported",
        )
    assertions = contract.get("assertions")
    if (
        not isinstance(assertions, list)
        or not assertions
        or any(not isinstance(item, Mapping) for item in assertions)
    ):
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            "verification contract requires at least one semantic assertion",
        )
    return tuple(assertions)


def _rule_from_assertion(
    *,
    changeset: CanonicalChangeSet,
    definition: CanonicalOperationDefinition,
    assertion: Mapping[str, Any],
) -> ConvergenceFieldRule:
    """把一个冻结 verification assertion 投影为 exact profile rule。"""
    if assertion.get("operator") != "EQUALS_ARGUMENT":
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            "only EQUALS_ARGUMENT verification assertions are supported",
        )

    subjects = assertion.get("subjects")
    if not isinstance(subjects, Mapping) or set(subjects) != {"from_argument"}:
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            "assertion subjects must use exactly one from_argument selector",
        )
    subjects_from_argument = subjects.get("from_argument")
    path = assertion.get("path")
    expected_argument = assertion.get("argument")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (subjects_from_argument, path, expected_argument)
    ):
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            "assertion subject/path/argument must be non-empty canonical strings",
        )

    subject_values = changeset.root_operation.arguments.get(subjects_from_argument)
    if (
        not isinstance(subject_values, Sequence)
        or isinstance(subject_values, (str, bytes, bytearray))
        or not subject_values
    ):
        _error(
            "CONVERGENCE_PROFILE_UNSUPPORTED",
            "subjects_from_argument must reference a non-empty canonical sequence",
        )

    canonical_unit = _schema_unit(definition, expected_argument)
    changeset_unit = _validated_argument_unit(changeset, expected_argument)
    if changeset_unit != canonical_unit:
        _error(
            "CONVERGENCE_PROFILE_OPERATION_CONTRACT_MISMATCH",
            "validated ChangeSet unit does not match canonical definition unit const",
        )

    return ConvergenceFieldRule(
        subjects_from_argument=subjects_from_argument,
        path=path,
        expected_argument=expected_argument,
        measurement_unit=canonical_unit,
        comparison_mode=ConvergenceComparisonMode.EXACT_CANONICAL_VALUE,
    )


def _validate_definition_fingerprint(
    changeset: CanonicalChangeSet,
    definition: CanonicalOperationDefinition,
) -> None:
    """在支持形状校验之后确认 definition fingerprint 没有被替换。"""
    fingerprint = compute_contract_definition_fingerprint(
        canonical_operation=definition.canonical_operation,
        canonical_operation_version=definition.version,
        argument_schema=definition.input_schema,
        effects=definition.effects,
        verification_contract=definition.verification_contract,
        existence_effects=definition.existence_effects,
        creation_contract=definition.creation_contract,
    )
    if fingerprint != changeset.root_operation.canonical_definition_fingerprint:
        _error(
            "CONVERGENCE_PROFILE_OPERATION_CONTRACT_MISMATCH",
            "canonical operation definition fingerprint does not match ChangeSet root operation",
        )


def _rule_sort_key(rule: ConvergenceFieldRule) -> tuple[str, str, str, str, str]:
    """提供稳定的 provider-neutral rule 顺序。"""
    return (
        rule.subjects_from_argument,
        rule.path,
        rule.expected_argument,
        rule.measurement_unit,
        rule.comparison_mode.value,
    )


def build_convergence_profile(
    request: ConvergenceProfileBuildRequest,
) -> ConvergenceComparisonProfile:
    """从已验证 canonical transaction 构造精确且内容寻址的 profile。"""
    if not isinstance(request, ConvergenceProfileBuildRequest):
        raise TypeError("request must be ConvergenceProfileBuildRequest")
    if not isinstance(request.canonical_changeset, CanonicalChangeSet):
        raise TypeError("canonical_changeset must be CanonicalChangeSet")
    if not isinstance(request.approval_scope_boundary, ApprovalScopeBoundaryV2):
        raise TypeError("approval_scope_boundary must be ApprovalScopeBoundaryV2")
    if not isinstance(request.canonical_operation_definition, CanonicalOperationDefinition):
        raise TypeError("canonical_operation_definition must be CanonicalOperationDefinition")

    # 必须先让 Step28/29 owner 完整性门禁通过，再读取任何 root-operation 参数。
    validate_changeset_integrity_v2(
        request.canonical_changeset,
        request.approval_scope_boundary,
    )
    changeset = request.canonical_changeset
    definition = request.canonical_operation_definition
    _validate_exact_definition(changeset, definition)

    assertions = _verification_assertions(definition)
    rules = tuple(
        sorted(
            (
                _rule_from_assertion(
                    changeset=changeset,
                    definition=definition,
                    assertion=assertion,
                )
                for assertion in assertions
            ),
            key=_rule_sort_key,
        )
    )
    _validate_definition_fingerprint(changeset, definition)

    # 延迟导入避免 hashing 对 profile 类型定义形成循环依赖。
    from .hashing import compute_convergence_profile_hash

    profile_hash = compute_convergence_profile_hash(_PROFILE_VERSION, rules)
    return ConvergenceComparisonProfile(
        profile_version=_PROFILE_VERSION,
        field_rules=rules,
        profile_hash=profile_hash,
    )


__all__ = [
    "ConvergenceComparisonMode",
    "ConvergenceComparisonProfile",
    "ConvergenceFieldRule",
    "ConvergenceProfileBuildRequest",
    "ConvergenceProfileError",
    "build_convergence_profile",
]
