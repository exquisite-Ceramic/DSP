"""Product Front Door thin service 的 host-independent query contract。"""

from __future__ import annotations

from dataclasses import dataclass

from design_product_front_door.service import ProductFrontDoorService
from design_product_runtime import ProductTaskQueryState, ProductTaskQueryView


@dataclass
class _QueryService:
    """只记录 exact get；不需要任何 Host/session dependency。"""

    result: ProductTaskQueryView | None
    calls: list[str]

    def get(self, task_id: str) -> ProductTaskQueryView | None:
        self.calls.append(task_id)
        return self.result


class _ExplodingDependency:
    """任何方法/属性访问都代表 get() 错误触碰了 Host/session/composition seam。"""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"host-independent get touched forbidden dependency: {name}")


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
