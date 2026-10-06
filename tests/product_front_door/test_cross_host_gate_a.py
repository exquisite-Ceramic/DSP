"""Cross-Host Product Vertical Task 5：Gate A 与 REJECT 分支契约。"""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module

import psycopg
import pytest
from design_orchestrator.interaction_artifacts import (
    CrossHostOperationProposalSubjectV2,
    CrossHostProposalObservationV2,
)
from design_orchestrator.workflow_contracts import (
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
)
from design_product_front_door import SessionBindingMemberV2, SessionBindingV2
from design_product_front_door.service import ProductFrontDoorService
from design_product_runtime import (
    ProductFlowStatus,
    ProductFlowView,
    ProductTaskQueryState,
    ProductTaskQueryView,
    ProductTaskRequestV2,
)
from design_product_runtime.accepted_input import AcceptedProductTaskInputV2

_ACCEPTED = "OPERATION_PROPOSAL_ACCEPTED"
_REJECTED = "OPERATION_PROPOSAL_REJECTED"


def _dsn() -> str:
    """只在显式 PostgreSQL lane 执行 Task 5 owner/consume gate acceptance。"""

    import os

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _reset_task5_schemas(dsn: str) -> None:
    """清理 decision owner 与共享 task-row gate，确保用例互不泄漏。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS orchestrator_proposal CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS product_task CASCADE")


def _decision_api():
    """延迟加载 proposal decision owner。"""

    contract = import_module("design_orchestrator.proposal_decision")
    postgres = import_module("design_orchestrator.proposal_decision_postgres")
    return contract, postgres.create_postgres_proposal_decision_store


def _consume_gate(dsn: str):
    """延迟加载独立 resume-consume semantic gate。"""

    module = import_module("design_product_runtime.postgres_start_gate")
    gate_type = getattr(module, "PostgresProductTaskResumeConsumeGate", None)
    assert gate_type is not None, "PostgresProductTaskResumeConsumeGate 尚未实现"
    return gate_type(dsn)


def _binding() -> SessionBindingV2:
    """构造 server accepted input 中冻结的 exact 双 Host binding。"""

    return SessionBindingV2.create(
        session_ref="session-task5-v2",
        project_id="project-task5-v2",
        semantic_target_id="WALL-001",
        semantic_environment_id="SEM-ENV-1",
        semantic_environment_hash="1" * 64,
        topology_environment_id="TOPOLOGY-1",
        topology_revision=7,
        topology_snapshot_hash="2" * 64,
        initiating_host_kind="REVIT",
        members=(
            SessionBindingMemberV2(
                host_kind="AUTOCAD",
                role="BOUND_REQUIRED",
                configured_reference_id="primary-autocad",
                configured_reference_hash="3" * 64,
                transport_locator="autocad-pipe",
                host_instance_id="autocad-runtime-1",
                document_id=r"C:\DSP\fixtures\cross-host.dwg",
                native_target_id="autocad-wall-1",
                host_binding_fingerprint="4" * 64,
            ),
            SessionBindingMemberV2(
                host_kind="REVIT",
                role="INITIATOR",
                configured_reference_id="primary-revit",
                configured_reference_hash="5" * 64,
                transport_locator="revit-pipe",
                host_instance_id="revit-runtime-1",
                document_id=r"C:\DSP\fixtures\cross-host.rvt",
                native_target_id="revit-wall-1",
                host_binding_fingerprint="6" * 64,
            ),
        ),
    )


def _binding_payload(binding: SessionBindingV2) -> dict[str, object]:
    """生成与 Task 3 ProductTask owner 一致的完整 binding JSON body。"""

    return {
        "session_ref": binding.session_ref,
        "project_id": binding.project_id,
        "semantic_target_id": binding.semantic_target_id,
        "semantic_environment_id": binding.semantic_environment_id,
        "semantic_environment_hash": binding.semantic_environment_hash,
        "topology_environment_id": binding.topology_environment_id,
        "topology_revision": binding.topology_revision,
        "topology_snapshot_hash": binding.topology_snapshot_hash,
        "initiating_host_kind": binding.initiating_host_kind,
        "members": [
            {
                "host_kind": member.host_kind,
                "role": member.role,
                "configured_reference_id": member.configured_reference_id,
                "configured_reference_hash": member.configured_reference_hash,
                "transport_locator": member.transport_locator,
                "host_instance_id": member.host_instance_id,
                "document_id": member.document_id,
                "native_target_id": member.native_target_id,
                "host_binding_fingerprint": member.host_binding_fingerprint,
            }
            for member in binding.members
        ],
        "binding_hash": binding.binding_hash,
    }


def _accepted_input() -> AcceptedProductTaskInputV2:
    """构造已完成 server takeover 的 immutable V2 task input。"""

    binding = _binding()
    request = ProductTaskRequestV2.create(
        task_id="task-task5-v2",
        project_id=binding.project_id,
        initiating_host_kind="REVIT",
        session_ref=binding.session_ref,
        session_binding_hash=binding.binding_hash,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )
    return AcceptedProductTaskInputV2(
        request,
        binding.binding_hash,
        _binding_payload(binding),
    )


def _observation(host_kind: str) -> CrossHostProposalObservationV2:
    """返回 proposal 时真实展示给人的稳定 Host 状态。"""

    if host_kind == "AUTOCAD":
        return CrossHostProposalObservationV2(
            host_kind="AUTOCAD",
            host_instance_id="autocad-runtime-1",
            document_id=r"C:\DSP\fixtures\cross-host.dwg",
            native_target_id="autocad-wall-1",
            semantic_target_id="WALL-001",
            host_revision=17,
            normalized_thickness_mm=200.0,
            observed_at="2026-10-06T12:00:00Z",
            command_id="proposal-autocad",
        )
    return CrossHostProposalObservationV2(
        host_kind="REVIT",
        host_instance_id="revit-runtime-1",
        document_id=r"C:\DSP\fixtures\cross-host.rvt",
        native_target_id="revit-wall-1",
        semantic_target_id="WALL-001",
        host_revision=41,
        normalized_thickness_mm=200.0,
        observed_at="2026-10-06T12:00:01Z",
        command_id="proposal-revit",
    )


def _subject() -> tuple[StableRef, CrossHostOperationProposalSubjectV2]:
    """构造与 workflow pause 绑定的 proposal subject ref/body。"""

    from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash

    value = CrossHostOperationProposalSubjectV2(
        request_hash=_accepted_input().request.request_hash,
        session_binding_hash=_binding().binding_hash,
        topology_snapshot_hash=_binding().topology_snapshot_hash,
        semantic_target_id="WALL-001",
        semantic_environment_id="SEM-ENV-1",
        semantic_environment_hash="1" * 64,
        canonical_operation="set_wall_thickness.v1",
        canonical_arguments={
            "thickness": {"value": 300.0, "unit": "mm"},
            "targets": ["WALL-001"],
        },
        observations=(_observation("AUTOCAD"), _observation("REVIT")),
    )
    return (
        StableRef("proposal-subject-task5", workflow_artifact_content_hash(value)),
        value,
    )


def _view(accepted: AcceptedProductTaskInputV2, *, pending: bool = True):
    """构造当前 V2 workflow read model；Task 14 前继续复用现有 query view 外壳。"""

    subject_ref, _ = _subject()
    phase = WorkflowPhase.AWAIT_OPERATION_PROPOSAL if pending else WorkflowPhase.PARAMETER_BINDING
    interaction = None
    if pending:
        interaction = PendingInteractionView(
            pause_id="pause-task5-v2",
            kind=PendingInteractionKind.OPERATION_PROPOSAL,
            subject_ref=subject_ref,
            allowed_resume_kinds=(_ACCEPTED, _REJECTED),
        )
    return ProductTaskQueryView(
        task_id=accepted.request.task_id,
        request_hash=accepted.request.request_hash,
        state=ProductTaskQueryState.WORKFLOW,
        flow=ProductFlowView(
            status=ProductFlowStatus.WAITING,
            checkpoint=WorkflowCheckpointView(
                task_id=accepted.request.task_id,
                phase=phase,
                operation_ref=StableRef("operation-task5", "7" * 64),
                pending_interaction=interaction,
            ),
        ),
    )


class _V2Query:
    """Task 5 service 使用的 durable accepted-input/checkpoint read seam。"""

    def __init__(self, accepted: AcceptedProductTaskInputV2) -> None:
        self.accepted = accepted
        self.current = _view(accepted, pending=True)

    def get_accepted_input_v2(self, task_id: str):
        """只按 exact task 返回 server-owned V2 input。"""

        assert task_id == self.accepted.request.task_id
        return self.accepted

    def get_request(self, task_id: str):
        """V2 path 不得回退到 V1 request reader。"""

        raise AssertionError(f"V2 resume must not use V1 request reader: {task_id}")

    def get(self, task_id: str):
        """返回当前 durable checkpoint projection。"""

        assert task_id == self.accepted.request.task_id
        return self.current


class _SubjectReader:
    """只按 exact StableRef 返回持久 proposal subject。"""

    def __init__(self, ref: StableRef, value: CrossHostOperationProposalSubjectV2) -> None:
        self.ref = ref
        self.value = value

    def get(self, ref: StableRef):
        """拒绝 reverse/latest lookup。"""

        assert ref == self.ref
        return self.value


class _ObservationReader:
    """返回 fresh Host observations；测试可注入 drift/offline。"""

    def __init__(self, values: dict[str, CrossHostProposalObservationV2] | None = None) -> None:
        self.values = values or {
            "AUTOCAD": replace(
                _observation("AUTOCAD"),
                observed_at="2026-10-06T12:05:00Z",
                command_id="gate-a-autocad",
            ),
            "REVIT": replace(
                _observation("REVIT"),
                observed_at="2026-10-06T12:05:01Z",
                command_id="gate-a-revit",
            ),
        }
        self.calls: list[str] = []
        self.failure: Exception | None = None

    def read(self, *, binding: SessionBindingV2, member, command_id: str):
        """按 binding member fresh-read；metadata 可变化但稳定状态必须可比较。"""

        assert member in binding.members
        assert command_id
        self.calls.append(member.host_kind)
        if self.failure is not None:
            raise self.failure
        return self.values[member.host_kind]


class _Flow:
    """记录真实 graph-consumption 调用，并在成功时推进 fake durable checkpoint。"""

    def __init__(self, query: _V2Query) -> None:
        self.query = query
        self.resume_calls = []

    def resume(self, task_id, command):
        """模拟 runtime 成功消费当前 pause。"""

        self.resume_calls.append((task_id, command))
        self.query.current = _view(self.query.accepted, pending=False)
        return object()


class _FlowResolver:
    """按 accepted input 返回本测试已存在的 workflow facade。"""

    def __init__(self, flow: _Flow) -> None:
        self.flow = flow
        self.calls = 0

    def get_flow(self, accepted_input: AcceptedProductTaskInputV2):
        """V2 resume 只解析已存在 task 的 flow，不创建业务 authority。"""

        assert accepted_input.request.task_id == self.flow.query.accepted.request.task_id
        self.calls += 1
        return self.flow


class _Forbidden:
    """REJECT/V2 path 若误触 V1 Host seam 立即失败。"""

    def __getattr__(self, name: str):
        raise AssertionError(f"forbidden V1/Host dependency touched: {name}")

    def __call__(self, *args, **kwargs):
        raise AssertionError(f"forbidden V1/Host dependency called: {args=} {kwargs=}")


def _service(*, observation_reader: _ObservationReader):
    """用真实 PostgreSQL decision owner + consume gate 构造 V2 resume service。"""

    dsn = _dsn()
    contract, decision_factory = _decision_api()
    del contract
    accepted = _accepted_input()
    subject_ref, subject = _subject()
    query = _V2Query(accepted)
    flow = _Flow(query)
    decision_store = decision_factory(dsn)
    consume_gate = _consume_gate(dsn)
    service = ProductFrontDoorService(
        session_binding_reader=_Forbidden(),
        candidate_source=_Forbidden(),
        context_probe=_Forbidden(),
        transport_factory=_Forbidden(),
        query_service=query,
        composition_pool=_Forbidden(),
        reviewed_configuration_validator=None,
        accepted_input_store=None,
        proposal_decision_store=decision_store,
        decision_consume_gate=consume_gate,
        interaction_subject_reader=_SubjectReader(subject_ref, subject),
        cross_host_observation_reader=observation_reader,
        v2_flow_resolver=_FlowResolver(flow),
    )
    return service, query, flow, decision_store, consume_gate


def test_accept_drift_records_gate_a_stale_and_never_consumes_graph() -> None:
    """任一 required Host stable state 漂移都必须先赢 stale transition，再阻止 resume。"""

    dsn = _dsn()
    _reset_task5_schemas(dsn)
    reader = _ObservationReader()
    reader.values["REVIT"] = replace(reader.values["REVIT"], host_revision=42)
    service, _query, flow, decision_store, gate = _service(observation_reader=reader)
    try:
        with pytest.raises(ValueError, match="FRONT_DOOR_PROPOSAL_STALE"):
            service.resume_operation_proposal(
                task_id="task-task5-v2",
                pause_id="pause-task5-v2",
                resume_kind=_ACCEPTED,
            )
        subject_ref, _ = _subject()
        record = decision_store.get(
            "task-task5-v2",
            "pause-task5-v2",
            subject_ref,
        )
        contract, _ = _decision_api()
        assert record is not None
        assert record.human_decision is contract.HumanDecisionState.AWAITING
        assert record.continuation is contract.ProposalContinuationState.STALE_GATE_A
        assert flow.resume_calls == []
    finally:
        decision_store.close()
        gate.close()


def test_reject_records_while_required_hosts_are_offline() -> None:
    """REJECT 不依赖 Host 在线；离线不能把真实 human rejection 替换成 stale。"""

    dsn = _dsn()
    _reset_task5_schemas(dsn)
    reader = _ObservationReader()
    reader.failure = RuntimeError("HOST OFFLINE")
    service, _query, flow, decision_store, gate = _service(observation_reader=reader)
    try:
        service.resume_operation_proposal(
            task_id="task-task5-v2",
            pause_id="pause-task5-v2",
            resume_kind=_REJECTED,
        )
        subject_ref, _ = _subject()
        record = decision_store.get(
            "task-task5-v2",
            "pause-task5-v2",
            subject_ref,
        )
        contract, _ = _decision_api()
        assert reader.calls == []
        assert record is not None
        assert record.human_decision is contract.HumanDecisionState.REJECTED
        assert record.continuation is contract.ProposalContinuationState.CONTINUABLE
        assert len(flow.resume_calls) == 1
    finally:
        decision_store.close()
        gate.close()


def test_reject_records_after_observation_drift_without_gate_a_stale() -> None:
    """即使当前模型已漂移，明确 REJECT 仍只记录拒绝且不 fresh-read。"""

    dsn = _dsn()
    _reset_task5_schemas(dsn)
    reader = _ObservationReader()
    reader.values["AUTOCAD"] = replace(reader.values["AUTOCAD"], host_revision=99)
    service, _query, flow, decision_store, gate = _service(observation_reader=reader)
    try:
        service.resume_operation_proposal(
            task_id="task-task5-v2",
            pause_id="pause-task5-v2",
            resume_kind=_REJECTED,
        )
        subject_ref, _ = _subject()
        record = decision_store.get(
            "task-task5-v2",
            "pause-task5-v2",
            subject_ref,
        )
        contract, _ = _decision_api()
        assert reader.calls == []
        assert record is not None
        assert record.human_decision is contract.HumanDecisionState.REJECTED
        assert record.continuation is contract.ProposalContinuationState.CONTINUABLE
        assert len(flow.resume_calls) == 1
    finally:
        decision_store.close()
        gate.close()
