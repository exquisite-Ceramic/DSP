"""Task 15.5 A1：V2 accepted-input 到 workflow bootstrap 的 TDD contract。"""

from __future__ import annotations

from contextlib import contextmanager

import design_product_runtime as product_runtime
from design_orchestrator import WorkflowCheckpointView, WorkflowPhase
from design_product_front_door.service import ProductFrontDoorService
from design_product_runtime import (
    ProductTaskQueryService,
    ProductTaskQueryState,
    ProductTaskRequestV2,
    ProductTaskV2Status,
)
from design_product_runtime.accepted_input import AcceptedProductTaskInputV2

from tests.product_front_door.test_cross_host_gate_a import (
    _binding,
    _binding_payload,
)


class _AcceptedStore:
    """同时充当 server accepted-input owner 与 query request reader。"""

    def __init__(self) -> None:
        self.accepted: AcceptedProductTaskInputV2 | None = None
        self.create_calls = 0

    def create_v2(
        self,
        request,
        *,
        session_binding_hash,
        session_binding_payload,
    ):
        """按 exact V2 body 幂等接受；不创建第二份 workflow truth。"""

        candidate = AcceptedProductTaskInputV2(
            request,
            session_binding_hash,
            session_binding_payload,
        )
        if self.accepted is None:
            self.accepted = candidate
        else:
            assert candidate == self.accepted
        self.create_calls += 1
        return self.accepted

    def get_v2(self, task_id: str):
        """按 exact task 返回 accepted input。"""

        if self.accepted is None:
            return None
        assert task_id == self.accepted.request.task_id
        return self.accepted

    def get(self, task_id: str):
        """V2 query 不得回退 V1 request reader。"""

        raise AssertionError(f"V2 query must not read V1 request: {task_id}")


class _Runtime:
    """最小 WorkflowOrchestratorPort double；记录真正的 start 次数。"""

    def __init__(self) -> None:
        self.checkpoint = None
        self.start_requests = []
        self.resume_calls = []

    def get_checkpoint(self, task_id: str):
        """读取 exact workflow checkpoint。"""

        if self.checkpoint is not None:
            assert task_id == self.checkpoint.task_id
        return self.checkpoint

    def start(self, request):
        """模拟 runtime 首次持久化 workflow navigation。"""

        self.start_requests.append(request)
        self.checkpoint = WorkflowCheckpointView(
            task_id=request.task_id,
            phase=WorkflowPhase.RESOLVE_HOST_CONTEXT,
        )
        return self.checkpoint

    def resume(self, task_id, command):
        """A1 不需要真实 resume，只保留接口完整性。"""

        self.resume_calls.append((task_id, command))
        assert self.checkpoint is not None
        return self.checkpoint


class _StartGate:
    """记录 exact task-row 临界区进入次数。"""

    def __init__(self) -> None:
        self.task_ids = []

    @contextmanager
    def serialize(self, task_id: str):
        """模拟现有 ProductTaskStartGate transaction scope。"""

        self.task_ids.append(task_id)
        yield


class _SagaStore:
    """start 阶段不存在 Saga；query 若尝试猜 Saga 即失败。"""

    def get_saga(self, saga_id: str):
        raise AssertionError(f"start path must not query Saga: {saga_id}")


class _SessionReader:
    """返回客户端已冻结的 exact SessionBindingV2。"""

    def __init__(self, binding) -> None:
        self.binding = binding

    def resolve_session_v2(self, session_ref: str):
        assert session_ref == self.binding.session_ref
        return self.binding


class _Validator:
    """记录 reviewed-config validation 必须发生在 server acceptance 之前。"""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def validate(self, binding) -> None:
        assert binding == _binding()
        self.events.append("validate")


class _Resolver:
    """V2 flow resolver 只接收 server-owned AcceptedProductTaskInputV2。"""

    def __init__(self, flow, events: list[str]) -> None:
        self.flow = flow
        self.events = events
        self.accepted = []

    def get_flow(self, accepted):
        assert isinstance(accepted, AcceptedProductTaskInputV2)
        self.accepted.append(accepted)
        self.events.append("resolve-flow")
        return self.flow


class _Forbidden:
    """A1 若误触 V1/Host seam 立即失败。"""

    def __getattr__(self, name: str):
        raise AssertionError(f"forbidden A1 dependency touched: {name}")

    def __call__(self, *args, **kwargs):
        raise AssertionError(f"forbidden A1 dependency called: {args=} {kwargs=}")


def _request():
    """构造与 exact frozen binding 一致的 V2 ProductTask request。"""

    binding = _binding()
    return ProductTaskRequestV2.create(
        task_id="task-cross-host-start",
        project_id=binding.project_id,
        initiating_host_kind="REVIT",
        session_ref=binding.session_ref,
        session_binding_hash=binding.binding_hash,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


def _service_harness():
    """组合真实 query + wished-for CrossHostProductFlow，Host I/O 全部禁止。"""

    flow_type = getattr(product_runtime, "CrossHostProductFlow", None)
    assert flow_type is not None, "CrossHostProductFlow 尚未实现"

    binding = _binding()
    accepted_store = _AcceptedStore()
    runtime = _Runtime()
    gate = _StartGate()
    flow = flow_type(
        workflow_runtime=runtime,
        start_gate=gate,
    )
    query = ProductTaskQueryService(
        request_store=accepted_store,
        checkpoint_reader=runtime,
        saga_store=_SagaStore(),
    )
    events: list[str] = []
    resolver = _Resolver(flow, events)
    validator = _Validator(events)
    service = ProductFrontDoorService(
        session_binding_reader=_SessionReader(binding),
        candidate_source=_Forbidden(),
        context_probe=_Forbidden(),
        transport_factory=_Forbidden(),
        query_service=query,
        composition_pool=_Forbidden(),
        reviewed_configuration_validator=validator,
        accepted_input_store=accepted_store,
        v2_flow_resolver=resolver,
    )
    return service, accepted_store, runtime, gate, resolver, events


def test_v2_submit_accepts_then_starts_exact_task_once() -> None:
    """server takeover 成功后必须启动同一个 exact ProductTask workflow。"""

    service, store, runtime, gate, resolver, events = _service_harness()
    request = _request()

    view = service.submit(request)

    assert store.create_calls == 1
    assert len(runtime.start_requests) == 1
    start = runtime.start_requests[0]
    assert start.task_id == request.task_id
    assert dict(start.request_data) == {
        "product_request_version": "V2",
        "product_request_task_id": request.task_id,
        "product_request_hash": request.request_hash,
        "product_session_binding_hash": request.session_binding_hash,
    }
    assert gate.task_ids == [request.task_id]
    assert len(resolver.accepted) == 1
    assert resolver.accepted[0] == store.accepted
    assert events == ["validate", "resolve-flow"]
    assert view.state is ProductTaskQueryState.WORKFLOW
    assert view.status is ProductTaskV2Status.WAITING


def test_v2_submit_replay_does_not_start_checkpoint_twice() -> None:
    """同 request replay 可重进 start gate，但已有 checkpoint 时不得再次 runtime.start。"""

    service, store, runtime, gate, resolver, _events = _service_harness()
    request = _request()

    first = service.submit(request)
    second = service.submit(request)

    assert first == second
    assert store.create_calls == 2
    assert len(runtime.start_requests) == 1
    assert gate.task_ids == [request.task_id, request.task_id]
    assert len(resolver.accepted) == 2
