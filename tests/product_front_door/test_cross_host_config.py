"""Cross-Host Product Vertical Task 2：reviewed config 的稳定 identity。"""

from __future__ import annotations

import design_product_front_door as front_door


def _member(*, host_kind: str, transport_locator: str):
    """构造一个 reviewed Host target；transport 只用于当前连接，不进入稳定配置 hash。"""

    member_type = getattr(front_door, "ConfiguredCrossHostMemberTarget", None)
    assert member_type is not None, "ConfiguredCrossHostMemberTarget 尚未实现"
    if host_kind == "REVIT":
        return member_type(
            host_kind="REVIT",
            role="INITIATOR",
            configured_reference_id="primary-revit",
            configured_reference_hash="1" * 64,
            transport_locator=transport_locator,
            document_id=r"C:\DSP\fixtures\cross-host.rvt",
            native_target_id="revit-wall-001",
        )
    return member_type(
        host_kind="AUTOCAD",
        role="BOUND_REQUIRED",
        configured_reference_id="primary-autocad",
        configured_reference_hash="2" * 64,
        transport_locator=transport_locator,
        document_id=r"C:\DSP\fixtures\cross-host.dwg",
        native_target_id="autocad-wall-001",
    )


def _target(*, revit_locator: str, autocad_locator: str):
    """通过公开 create API 构造 exact 双 Host reviewed target。"""

    target_type = getattr(front_door, "ConfiguredCrossHostWallThicknessTarget", None)
    assert target_type is not None, "ConfiguredCrossHostWallThicknessTarget 尚未实现"
    return target_type.create(
        candidate_key="cross-host-primary",
        project_id="project-001",
        semantic_target_id="WALL-001",
        semantic_environment_id="SEM-ENV-1",
        semantic_environment_hash="3" * 64,
        topology_environment_id="TOPOLOGY-1",
        topology_revision=7,
        topology_snapshot_hash="4" * 64,
        members=(
            _member(host_kind="REVIT", transport_locator=revit_locator),
            _member(host_kind="AUTOCAD", transport_locator=autocad_locator),
        ),
    )


def test_reviewed_configuration_hash_ignores_transient_transport_locators() -> None:
    """Host 重启/pipe 漂移不能要求重写长期 policy/reviewed config identity。"""

    first = _target(
        revit_locator="revit-pipe-runtime-1",
        autocad_locator="autocad-pipe-runtime-1",
    )
    restarted = _target(
        revit_locator="revit-pipe-runtime-2",
        autocad_locator="autocad-pipe-runtime-9",
    )

    assert first.reviewed_configuration_hash == restarted.reviewed_configuration_hash
    assert first.members != restarted.members


def test_reviewed_configuration_hash_changes_for_document_or_native_target() -> None:
    """稳定文档/native target 是 reviewed authority，变化必须改变配置 identity。"""

    target_type = getattr(front_door, "ConfiguredCrossHostWallThicknessTarget")
    original = _target(revit_locator="revit-pipe", autocad_locator="autocad-pipe")
    changed_member = front_door.ConfiguredCrossHostMemberTarget(
        host_kind="AUTOCAD",
        role="BOUND_REQUIRED",
        configured_reference_id="primary-autocad",
        configured_reference_hash="2" * 64,
        transport_locator="autocad-pipe",
        document_id=r"C:\DSP\fixtures\cross-host.dwg",
        native_target_id="autocad-wall-CHANGED",
    )
    changed = target_type.create(
        candidate_key=original.candidate_key,
        project_id=original.project_id,
        semantic_target_id=original.semantic_target_id,
        semantic_environment_id=original.semantic_environment_id,
        semantic_environment_hash=original.semantic_environment_hash,
        topology_environment_id=original.topology_environment_id,
        topology_revision=original.topology_revision,
        topology_snapshot_hash=original.topology_snapshot_hash,
        members=(original.member("REVIT"), changed_member),
    )

    assert changed.reviewed_configuration_hash != original.reviewed_configuration_hash
