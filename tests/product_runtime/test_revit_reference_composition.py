from __future__ import annotations

from dataclasses import fields
from datetime import datetime, UTC

import design_product_runtime.revit_reference_composition as composition_module
import pytest
from design_approval_scope import InMemoryApprovalScopeStore
from design_changeset import InMemoryChangeSetStore
from design_orchestrator import WorkflowPhase, WorkflowResumeCommand
from design_orchestrator.workflow_services import WorkflowStateError
from design_product_front_door import (
    ConfiguredPolicyApprovalAdmissionPort,
    ConfiguredProductApprovalPolicy,
    PostgresConfiguredPolicyAdmissionStore,
)
from design_product_runtime import (
    ProductFlowStatus,
    ProductTaskRequest,
    RevitWallThicknessCompositionConfig,
    build_revit_wall_thickness_reference_composition,
)

from tests.product_runtime.conftest import StatefulRevitTransport


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

    def build(self, *, changeset_store, approval_scope_store):
        """只接受冻结 Protocol 的 keyword-only shared-store seam。"""

        self.calls.append((changeset_store, approval_scope_store))
        return _RejectingAdmissionPort()


class _StaticPolicySource:
    """reference acceptance 使用冻结 policy，不从环境隐式发现授权。"""

    def __init__(self, policy: ConfiguredProductApprovalPolicy) -> None:
        self._policy = policy

    def load(self) -> ConfiguredProductApprovalPolicy:
        return self._policy


class _PolicyClock:
    """为 configured-policy issuance 提供 timezone-aware UTC 时间。"""

    def now(self) -> datetime:
        return datetime.now(UTC)


class _ConfiguredPolicyAdmissionFactory:
    """只在 supplied authoritative stores 上构造真实 configured-policy admission port。"""

    def __init__(self, dsn: str, *, parallel_store_graph: bool = False) -> None:
        self._dsn = dsn
        self._parallel_store_graph = parallel_store_graph
        self._stores: list[PostgresConfiguredPolicyAdmissionStore] = []

    def build(self, *, changeset_store, approval_scope_store):
        """正常路径复用 supplied stores；负例显式制造错误平行 store graph。"""

        if self._parallel_store_graph:
            changeset_store = InMemoryChangeSetStore()
            approval_scope_store = InMemoryApprovalScopeStore()
        admission_store = PostgresConfiguredPolicyAdmissionStore(self._dsn)
        self._stores.append(admission_store)
        policy = ConfiguredProductApprovalPolicy.from_mapping(
            {
                "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
                "policy_id": "task6-reference-policy",
                "principal": "user:task6-reference",
                "project_ids": ["project-task9"],
                "allowed_canonical_operations": ["set_wall_thickness.v1"],
                "admission_ttl_seconds": 3600,
            }
        )
        return ConfiguredPolicyApprovalAdmissionPort(
            changeset_store=changeset_store,
            approval_scope_store=approval_scope_store,
            admission_store=admission_store,
            policy_source=_StaticPolicySource(policy),
            clock=_PolicyClock(),
            id_factory=lambda: "ADM-TASK6-REFERENCE",
        )

    def close(self) -> None:
        """关闭 test factory 创建的 durable admission stores。"""

        for store in reversed(self._stores):
            store.close()


def _config() -> RevitWallThicknessCompositionConfig:
    return RevitWallThicknessCompositionConfig(
        dsn="postgresql://unused-by-shape-test",
        session_ref="session-task6-reference",
        document_id="C:/fixtures/task6-reference.rvt",
        host_instance_id="REVIT-TASK6-REFERENCE",
        semantic_target_id="WALL-001",
        native_target_unique_id="REVIT-UNIQUE-ID-TASK6",
    )


def _real_config(dsn: str) -> RevitWallThicknessCompositionConfig:
    """与 StatefulRevitTransport 暴露的 exact runtime/document/target identity 对齐。"""

    return RevitWallThicknessCompositionConfig(
        dsn=dsn,
        session_ref="revit-session-product-e2e",
        document_id="DOC-TASK9",
        host_instance_id="REVIT-TASK9",
        semantic_target_id="WALL-001",
        native_target_unique_id="REVIT-UNIQUE-ID-TASK9",
    )


def _request(task_id: str) -> ProductTaskRequest:
    """构造 reference composition 的 exact immutable wall-thickness request。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id="project-task9",
        host_kind="REVIT",
        session_ref="revit-session-product-e2e",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


def _accept(proposal) -> WorkflowResumeCommand:
    """只接受 owner 暴露的 exact operation-proposal pause。"""

    pending = proposal.checkpoint.pending_interaction
    assert pending is not None
    return WorkflowResumeCommand(
        resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        pause_id=pending.pause_id,
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


def test_real_configured_policy_authorizes_exact_workflow_lineage_on_same_composition(
    product_task_postgres_dsn: str,
) -> None:
    """真实 policy port 必须消费本 workflow 的 final ChangeSet/scope 并在同 composition 完成。"""

    host = StatefulRevitTransport()
    approval_factory = _ConfiguredPolicyAdmissionFactory(product_task_postgres_dsn)
    composition = build_revit_wall_thickness_reference_composition(
        config=_real_config(product_task_postgres_dsn),
        transport=host,
        approval_admission_factory=approval_factory,
    )
    try:
        proposal = composition.flow.submit(_request("task6-reference-policy-happy"))
        assert proposal.status is ProductFlowStatus.WAITING
        assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert host.execute_count == 0

        completed = composition.flow.resume(
            proposal.task_id,
            _accept(proposal),
        )

        assert completed.status is ProductFlowStatus.SUCCEEDED
        assert completed.workflow_phase is WorkflowPhase.COMPLETED
        assert host.execute_count == 1
        assert host.current_thickness_mm == 300.0
    finally:
        composition.close()
        approval_factory.close()


def test_parallel_policy_store_graph_fails_closed_before_host_mutation(
    product_task_postgres_dsn: str,
) -> None:
    """configured-policy 若接到平行空 owner graph，必须在 Gateway/Host mutation 前失败。"""

    host = StatefulRevitTransport()
    approval_factory = _ConfiguredPolicyAdmissionFactory(
        product_task_postgres_dsn,
        parallel_store_graph=True,
    )
    composition = build_revit_wall_thickness_reference_composition(
        config=_real_config(product_task_postgres_dsn),
        transport=host,
        approval_admission_factory=approval_factory,
    )
    try:
        proposal = composition.flow.submit(_request("task6-reference-policy-wrong-store"))
        assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL

        with pytest.raises(WorkflowStateError):
            composition.flow.resume(
                proposal.task_id,
                _accept(proposal),
            )

        assert host.execute_count == 0
        assert "set_wall_thickness" not in host.command_operations()
    finally:
        composition.close()
        approval_factory.close()
