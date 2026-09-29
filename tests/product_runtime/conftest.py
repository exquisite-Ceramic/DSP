from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg
import pytest
from design_product_front_door import (
    ConfiguredPolicyApprovalAdmissionPort,
    ConfiguredProductApprovalPolicy,
    PostgresConfiguredPolicyAdmissionStore,
)
from design_product_runtime import (
    ProductTaskRequest,
    RevitWallThicknessCompositionConfig,
    build_revit_wall_thickness_reference_composition,
)

_DOCUMENT_REF = "DOC-TASK9"
_HOST_INSTANCE_ID = "REVIT-TASK9"
_SESSION_REF = "revit-session-product-e2e"
_PROJECT_ID = "project-task9"
_SEMANTIC_WALL_ID = "WALL-001"
_WALL_UNIQUE_ID = "REVIT-UNIQUE-ID-TASK9"
_WALL_TYPE_UNIQUE_ID = "REVIT-WALLTYPE-TASK9"
_INITIAL_REVISION = 42
_INITIAL_THICKNESS_MM = 275.0


@pytest.fixture
def product_task_postgres_dsn() -> str:
    """只在显式 PostgreSQL 17 lane 中运行真实 ProductTask / workflow / Saga acceptance。"""

    import os

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


class StatefulRevitTransport:
    """只模拟外部 Revit Host transport；平台 owners 与 sidecar adapters 全部来自 production factory。"""

    def __init__(self) -> None:
        self.current_revision = _INITIAL_REVISION
        self.current_thickness_mm = _INITIAL_THICKNESS_MM
        self.commands: list[object] = []
        self.command_revisions: list[int] = []
        self.execute_count = 0

    def request(self, command):
        """按真实 HostCommand operation 返回严格 Host evidence，并记录调用时 revision。"""

        self.commands.append(command)
        self.command_revisions.append(self.current_revision)
        operation = command.operation
        if operation == "context.current_selection":
            return {
                "status": "OK",
                "revision_after": self.current_revision,
                "payload": {
                    "document_id": _DOCUMENT_REF,
                    "document_title": "Product E2E Fixture",
                    "host_instance_id": _HOST_INSTANCE_ID,
                    "selected_elements": [
                        {"unique_id": _WALL_UNIQUE_ID, "native_kind": "Wall"}
                    ],
                },
            }
        if operation == "read_wall_thickness_snapshot":
            return {
                "status": "OK",
                "revision_after": self.current_revision,
                "payload": {
                    "document_id": command.document_id,
                    "host_instance_id": _HOST_INSTANCE_ID,
                    "wall_unique_id": command.target_native_refs[0].native_id,
                    "wall_type_unique_id": _WALL_TYPE_UNIQUE_ID,
                    "native_kind": "Wall",
                    "builtin_category": "OST_Walls",
                    "wall_thickness_mm": self.current_thickness_mm,
                    "location_signature": "Line|0|0|0|10|0|0",
                    "relationship_signature": "isolated",
                    "revision_before": self.current_revision,
                    "revision_after": self.current_revision,
                },
            }
        if operation == "check_wall_thickness_readiness":
            return {
                "status": "OK",
                "revision_after": self.current_revision,
                "payload": {
                    "document_id": _DOCUMENT_REF,
                    "wall_unique_id": _WALL_UNIQUE_ID,
                    "current_width": {
                        "value": self.current_thickness_mm,
                        "unit": "mm",
                    },
                    "isolation_ready": True,
                    "plan_ready": True,
                },
            }
        if operation == "set_wall_thickness":
            return self._execute_wall_thickness(command)
        raise AssertionError(f"unexpected Revit Host operation: {operation}")

    def _execute_wall_thickness(self, command):
        """执行唯一允许的 mutation；exact revision 不匹配时明确 BEFORE_COMMIT。"""

        self.execute_count += 1
        expected_revision = command.preconditions[0]["revision"]
        if expected_revision != self.current_revision:
            return {
                "command_id": command.command_id,
                "status": "ERROR",
                "revision_after": self.current_revision,
                "error": {
                    "code": "REVIT_REVISION_CONFLICT",
                    "commit_state": "BEFORE_COMMIT",
                },
            }
        requested_mm = float(command.arguments["thickness"]["value"])
        revision_before = self.current_revision
        revision_after = revision_before + 1
        self.current_thickness_mm = requested_mm
        self.current_revision = revision_after
        return {
            "command_id": command.command_id,
            "status": "OK",
            "revision_after": revision_after,
            "payload": {
                "wall_unique_id": _WALL_UNIQUE_ID,
                "wall_type_unique_id": _WALL_TYPE_UNIQUE_ID,
                "editable_layer_index": 1,
                "width_before_internal": 0.5,
                "width_after_internal": requested_mm / 304.8,
                "width_after_mm": requested_mm,
                "requested_width_mm": requested_mm,
                "transaction_attempt_count": 1,
            },
            "verification": {
                "identity_invariant_proven": True,
                "location_invariant_proven": True,
                "relationship_invariant_proven": True,
                "document_change_observed": True,
                "revision_before": revision_before,
                "revision_after": revision_after,
                "location_signature_before": "Line|0|0|0|10|0|0",
                "location_signature_after": "Line|0|0|0|10|0|0",
                "relationship_signature_before": "isolated",
                "relationship_signature_after": "isolated",
            },
            "replayed": False,
        }

    def command_operations(self) -> tuple[str, ...]:
        """按实际 I/O 顺序暴露 operation，测试据此断言调用次数与先后。"""

        return tuple(command.operation for command in self.commands)


