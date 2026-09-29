"""Product Front Door 的薄应用 service；业务真相继续由既有 owner 持有。"""

from __future__ import annotations

from design_product_runtime import ProductTaskQueryService, ProductTaskQueryView


class ProductFrontDoorService:
    """协调 server-side Product Front Door seams，不复制任何业务 owner state。"""

    def __init__(
        self,
        *,
        session_binding_reader: object,
        candidate_source: object,
        context_probe: object,
        transport_factory: object,
        query_service: ProductTaskQueryService,
        composition_pool: object,
    ) -> None:
        """保存已注入 seams；构造阶段不得解析 session、打开 Host 或创建 composition。"""

        if query_service is None:
            raise ValueError("query_service must not be None")
        self._session_binding_reader = session_binding_reader
        self._candidate_source = candidate_source
        self._context_probe = context_probe
        self._transport_factory = transport_factory
        self._query_service = query_service
        self._composition_pool = composition_pool

    def get(self, task_id: str) -> ProductTaskQueryView | None:
        """只委托 host-independent durable query；不得解析 session 或访问 Host。"""

        return self._query_service.get(task_id)


__all__ = ["ProductFrontDoorService"]
