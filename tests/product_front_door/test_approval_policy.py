"""Task 5 Step 1：configured product approval policy normalization / default-deny 契约。"""

from __future__ import annotations

from copy import deepcopy

import design_product_front_door as front_door
import pytest
from design_changeset import canonical_hash


def _policy_type():
    """延迟取得 Task 5 policy 类型，使尚未实现时形成明确 TDD RED。"""

    policy_type = getattr(front_door, "ConfiguredProductApprovalPolicy", None)
    assert policy_type is not None, "ConfiguredProductApprovalPolicy 尚未实现"
    return policy_type


def _valid_payload() -> dict[str, object]:
    """返回 approved plan 冻结的最小 wall-thickness policy 配置。"""

    return {
        "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
        "policy_id": "local-wall-thickness-v1",
        "principal": "local:operator",
        "project_ids": ["project-001"],
        "allowed_canonical_operations": ["set_wall_thickness.v1"],
        "admission_ttl_seconds": 900,
    }


def test_policy_normalizes_exact_authority_body_and_uses_repository_canonical_hash() -> None:
    """policy hash 必须只来自规范化 authority body，且列表顺序不能改变 identity。"""

    policy_type = _policy_type()
    payload = _valid_payload()
    payload["project_ids"] = [" project-002 ", "project-001"]
    payload["allowed_canonical_operations"] = [
        "set_wall_thickness.v1",
        "inspect_wall.v1",
    ]

    policy = policy_type.from_mapping(payload)

    expected_body = {
        "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
        "policy_id": "local-wall-thickness-v1",
        "principal": "local:operator",
        "project_ids": ["project-001", "project-002"],
        "allowed_canonical_operations": ["inspect_wall.v1", "set_wall_thickness.v1"],
        "admission_ttl_seconds": 900,
    }
    assert policy.version == "DSP_PRODUCT_APPROVAL_POLICY_V1"
    assert policy.policy_id == "local-wall-thickness-v1"
    assert policy.principal == "local:operator"
    assert policy.project_ids == ("project-001", "project-002")
    assert policy.allowed_canonical_operations == (
        "inspect_wall.v1",
        "set_wall_thickness.v1",
    )
    assert policy.admission_ttl_seconds == 900
    assert policy.policy_snapshot_hash == canonical_hash(expected_body)

    reordered = deepcopy(payload)
    reordered["project_ids"] = ["project-001", "project-002"]
    reordered["allowed_canonical_operations"] = [
        "inspect_wall.v1",
        "set_wall_thickness.v1",
    ]
    assert policy_type.from_mapping(reordered).policy_snapshot_hash == policy.policy_snapshot_hash


def test_policy_authorizes_only_complete_exact_canonical_operation_set() -> None:
    """当前 vertical 必须显式授权 exact operation，不能用 provider/tool 名近似替代。"""

    policy_type = _policy_type()
    policy = policy_type.from_mapping(_valid_payload())

    policy.authorize(
        project_id="project-001",
        required_canonical_operations=("set_wall_thickness.v1",),
    )

    wrong = _valid_payload()
    wrong["allowed_canonical_operations"] = ["set_wall_thickness"]
    wrong_policy = policy_type.from_mapping(wrong)
    with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY_DENIED"):
        wrong_policy.authorize(
            project_id="project-001",
            required_canonical_operations=("set_wall_thickness.v1",),
        )

    incomplete = _valid_payload()
    incomplete["allowed_canonical_operations"] = ["set_wall_thickness.v1"]
    incomplete_policy = policy_type.from_mapping(incomplete)
    with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY_DENIED"):
        incomplete_policy.authorize(
            project_id="project-001",
            required_canonical_operations=(
                "set_wall_thickness.v1",
                "inspect_wall.v1",
            ),
        )


def test_policy_default_denies_project_mismatch_and_empty_required_operation_set() -> None:
    """project 不在 immutable allowlist 或 required operation 集为空时都不能签发新 admission。"""

    policy_type = _policy_type()
    policy = policy_type.from_mapping(_valid_payload())

    with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY_DENIED"):
        policy.authorize(
            project_id="project-other",
            required_canonical_operations=("set_wall_thickness.v1",),
        )

    with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY_DENIED"):
        policy.authorize(
            project_id="project-001",
            required_canonical_operations=(),
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.update(version="UNKNOWN"),
        lambda payload: payload.update(policy_id=" "),
        lambda payload: payload.update(principal=" "),
        lambda payload: payload.update(project_ids=[]),
        lambda payload: payload.update(project_ids=["project-001", "project-001"]),
        lambda payload: payload.update(project_ids=["project-001", " "]),
        lambda payload: payload.update(allowed_canonical_operations=[]),
        lambda payload: payload.update(
            allowed_canonical_operations=["set_wall_thickness.v1", "set_wall_thickness.v1"]
        ),
        lambda payload: payload.update(allowed_canonical_operations=[" "]),
        lambda payload: payload.update(admission_ttl_seconds=0),
        lambda payload: payload.update(admission_ttl_seconds=-1),
        lambda payload: payload.update(admission_ttl_seconds=True),
        lambda payload: payload.update(admission_ttl_seconds=900.5),
    ],
)
def test_policy_rejects_malformed_or_non_authoritative_config(mutator) -> None:
    """未知版本、空/重复 allowlist 与非正整数 TTL 一律不能成为 admission authority。"""

    policy_type = _policy_type()
    payload = _valid_payload()
    mutator(payload)

    with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY"):
        policy_type.from_mapping(payload)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"version": "DSP_PRODUCT_APPROVAL_POLICY_V1"},
        {
            **_valid_payload(),
            "unknown": "must-fail-closed",
        },
    ],
)
def test_missing_or_expanded_policy_config_denies_new_issuance(payload: object) -> None:
    """缺失配置或未知字段不是 permissive fallback；new issuance 必须 fail closed。"""

    policy_type = _policy_type()

    with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY"):
        policy_type.from_mapping(payload)
