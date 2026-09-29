from __future__ import annotations

from dataclasses import fields

import design_product_runtime.revit_reference_composition as composition_module
from design_product_runtime import (
    RevitWallThicknessCompositionConfig,
    build_revit_wall_thickness_reference_composition,
)


class _NoIoRevitTransport:
    """只满足 reference composition 的 Host transport seam；构建阶段不得触发 Host I/O。"""

    def request(self, command):
        raise AssertionError(f"composition build must not perform Host I/O: {command!r}")


class _RejectingAdmissionPort:
    """只用于证明 composition 接受 factory 产物；本 RED 不执行 approval。"""

    def request_approval(self, changeset_ref):
        raise AssertionError(f"approval must not run during composition build: {changeset_ref!r}")


class _RecordingApprovalAdmissionFactory:
    """记录 build 接收到的 authoritative stores，验证与 workflow owner 精确同实例。"""

    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def build(self, changeset_store, approval_scope_store):
        self.calls.append((changeset_store, approval_scope_store))
        return _RejectingAdmissionPort()


def _config() -> RevitWallThicknessCompositionConfig:
    return RevitWallThicknessCompositionConfig(
        dsn="postgresql://unused-by-shape-test",
        session_ref="session-task6-reference",
        document_id="C:/fixtures/task6-reference.rvt",
        host_instance_id="REVIT-TASK6-REFERENCE",
        semantic_target_id="WALL-001",
        native_target_unique_id="REVIT-UNIQUE-ID-TASK6",
    )


def test_reference_composition_config_field_set_is_frozen() -> None:
    """Task 6 public config 只携带 exact-session composition 输入，不混入 policy/owner truth。"""

    assert tuple(field.name for field in fields(RevitWallThicknessCompositionConfig)) == (
        "dsn",
        "session_ref",
        "document_id",
        "host_instance_id",
        "semantic_target_id",
        "native_target_unique_id",
    )


def test_reference_composition_passes_exact_same_changeset_and_scope_stores_to_policy_factory(
    product_task_postgres_dsn: str,
    monkeypatch,
) -> None:
    """workflow 与 configured-policy factory 必须共享同一组 authoritative owner stores。"""

    owner_seen: dict[str, object] = {}
    real_owner_ports = composition_module.CanonicalWorkflowOwnerPorts

    def recording_owner_ports(**kwargs):
        owner_seen["changeset_store"] = kwargs["changeset_store"]
        owner_seen["approval_scope_store"] = kwargs["approval_scope_store"]
        return real_owner_ports(**kwargs)

    monkeypatch.setattr(
        composition_module,
        "CanonicalWorkflowOwnerPorts",
        recording_owner_ports,
    )
    approval_factory = _RecordingApprovalAdmissionFactory()
    config = _config()
    config = RevitWallThicknessCompositionConfig(
        dsn=product_task_postgres_dsn,
        session_ref=config.session_ref,
        document_id=config.document_id,
        host_instance_id=config.host_instance_id,
        semantic_target_id=config.semantic_target_id,
        native_target_unique_id=config.native_target_unique_id,
    )

    composition = build_revit_wall_thickness_reference_composition(
        config=config,
        transport=_NoIoRevitTransport(),
        approval_admission_factory=approval_factory,
    )
    try:
        assert len(approval_factory.calls) == 1
        policy_changeset_store, policy_scope_store = approval_factory.calls[0]
        assert policy_changeset_store is owner_seen["changeset_store"]
        assert policy_scope_store is owner_seen["approval_scope_store"]
        assert composition.flow is not None
        assert composition.runtime is not None
        assert composition.snapshot_registry is not None
    finally:
        composition.close()
