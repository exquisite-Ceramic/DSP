"""Product Front Door thin service 的 query 与 submit authority contract。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from design_changeset import canonical_hash
from design_product_front_door.contracts import (
    ConfiguredRevitCandidate,
    SessionBinding,
    configured_revit_candidate_hash_body,
    session_binding_hash_body,
)
from design_product_front_door.service import ProductFrontDoorService
from design_product_runtime import (
    ProductTaskQueryState,
    ProductTaskQueryView,
    ProductTaskRequest,
)
from revit_sidecar import RevitContextObservation, RevitSelectedElement


@dataclass
class _QueryService:
    """记录 exact get；测试可注入 owner query 的最终投影。"""

    result: ProductTaskQueryView | None
    calls: list[str]

    def get(self, task_id: str) -> ProductTaskQueryView | None:
        self.calls.append(task_id)
        return self.result


class _ExplodingDependency:
    """任何方法/属性访问都代表 host-independent get 错误触碰了外部 seam。"""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"host-independent get touched forbidden dependency: {name}")


@dataclass
class _SessionReader:
    binding: SessionBinding | None
    calls: list[str]

    def resolve_session(self, session_ref: str) -> SessionBinding | None:
        self.calls.append(session_ref)
        return self.binding


@dataclass
class _CandidateSource:
    candidate: ConfiguredRevitCandidate | None
    calls: list[str]

    def get(self, candidate_key: str) -> ConfiguredRevitCandidate | None:
        self.calls.append(candidate_key)
        return self.candidate


@dataclass
class _TransportFactory:
    calls: list[str]

    def __call__(self, locator: str) -> object:
        self.calls.append(locator)
        return object()


@dataclass
class _Probe:
    observation: RevitContextObservation
    calls: list[tuple[str, str]]

    def discover(self, *, command_id: str, document_id: str) -> RevitContextObservation:
        self.calls.append((command_id, document_id))
        return self.observation


@dataclass
class _ProbeFactory:
    probe: _Probe
    calls: list[object]

    def __call__(self, transport: object) -> _Probe:
        self.calls.append(transport)
        return self.probe


@dataclass
class _Flow:
    submit_calls: list[ProductTaskRequest]

    def submit(self, request: ProductTaskRequest) -> object:
        self.submit_calls.append(request)
        return object()


@dataclass
class _Composition:
    flow: _Flow


@dataclass
class _CompositionPool:
    composition: _Composition
    calls: list[tuple[SessionBinding, ConfiguredRevitCandidate]]

    def get_or_create(
        self,
        *,
        binding: SessionBinding,
        candidate: ConfiguredRevitCandidate,
    ) -> _Composition:
        self.calls.append((binding, candidate))
        return self.composition


def _candidate(*, native_target_unique_id: str = "WALL-UNIQUE-001") -> ConfiguredRevitCandidate:
    body = configured_revit_candidate_hash_body(
        candidate_key="revit-main-wall",
        project_id="project-front-door",
        transport_locator=r"\\.\pipe\dsp-revit-front-door",
        document_id=r"C:\Models\FrontDoor.rvt",
        semantic_target_id="wall-semantic-001",
        native_target_unique_id=native_target_unique_id,
    )
    return ConfiguredRevitCandidate(
        **body,
        candidate_hash=canonical_hash(body),
    )


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


def _request(binding: SessionBinding, *, project_id: str | None = None) -> ProductTaskRequest:
    return ProductTaskRequest.create(
        task_id="task-submit-001",
        project_id=project_id or binding.project_id,
        host_kind="REVIT",
        session_ref=binding.session_ref,
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 350.0, "unit": "mm"}},
    )


def _observation(
    candidate: ConfiguredRevitCandidate,
    *,
    host_instance_id: str = "REVIT-RUNTIME-001",
    document_id: str | None = None,
    selected_unique_id: str | None = None,
) -> RevitContextObservation:
    return RevitContextObservation(
        document_id=document_id or candidate.document_id,
        document_title="FrontDoor.rvt",
        host_instance_id=host_instance_id,
        revision=42,
        selected_elements=(
            RevitSelectedElement(
                unique_id=selected_unique_id or candidate.native_target_unique_id,
                native_kind="Wall",
            ),
        ),
    )


def _service(query_service: _QueryService) -> ProductFrontDoorService:
    """构造所有非 query 依赖都不可访问的 service。"""

    exploding = _ExplodingDependency()
    return ProductFrontDoorService(
        session_binding_reader=exploding,
        candidate_source=exploding,
        context_probe=exploding,
        transport_factory=exploding,
        query_service=query_service,
        composition_pool=exploding,
    )


def _submit_service(
    *,
    binding: SessionBinding | None,
    candidate: ConfiguredRevitCandidate | None,
    observation: RevitContextObservation,
    query_result: ProductTaskQueryView | None = None,
):
    reader = _SessionReader(binding=binding, calls=[])
    candidates = _CandidateSource(candidate=candidate, calls=[])
    transport_factory = _TransportFactory(calls=[])
    probe = _Probe(observation=observation, calls=[])
    probe_factory = _ProbeFactory(probe=probe, calls=[])
    flow = _Flow(submit_calls=[])
    pool = _CompositionPool(composition=_Composition(flow=flow), calls=[])
    query = _QueryService(result=query_result, calls=[])
    service = ProductFrontDoorService(
        session_binding_reader=reader,
        candidate_source=candidates,
        context_probe=probe_factory,
        transport_factory=transport_factory,
        query_service=query,
        composition_pool=pool,
    )
    return service, reader, candidates, transport_factory, probe, pool, flow, query


def test_get_delegates_exact_task_id_without_session_or_host_access() -> None:
    """已存在任务的 exact get 只读 durable ProductTask query owner。"""

    expected = ProductTaskQueryView(
        task_id="task-query-001",
        request_hash="a" * 64,
        state=ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW,
        flow=None,
    )
    query = _QueryService(result=expected, calls=[])

    actual = _service(query).get("task-query-001")

    assert actual == expected
    assert query.calls == ["task-query-001"]


def test_get_unknown_task_remains_host_independent() -> None:
    """未知 task 也不得为了猜测 session/Host 状态而打开 transport 或 composition。"""

    query = _QueryService(result=None, calls=[])

    actual = _service(query).get("task-missing")

    assert actual is None
    assert query.calls == ["task-missing"]


def test_submit_unknown_session_fails_before_candidate_host_or_pool() -> None:
    """server 只能接受已冻结的 exact session；未知 session 不得继续推断。"""

    candidate = _candidate()
    service, reader, candidates, transport, _probe, pool, flow, _query = _submit_service(
        binding=None,
        candidate=candidate,
        observation=_observation(candidate),
    )
    request = ProductTaskRequest.create(
        task_id="task-submit-001",
        project_id=candidate.project_id,
        host_kind="REVIT",
        session_ref="session-missing",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 350.0, "unit": "mm"}},
    )

    with pytest.raises(ValueError, match="FRONT_DOOR_SESSION_NOT_FOUND"):
        service.submit(request)

    assert reader.calls == ["session-missing"]
    assert candidates.calls == []
    assert transport.calls == []
    assert pool.calls == []
    assert flow.submit_calls == []


def test_submit_request_binding_project_mismatch_fails_before_candidate_host_or_pool() -> None:
    """request project/host authority 必须与 immutable SessionBinding 一致。"""

    candidate = _candidate()
    binding = _binding(candidate)
    service, _reader, candidates, transport, _probe, pool, flow, _query = _submit_service(
        binding=binding,
        candidate=candidate,
        observation=_observation(candidate),
    )

    with pytest.raises(ValueError, match="FRONT_DOOR_REQUEST_BINDING_MISMATCH"):
        service.submit(_request(binding, project_id="project-other"))

    assert candidates.calls == []
    assert transport.calls == []
    assert pool.calls == []
    assert flow.submit_calls == []


def test_submit_revalidates_binding_hash_before_current_candidate_or_host() -> None:
    """自定义/损坏 read port 返回的 binding 也必须在 service 边界重新验证 canonical hash。"""

    candidate = _candidate()
    binding = _binding(candidate)
    object.__setattr__(binding, "binding_hash", "f" * 64)
    service, _reader, candidates, transport, _probe, pool, flow, _query = _submit_service(
        binding=binding,
        candidate=candidate,
        observation=_observation(candidate),
    )

    with pytest.raises(ValueError, match="FRONT_DOOR_BINDING_HASH_INVALID"):
        service.submit(_request(binding))

    assert candidates.calls == []
    assert transport.calls == []
    assert pool.calls == []
    assert flow.submit_calls == []


def test_submit_candidate_drift_fails_before_host_or_pool() -> None:
    """同一 candidate_key 被编辑后，current canonical hash 必须与 frozen binding hash 精确一致。"""

    frozen_candidate = _candidate()
    current_candidate = _candidate(native_target_unique_id="WALL-UNIQUE-DRIFTED")
    binding = _binding(frozen_candidate)
    service, _reader, candidates, transport, _probe, pool, flow, _query = _submit_service(
        binding=binding,
        candidate=current_candidate,
        observation=_observation(current_candidate),
    )

    with pytest.raises(ValueError, match="FRONT_DOOR_CANDIDATE_DRIFT"):
        service.submit(_request(binding))

    assert candidates.calls == [binding.candidate_key]
    assert transport.calls == []
    assert pool.calls == []
    assert flow.submit_calls == []


@pytest.mark.parametrize(
    ("observation_kwargs", "error_code"),
    [
        ({"host_instance_id": "REVIT-RUNTIME-DRIFTED"}, "FRONT_DOOR_CONTEXT_INVALID"),
        ({"document_id": r"C:\Models\Other.rvt"}, "FRONT_DOOR_CONTEXT_INVALID"),
        ({"selected_unique_id": "WALL-UNIQUE-OTHER"}, "FRONT_DOOR_SELECTION_INVALID"),
    ],
)
def test_submit_fresh_context_drift_fails_before_composition_or_workflow(
    observation_kwargs: dict[str, str],
    error_code: str,
) -> None:
    """fresh runtime/document/selection 任一漂移都不得取得 composition 或推进 workflow。"""

    candidate = _candidate()
    binding = _binding(candidate)
    service, _reader, _candidates, transport, probe, pool, flow, _query = _submit_service(
        binding=binding,
        candidate=candidate,
        observation=_observation(candidate, **observation_kwargs),
    )

    with pytest.raises(ValueError, match=error_code):
        service.submit(_request(binding))

    assert transport.calls == [binding.transport_locator]
    assert probe.calls and probe.calls[0][1] == binding.document_id
    assert pool.calls == []
    assert flow.submit_calls == []


def test_submit_validates_authority_then_reuses_exact_objects_for_composition() -> None:
    """全部 authority/fresh evidence 通过后才取得 exact-session composition 并委托已有 flow。"""

    candidate = _candidate()
    binding = _binding(candidate)
    request = _request(binding)
    expected = ProductTaskQueryView(
        task_id=request.task_id,
        request_hash=request.request_hash,
        state=ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW,
        flow=None,
    )
    service, reader, candidates, transport, probe, pool, flow, query = _submit_service(
        binding=binding,
        candidate=candidate,
        observation=_observation(candidate),
        query_result=expected,
    )

    actual = service.submit(request)

    assert actual == expected
    assert reader.calls == [binding.session_ref]
    assert candidates.calls == [binding.candidate_key]
    assert transport.calls == [binding.transport_locator]
    assert probe.calls and probe.calls[0][1] == binding.document_id
    assert pool.calls == [(binding, candidate)]
    assert flow.submit_calls == [request]
    assert query.calls == [request.task_id]
