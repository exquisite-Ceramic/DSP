"""Cross-Host Product Vertical Task 7：V2 stable policy contract。"""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module

import pytest
from design_changeset import canonical_hash


def _api():
    """延迟加载 V2 policy，使 RED 精确落在 Task 7 capability 缺失。"""

    module = import_module("design_product_front_door.approval_policy_v2")
    policy_type = getattr(module, "ConfiguredProductApprovalPolicyV2", None)
    assert policy_type is not None, "ConfiguredProductApprovalPolicyV2 尚未实现"
    return module, policy_type


def _payload() -> dict[str, object]:
    """返回 exact two-Host stable policy 配置；不含 runtime/transport identity。"""

    return {
        "version": "DSP_PRODUCT_APPROVAL_POLICY_V2",
        "policy_id": "cross-host-wall-thickness-v2",
        "principal": "local:operator",
        "project_ids": ["project-id"],
        "allowed_canonical_operations": ["set_wall_thickness.v1"],
        "reviewed_configuration_hash": "a" * 64,
        "semantic_target_ids": ["WALL-001"],
        "allowed_topology_snapshot_hashes": ["b" * 64],
        "required_host_roles": {
            "AUTOCAD": "BOUND_REQUIRED",
            "REVIT": "INITIATOR",
        },
        "admission_ttl_seconds": 900,
    }


def test_v2_policy_normalizes_exact_stable_authority_body() -> None:
    """policy hash 只覆盖 stable reviewed capability；runtime endpoint 不得参与。"""

    _, policy_type = _api()
    payload = _payload()
    policy = policy_type.from_mapping(payload)

    expected = deepcopy(payload)
    expected["project_ids"] = ["project-id"]
    expected["allowed_canonical_operations"] = ["set_wall_thickness.v1"]
    expected["semantic_target_ids"] = ["WALL-001"]
    expected["allowed_topology_snapshot_hashes"] = ["b" * 64]
    expected["required_host_roles"] = {
        "AUTOCAD": "BOUND_REQUIRED",
        "REVIT": "INITIATOR",
    }

    assert policy.version == "DSP_PRODUCT_APPROVAL_POLICY_V2"
    assert policy.policy_snapshot_hash == canonical_hash(expected)
    assert not hasattr(policy, "host_instance_id")
    assert not hasattr(policy, "transport_locator")


def test_runtime_restart_identity_does_not_change_policy_snapshot_hash() -> None:
    """runtime 重建不要求改 policy；瞬态字段甚至不能进入 policy config。"""

    _, policy_type = _api()
    first = policy_type.from_mapping(_payload())
    second = policy_type.from_mapping(deepcopy(_payload()))
    assert first.policy_snapshot_hash == second.policy_snapshot_hash

    expanded = _payload()
    expanded["host_instance_id"] = "revit-runtime-after-restart"
    with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY"):
        policy_type.from_mapping(expanded)

    expanded = _payload()
    expanded["transport_locator"] = "new-pipe-after-restart"
    with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY"):
        policy_type.from_mapping(expanded)


def test_v2_policy_allows_exact_project_operation_target_topology_and_host_roles() -> None:
    """V2 policy 必须同时授权 project/op/semantic target/topology/required Host roles。"""

    _, policy_type = _api()
    policy = policy_type.from_mapping(_payload())

    policy.authorize(
        project_id="project-id",
        required_canonical_operations=("set_wall_thickness.v1",),
        semantic_target_id="WALL-001",
        topology_snapshot_hash="b" * 64,
        required_host_roles={
            "AUTOCAD": "BOUND_REQUIRED",
            "REVIT": "INITIATOR",
        },
    )


@pytest.mark.parametrize(
    "required_host_roles",
    [
        {"REVIT": "INITIATOR"},
        {
            "AUTOCAD": "BOUND_REQUIRED",
            "REVIT": "INITIATOR",
            "IFC": "BOUND_REQUIRED",
        },
        {
            "AUTOCAD": "INITIATOR",
            "REVIT": "BOUND_REQUIRED",
        },
    ],
)
def test_policy_default_denies_missing_extra_or_wrong_required_host(
    required_host_roles: dict[str, str],
) -> None:
    """required Host 集合必须 exact match；不能缺失、扩张或角色互换。"""

    _, policy_type = _api()
    policy = policy_type.from_mapping(_payload())

    with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY_DENIED"):
        policy.authorize(
            project_id="project-id",
            required_canonical_operations=("set_wall_thickness.v1",),
            semantic_target_id="WALL-001",
            topology_snapshot_hash="b" * 64,
            required_host_roles=required_host_roles,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("semantic_target_id", "WALL-OTHER"),
        ("topology_snapshot_hash", "c" * 64),
    ],
)
def test_policy_default_denies_target_or_topology_mismatch(
    field: str,
    value: str,
) -> None:
    """semantic target 与 topology 都是 V2 stable authorization dimensions。"""

    _, policy_type = _api()
    policy = policy_type.from_mapping(_payload())
    kwargs = {
        "project_id": "project-id",
        "required_canonical_operations": ("set_wall_thickness.v1",),
        "semantic_target_id": "WALL-001",
        "topology_snapshot_hash": "b" * 64,
        "required_host_roles": {
            "AUTOCAD": "BOUND_REQUIRED",
            "REVIT": "INITIATOR",
        },
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY_DENIED"):
        policy.authorize(**kwargs)
