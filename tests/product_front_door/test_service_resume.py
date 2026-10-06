"""Product Front Door Operation Proposal human-resume authority contract。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from design_changeset import canonical_hash
from design_orchestrator import (
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
    WorkflowResumeCommand,
)
from design_product_front_door.contracts import (
    ConfiguredRevitCandidate,
    SessionBinding,
    configured_revit_candidate_hash_body,
    session_binding_hash_body,
)
from design_product_front_door.service import ProductFrontDoorService
from design_product_runtime import (
    ProductFlowStatus,
    ProductFlowView,
    ProductTaskQueryState,
    ProductTaskQueryView,
    ProductTaskRequest,
)
from revit_sidecar import RevitContextObservation, RevitSelectedElement

_ACCEPTED = "OPERATION_PROPOSAL_ACCEPTED"
_REJECTED = "OPERATION_PROPOSAL_REJECTED"


def _candidate(*, native_target_unique_id: str = "WALL-UNIQUE-001") -> ConfiguredRevitCandidate:
    body = configured_revit_candidate_hash_body(
        candidate_key="revit-main-wall",
        project_id="project-front-door",
        transport_locator=r"\\.\pipe\dsp-revit-front-door",
        document_id=r"C:\Models\FrontDoor.rvt",
        semantic_target_id="wall-semantic-001",
        native_target_unique_id=native_target_unique_id,
    )
    return ConfiguredRevitCandidate(**body, candidate_hash=canonical_hash(body))


def _binding(candidate: ConfiguredRevitCandidate) -> SessionBinding:
    body = session_binding_hash_body(
        session_ref="session-front-door-001",
        project_id=candidate.project_id,
        host_kind="REVIT",
        candidate_key=candidate.candidate_key,
        candidate_hash=candidate.candidate_hash,
        transport_locator=candidate.transport_locator,
        host_instance_id="REVIT-RUNTIME-001",
        document_id=candidate.document_id,
    )
    return SessionBinding(
        **body,
        document_title="FrontDoor.rvt",
        binding_hash=canonical_hash(body),
    )


def _request(binding: SessionBinding) -> ProductTaskRequest:
    return ProductTaskRequest.create(
        task_id="task-resume-001",
        project_id=binding.project_id,
        host_kind=binding.host_kind,
        session_ref=binding.session_ref,
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 350.0, "unit": "mm"}},
    )


def _query_view(
    request: ProductTaskRequest,
    *,
    pause_id: str = "pause-operation-001",
    kind: PendingInteractionKind = PendingInteractionKind.OPERATION_PROPOSAL,
    allowed_resume_kinds: tuple[str, ...] = (_ACCEPTED, _REJECTED),
) -> ProductTaskQueryView:
    checkpoint = WorkflowCheckpointView(
        task_id=request.task_id,
        phase=WorkflowPhase.AWAIT_OPERATION_PROPOSAL,
        pending_interaction=PendingInteractionView(
            pause_id=pause_id,
            kind=kind,
            subject_ref=StableRef(ref_id="operation-proposal-001"),
            allowed_resume_kinds=allowed_resume_kinds,
        ),
    )
    return ProductTaskQueryView(
        task_id=request.task_id,
        request_hash=request.request_hash,
        state=ProductTaskQueryState.WORKFLOW,
        flow=ProductFlowView(status=ProductFlowStatus.WAITING, checkpoint=checkpoint),
    )


def _observation(candidate: ConfiguredRevitCandidate) -> RevitContextObservation:
    return RevitContextObservation(
        document_id=candidate.document_id,
        document_title="FrontDoor.rvt",
        host_instance_id="REVIT-RUNTIME-001",
        revision=42,
        selected_elements=(
            RevitSelectedElement(
                unique_id=candidate.native_target_unique_id,
                native_kind="Wall",
            ),
        ),
    )


@dataclass
class _QueryService:
    request: ProductTaskRequest | None
    views: list[ProductTaskQueryView | None]
    events: list[str]

    def get_request(self, task_id: str) -> ProductTaskRequest | None:
        self.events.append(f"query:get_request:{task_id}")
        return self.request

    def get(self, task_id: str) -> ProductTaskQueryView | None:
        self.events.append(f"query:get:{task_id}")
        if not self.views:
            raise AssertionError("query.get received an unplanned read")
        return self.views.pop(0)


@dataclass
class _SessionReader:
    binding: SessionBinding | None
    events: list[str]

    def resolve_session(self, session_ref: str) -> SessionBinding | None:
        self.events.append(f"session:{session_ref}")
        return self.binding


@dataclass
class _CandidateSource:
    candidate: ConfiguredRevitCandidate | None
    events: list[str]

    def get(self, candidate_key: str) -> ConfiguredRevitCandidate | None:
        self.events.append(f"candidate:{candidate_key}")
        return self.candidate


@dataclass
class _TransportFactory:
    events: list[str]

    def __call__(self, locator: str) -> object:
        self.events.append(f"transport:{locator}")
        return object()


@dataclass
class _Probe:
    observation: RevitContextObservation
    events: list[str]

    def discover(self, *, command_id: str, document_id: str) -> RevitContextObservation:
        self.events.append(f"probe:{command_id}:{document_id}")
        return self.observation


@dataclass
class _ProbeFactory:
    probe: _Probe

    def __call__(self, _transport: object) -> _Probe:
        return self.probe


@dataclass
class _Flow:
    events: list[str]
    resume_calls: list[tuple[str, WorkflowResumeCommand]]

    def resume(self, task_id: str, command: WorkflowResumeCommand) -> object:
        self.events.append(f"flow:resume:{task_id}")
        self.resume_calls.append((task_id, command))
        return object()


@dataclass
class _Composition:
    flow: _Flow


@dataclass
class _Pool:
    composition: _Composition
    events: list[str]
    calls: list[tuple[SessionBinding, ConfiguredRevitCandidate]]

    def get_or_create(
        self,
        *,
        binding: SessionBinding,
        candidate: ConfiguredRevitCandidate,
    ) -> _Composition:
        self.events.append(f"pool:{binding.session_ref}")
        self.calls.append((binding, candidate))
        return self.composition


def _service(
    *,
    request: ProductTaskRequest | None,
    current_view: ProductTaskQueryView | None,
    final_view: ProductTaskQueryView | None = None,
    binding: SessionBinding | None = None,
    candidate: ConfiguredRevitCandidate | None = None,
    observation: RevitContextObservation | None = None,
):
    events: list[str] = []
    query = _QueryService(
        request=request,
        views=[current_view] if final_view is None else [current_view, final_view],
        events=events,
    )
    reader = _SessionReader(binding=binding, events=events)
    candidates = _CandidateSource(candidate=candidate, events=events)
    transport = _TransportFactory(events=events)
    probe = _Probe(
        observation=observation or _observation(candidate or _candidate()),
        events=events,
    )
    flow = _Flow(events=events, resume_calls=[])
    pool = _Pool(composition=_Composition(flow=flow), events=events, calls=[])
    service = ProductFrontDoorService(
        session_binding_reader=reader,
        candidate_source=candidates,
        context_probe=_ProbeFactory(probe=probe),
        transport_factory=transport,
        query_service=query,
        composition_pool=pool,
    )
    return service, events, pool, flow


def test_resume_reads_authoritative_request_and_checkpoint_before_session_or_host() -> None:
    candidate = _candidate()
    binding = _binding(candidate)
    service, events, pool, flow = _service(
        request=None,
        current_view=None,
        binding=binding,
        candidate=candidate,
    )

    with pytest.raises(ValueError, match="FRONT_DOOR_RESUME_TASK_NOT_FOUND"):
        service.resume_operation_proposal(
            task_id="task-resume-001",
            pause_id="pause-operation-001",
            resume_kind=_ACCEPTED,
        )

    assert events == [
        "query:get_request:task-resume-001",
        "query:get:task-resume-001",
    ]
    assert pool.calls == []
    assert flow.resume_calls == []


@pytest.mark.parametrize(
    ("pause_id", "resume_kind", "error_code"),
    [
        ("pause-wrong", _ACCEPTED, "FRONT_DOOR_RESUME_PAUSE_MISMATCH"),
        ("pause-operation-001", "OPERATION_PROPOSAL_OTHER", "FRONT_DOOR_RESUME_KIND_INVALID"),
    ],
)
def test_resume_rejects_pause_or_kind_mismatch_before_session_host_or_pool(
    pause_id: str,
    resume_kind: str,
    error_code: str,
) -> None:
    candidate = _candidate()
    binding = _binding(candidate)
    request = _request(binding)
    current = _query_view(request)
    service, events, pool, flow = _service(
        request=request,
        current_view=current,
        binding=binding,
        candidate=candidate,
    )

    with pytest.raises(ValueError, match=error_code):
        service.resume_operation_proposal(
            task_id=request.task_id,
            pause_id=pause_id,
            resume_kind=resume_kind,
        )

    assert events == [
        f"query:get_request:{request.task_id}",
        f"query:get:{request.task_id}",
    ]
    assert pool.calls == []
    assert flow.resume_calls == []


def test_resume_candidate_drift_after_pause_fails_before_host_pool_or_runtime() -> None:
    frozen_candidate = _candidate()
    current_candidate = _candidate(native_target_unique_id="WALL-UNIQUE-DRIFTED")
    binding = _binding(frozen_candidate)
    request = _request(binding)
    service, events, pool, flow = _service(
        request=request,
        current_view=_query_view(request),
        binding=binding,
        candidate=current_candidate,
    )

    with pytest.raises(ValueError, match="FRONT_DOOR_CANDIDATE_DRIFT"):
        service.resume_operation_proposal(
            task_id=request.task_id,
            pause_id="pause-operation-001",
            resume_kind=_ACCEPTED,
        )

    assert events == [
        f"query:get_request:{request.task_id}",
        f"query:get:{request.task_id}",
        f"session:{binding.session_ref}",
        f"candidate:{binding.candidate_key}",
    ]
    assert pool.calls == []
    assert flow.resume_calls == []


def test_resume_validates_authority_reuses_exact_composition_and_delegates_existing_command(
) -> None:
    candidate = _candidate()
    binding = _binding(candidate)
    request = _request(binding)
    current = _query_view(request)
    final = _query_view(request)
    service, events, pool, flow = _service(
        request=request,
        current_view=current,
        final_view=final,
        binding=binding,
        candidate=candidate,
        observation=_observation(candidate),
    )

    actual = service.resume_operation_proposal(
        task_id=request.task_id,
        pause_id="pause-operation-001",
        resume_kind=_ACCEPTED,
    )

    assert actual == final
    assert pool.calls == [(binding, candidate)]
    assert flow.resume_calls == [
        (
            request.task_id,
            WorkflowResumeCommand(
                resume_kind=_ACCEPTED,
                payload={},
                pause_id="pause-operation-001",
            ),
        )
    ]
    assert events[:4] == [
        f"query:get_request:{request.task_id}",
        f"query:get:{request.task_id}",
        f"session:{binding.session_ref}",
        f"candidate:{binding.candidate_key}",
    ]
    assert any(event.startswith("probe:front-door-resume:") for event in events)
    assert events[-2:] == [
        f"flow:resume:{request.task_id}",
        f"query:get:{request.task_id}",
    ]


# --- Cross-Host Product Vertical Task 5: durable decision consumption ---


def _task5_postgres_dsn() -> str:
    """Task 5 并发消费测试只在真实 PostgreSQL lane 执行。"""

    import os

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _task5_v2_harness(*, flow_failure: str | None = None):
    """复用 Gate-A 测试 helper，并把 flow 注入 crash-window 行为。"""

    from importlib import import_module

    module = import_module("tests.product_front_door.test_cross_host_gate_a")
    dsn = _task5_postgres_dsn()
    module._reset_task5_schemas(dsn)
    reader = module._ObservationReader()
    service, query, flow, decision_store, gate = module._service(
        observation_reader=reader,
    )
    if flow_failure is not None:
        original_resume = flow.resume

        def _failing_resume(task_id, command):
            if flow_failure == "before":
                flow.resume_calls.append((task_id, command))
                raise RuntimeError("SIMULATED_BEFORE_CHECKPOINT")
            if flow_failure == "after":
                original_resume(task_id, command)
                raise RuntimeError("SIMULATED_AFTER_CHECKPOINT")
            raise AssertionError(f"unknown failure mode: {flow_failure}")

        flow.resume = _failing_resume
    return module, service, query, flow, decision_store, gate, reader


def test_two_workers_consume_durable_accept_once_at_graph_boundary() -> None:
    """两个独立 service worker 同时 ACCEPT，实际 flow.resume 只能发生一次。"""

    from concurrent.futures import ThreadPoolExecutor

    module, service_a, query, flow, store_a, gate_a, reader = _task5_v2_harness()
    dsn = _task5_postgres_dsn()
    contract, decision_factory = module._decision_api()
    del contract
    store_b = decision_factory(dsn)
    gate_b = module._consume_gate(dsn)
    subject_ref, subject = module._subject()
    service_b = ProductFrontDoorService(
        session_binding_reader=module._Forbidden(),
        candidate_source=module._Forbidden(),
        context_probe=module._Forbidden(),
        transport_factory=module._Forbidden(),
        query_service=query,
        composition_pool=module._Forbidden(),
        proposal_decision_store=store_b,
        decision_consume_gate=gate_b,
        interaction_subject_reader=module._SubjectReader(subject_ref, subject),
        cross_host_observation_reader=reader,
        v2_flow_resolver=module._FlowResolver(flow),
    )

    def _accept(service):
        return service.resume_operation_proposal(
            task_id="task-task5-v2",
            pause_id="pause-task5-v2",
            resume_kind=_ACCEPTED,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(_accept, service_a)
            second = executor.submit(_accept, service_b)
            first.result(timeout=20)
            second.result(timeout=20)

        assert len(flow.resume_calls) == 1
        # Gate A 只能由实际赢得 decision 的 worker执行一次；每次读取两个 REQUIRED Host。
        assert sorted(reader.calls) == ["AUTOCAD", "REVIT"]
    finally:
        store_a.close()
        store_b.close()
        gate_a.close()
        gate_b.close()


def test_consumer_exit_before_graph_invoke_allows_waiter_to_consume() -> None:
    """decision 已提交但 graph 未推进时，下一 worker 可消费且无需再次 Gate A。"""

    module, service_a, query, flow, store_a, gate_a, reader = _task5_v2_harness(
        flow_failure="before"
    )
    dsn = _task5_postgres_dsn()

    try:
        with pytest.raises(RuntimeError, match="SIMULATED_BEFORE_CHECKPOINT"):
            service_a.resume_operation_proposal(
                task_id="task-task5-v2",
                pause_id="pause-task5-v2",
                resume_kind=_ACCEPTED,
            )

        # 模拟新进程：恢复真实 flow 行为，但继续读取同一 durable decision/query。
        flow.resume = module._Flow.resume.__get__(flow, module._Flow)
        _, decision_factory = module._decision_api()
        store_b = decision_factory(dsn)
        gate_b = module._consume_gate(dsn)
        subject_ref, subject = module._subject()
        service_b = ProductFrontDoorService(
            session_binding_reader=module._Forbidden(),
            candidate_source=module._Forbidden(),
            context_probe=module._Forbidden(),
            transport_factory=module._Forbidden(),
            query_service=query,
            composition_pool=module._Forbidden(),
            proposal_decision_store=store_b,
            decision_consume_gate=gate_b,
            interaction_subject_reader=module._SubjectReader(subject_ref, subject),
            cross_host_observation_reader=reader,
            v2_flow_resolver=module._FlowResolver(flow),
        )
        try:
            service_b.resume_operation_proposal(
                task_id="task-task5-v2",
                pause_id="pause-task5-v2",
                resume_kind=_ACCEPTED,
            )
        finally:
            store_b.close()
            gate_b.close()

        # 首次调用进入 graph 前故障，第二次才成功；Gate A 仍只执行一次。
        assert len(flow.resume_calls) == 2
        assert sorted(reader.calls) == ["AUTOCAD", "REVIT"]
        assert query.current.flow.checkpoint.pending_interaction is None
    finally:
        store_a.close()
        gate_a.close()


def test_consumer_exit_after_checkpoint_advance_does_not_consume_again() -> None:
    """graph 已推进但 response 丢失时，下一 worker只读新 checkpoint，不能第二次 resume。"""

    module, service_a, query, flow, store_a, gate_a, reader = _task5_v2_harness(
        flow_failure="after"
    )
    dsn = _task5_postgres_dsn()

    try:
        with pytest.raises(RuntimeError, match="SIMULATED_AFTER_CHECKPOINT"):
            service_a.resume_operation_proposal(
                task_id="task-task5-v2",
                pause_id="pause-task5-v2",
                resume_kind=_ACCEPTED,
            )

        flow.resume = module._Flow.resume.__get__(flow, module._Flow)
        _, decision_factory = module._decision_api()
        store_b = decision_factory(dsn)
        gate_b = module._consume_gate(dsn)
        subject_ref, subject = module._subject()
        service_b = ProductFrontDoorService(
            session_binding_reader=module._Forbidden(),
            candidate_source=module._Forbidden(),
            context_probe=module._Forbidden(),
            transport_factory=module._Forbidden(),
            query_service=query,
            composition_pool=module._Forbidden(),
            proposal_decision_store=store_b,
            decision_consume_gate=gate_b,
            interaction_subject_reader=module._SubjectReader(subject_ref, subject),
            cross_host_observation_reader=reader,
            v2_flow_resolver=module._FlowResolver(flow),
        )
        try:
            service_b.resume_operation_proposal(
                task_id="task-task5-v2",
                pause_id="pause-task5-v2",
                resume_kind=_ACCEPTED,
            )
        finally:
            store_b.close()
            gate_b.close()

        assert len(flow.resume_calls) == 1
        assert sorted(reader.calls) == ["AUTOCAD", "REVIT"]
        assert query.current.flow.checkpoint.pending_interaction is None
    finally:
        store_a.close()
        gate_a.close()
