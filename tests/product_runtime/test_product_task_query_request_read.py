"""ProductTaskQueryService 为 Front Door resume 暴露 exact immutable request read seam。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from design_product_runtime import (
    ProductTaskQueryError,
    ProductTaskQueryService,
    ProductTaskRequest,
)


@dataclass
class _RequestStore:
    result: ProductTaskRequest | None
    calls: list[str]

    def get(self, task_id: str) -> ProductTaskRequest | None:
        self.calls.append(task_id)
        return self.result


class _ForbiddenRead:
    """exact request read 不得顺带读取 checkpoint 或 Saga。"""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"get_request touched forbidden dependency: {name}")


def _request(task_id: str = "task-resume-001") -> ProductTaskRequest:
    return ProductTaskRequest.create(
        task_id=task_id,
        project_id="project-front-door",
        host_kind="REVIT",
        session_ref="session-front-door-001",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 350.0, "unit": "mm"}},
    )


def _service(store: _RequestStore) -> ProductTaskQueryService:
    forbidden = _ForbiddenRead()
    return ProductTaskQueryService(
        request_store=store,
        checkpoint_reader=forbidden,
        saga_store=forbidden,
    )


def test_get_request_reads_only_exact_immutable_request_owner() -> None:
    request = _request()
    store = _RequestStore(result=request, calls=[])

    actual = _service(store).get_request(request.task_id)

    assert actual == request
    assert store.calls == [request.task_id]


def test_get_request_unknown_task_returns_none_without_checkpoint_lookup() -> None:
    store = _RequestStore(result=None, calls=[])

    assert _service(store).get_request("task-missing") is None
    assert store.calls == ["task-missing"]


def test_get_request_wrong_task_body_fails_closed() -> None:
    store = _RequestStore(result=_request("task-other"), calls=[])

    with pytest.raises(ProductTaskQueryError) as exc_info:
        _service(store).get_request("task-resume-001")

    assert exc_info.value.code == "PRODUCT_TASK_LINEAGE_INVALID"
    assert store.calls == ["task-resume-001"]
