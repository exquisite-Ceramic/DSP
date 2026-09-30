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


def test_resume_validates_authority_reuses_exact_composition_and_delegates_existing_command() -> None:
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