class _StaticPolicySource:
    """mandatory offline/live acceptance 使用固定 configured policy，不绕过真实 policy owner。"""

    def __init__(self, policy: ConfiguredProductApprovalPolicy) -> None:
        self._policy = policy

    def load(self) -> ConfiguredProductApprovalPolicy:
        return self._policy


class _AcceptancePolicyClock:
    """固定 issuance 时间，避免测试运行日期改变授权生命周期语义。"""

    def now(self) -> datetime:
        return datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)


class _ConfiguredPolicyAdmissionFactory:
    """从 public composition 提供的 exact owner stores 构造真实 configured-policy admission。"""

    def __init__(self, dsn: str, *, admission_prefix: str) -> None:
        self._dsn = dsn
        self._admission_prefix = admission_prefix
        self._stores: list[PostgresConfiguredPolicyAdmissionStore] = []
        self._next_sequence = 0

    def build(self, *, changeset_store, approval_scope_store):
        """只使用 factory 提供的 authoritative stores；不创建第二份 ChangeSet/scope graph。"""

        admission_store = PostgresConfiguredPolicyAdmissionStore(self._dsn)
        self._stores.append(admission_store)
        policy = ConfiguredProductApprovalPolicy.from_mapping(
            {
                "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
                "policy_id": "product-reference-acceptance",
                "principal": "user:product-reference-acceptance",
                "project_ids": [_PROJECT_ID],
                "allowed_canonical_operations": ["set_wall_thickness.v1"],
                "admission_ttl_seconds": 31_536_000,
            }
        )

        def next_admission_id() -> str:
            self._next_sequence += 1
            return f"{self._admission_prefix}-{self._next_sequence}"

        return ConfiguredPolicyApprovalAdmissionPort(
            changeset_store=changeset_store,
            approval_scope_store=approval_scope_store,
            admission_store=admission_store,
            policy_source=_StaticPolicySource(policy),
            clock=_AcceptancePolicyClock(),
            id_factory=next_admission_id,
        )

    def close(self) -> None:
        """关闭本 test factory 创建的 durable admission stores。"""

        for store in reversed(self._stores):
            store.close()


def _reset_product_acceptance_schemas(dsn: str) -> None:
    """每个 acceptance case 从 fresh ProductTask/Orchestrator/Saga/Policy owner schemas 开始。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        for schema in (
            "product_task",
            "orchestrator_checkpoint",
            "orchestrator_artifact",
            "execution_saga",
            "product_policy",
        ):
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def _request(task_id: str, *, thickness_mm: float = 300.0) -> ProductTaskRequest:
    """构造只携带用户 INTENT 的 immutable ProductTask request。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id=_PROJECT_ID,
        host_kind="REVIT",
        session_ref=_SESSION_REF,
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": thickness_mm, "unit": "mm"}},
    )


def _reference_config(
    dsn: str,
    *,
    document_id: str = _DOCUMENT_REF,
    host_instance_id: str = _HOST_INSTANCE_ID,
    native_target_unique_id: str = _WALL_UNIQUE_ID,
) -> RevitWallThicknessCompositionConfig:
    """构造 mandatory acceptance 的 exact-session public composition config。"""

    return RevitWallThicknessCompositionConfig(
        dsn=dsn,
        session_ref=_SESSION_REF,
        document_id=document_id,
        host_instance_id=host_instance_id,
        semantic_target_id=_SEMANTIC_WALL_ID,
        native_target_unique_id=native_target_unique_id,
    )


def _build_reference_case(
    dsn: str,
    task_id: str,
    *,
    reset_schema: bool,
    host: object | None = None,
    config: RevitWallThicknessCompositionConfig | None = None,
    request: ProductTaskRequest | None = None,
):
    """只经 public reference factory 组合 mandatory product acceptance case。"""

    if reset_schema:
        _reset_product_acceptance_schemas(dsn)
    host = host or StatefulRevitTransport()
    config = config or _reference_config(dsn)
    request = request or _request(task_id)
    approval_factory = _ConfiguredPolicyAdmissionFactory(
        dsn,
        admission_prefix=f"ADM-{task_id}",
    )
    composition = build_revit_wall_thickness_reference_composition(
        config=config,
        transport=host,
        approval_admission_factory=approval_factory,
    )
    owner_ports = composition.runtime._services._external_owners
    return SimpleNamespace(
        task_id=task_id,
        request=request,
        composition=composition,
        flow=composition.flow,
        runtime=composition.runtime,
        host=host,
        request_store=composition.request_store,
        start_gate=composition.start_gate,
        snapshot_registry=composition.snapshot_registry,
        saga_store=composition.saga_store,
        artifact_store=owner_ports._workflow_artifact_store,
        changeset_store=owner_ports._changeset_store,
        gateway_store=owner_ports._gateway_authorization_store,
        execution_store=owner_ports._execution_plan_store,
        dispatch_store=owner_ports._dispatch_intent_store,
        approval_factory=approval_factory,
    )


def _close_case(case) -> None:
    """按 composition/factory ownership 显式关闭 mandatory acceptance resources。"""

    try:
        case.composition.close()
    finally:
        case.approval_factory.close()


@pytest.fixture
def revit_wall_thickness_product_case(product_task_postgres_dsn: str):
    """返回 fresh public-reference composition factory；pause/resume 必须保持同一实例。"""

    cases = []

    def build(task_id: str):
        case = _build_reference_case(
            product_task_postgres_dsn,
            task_id,
            reset_schema=True,
        )
        cases.append(case)
        return case

    yield build

    for case in reversed(cases):
        _close_case(case)
