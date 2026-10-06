"""ProductTask request 与 workflow checkpoint 的 host-independent exact query composition。"""

from __future__ import annotations

from typing import Protocol

from design_execution_reconciliation import ExecutionSagaStoreV2
from design_orchestrator import WorkflowCheckpointView

from .accepted_input import AcceptedProductTaskInputV2
from .contracts import (
    ProductTaskQueryState,
    ProductTaskQueryView,
    ProductTaskRequest,
    ProductTaskRequestError,
)
from .wall_thickness_flow import ProductTaskRequestStore, project_wall_thickness_product_flow


class ProductTaskQueryError(RuntimeError):
    """ProductTask query 发现跨 owner lineage 损坏时使用的稳定错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProductTaskCheckpointReadPort(Protocol):
    """query 只依赖 framework-neutral checkpoint 读取，不需要可执行 workflow runtime。"""

    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None:
        """按 exact task_id 读取当前 durable checkpoint。"""

        ...


class ProductTaskQueryService:
    """按冻结读序组合既有 owner truth，不创建、恢复或推进 workflow。"""

    def __init__(
        self,
        *,
        request_store: ProductTaskRequestStore,
        checkpoint_reader: ProductTaskCheckpointReadPort,
        saga_store: ExecutionSagaStoreV2,
    ) -> None:
        """绑定三个只读 owner seam；query 自身不持有任何 durable state。"""

        if request_store is None:
            raise ValueError("request_store must not be None")
        if checkpoint_reader is None:
            raise ValueError("checkpoint_reader must not be None")
        if saga_store is None:
            raise ValueError("saga_store must not be None")
        self._request_store = request_store
        self._checkpoint_reader = checkpoint_reader
        self._saga_store = saga_store

    def get_request(self, task_id: str) -> ProductTaskRequest | None:
        """只按 exact task_id 读取 immutable request owner，不读取 checkpoint 或 Saga。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ProductTaskQueryError(
                "PRODUCT_TASK_QUERY_INVALID",
                "task_id must be a non-blank string",
            )
        normalized_task_id = task_id.strip()
        request = self._request_store.get(normalized_task_id)
        if request is None:
            return None
        self._require_exact_request(request, normalized_task_id)
        return request

    def get_accepted_input_v2(
        self,
        task_id: str,
    ) -> AcceptedProductTaskInputV2 | None:
        """按 exact task 读取 V2 accepted input；V1/missing task 返回 None。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ProductTaskQueryError(
                "PRODUCT_TASK_QUERY_INVALID",
                "task_id must be a non-blank string",
            )
        normalized_task_id = task_id.strip()
        get_v2 = getattr(self._request_store, "get_v2", None)
        if not callable(get_v2):
            return None
        try:
            accepted = get_v2(normalized_task_id)
        except ProductTaskRequestError as exc:
            if exc.code == "PRODUCT_TASK_REQUEST_VERSION_MISMATCH":
                return None
            raise
        if accepted is None:
            return None
        if (
            not isinstance(accepted, AcceptedProductTaskInputV2)
            or accepted.request.task_id != normalized_task_id
        ):
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "request store returned V2 accepted input for a different task",
            )
        return accepted

    def get(self, task_id: str) -> ProductTaskQueryView | None:
        """执行 request→checkpoint→必要时 request 稳定化重读的冻结查询顺序。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ProductTaskQueryError(
                "PRODUCT_TASK_QUERY_INVALID",
                "task_id must be a non-blank string",
            )
        normalized_task_id = task_id.strip()

        accepted_v2 = self.get_accepted_input_v2(normalized_task_id)
        if accepted_v2 is not None:
            checkpoint = self._checkpoint_reader.get_checkpoint(normalized_task_id)
            if checkpoint is None:
                return ProductTaskQueryView(
                    task_id=accepted_v2.request.task_id,
                    request_hash=accepted_v2.request.request_hash,
                    state=ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW,
                    flow=None,
                )
            if checkpoint.task_id != normalized_task_id:
                raise ProductTaskQueryError(
                    "PRODUCT_TASK_LINEAGE_INVALID",
                    "workflow checkpoint task_id does not match authoritative V2 request",
                )
            flow = project_wall_thickness_product_flow(checkpoint, self._saga_store)
            return ProductTaskQueryView(
                task_id=accepted_v2.request.task_id,
                request_hash=accepted_v2.request.request_hash,
                state=ProductTaskQueryState.WORKFLOW,
                flow=flow,
            )

        request = self._request_store.get(normalized_task_id)
        checkpoint = self._checkpoint_reader.get_checkpoint(normalized_task_id)

        if request is None and checkpoint is None:
            return None

        if request is not None and checkpoint is None:
            self._require_exact_request(request, normalized_task_id)
            return ProductTaskQueryView(
                task_id=request.task_id,
                request_hash=request.request_hash,
                state=ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW,
                flow=None,
            )

        if checkpoint is None:
            # 前两个分支已经覆盖 checkpoint=None；保留防御性不可达保护。
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "checkpoint state changed unexpectedly during query",
            )

        if request is None:
            # request/checkpoint 分属独立 durable owner。checkpoint 读取期间 request 可能刚提交，
            # 因此必须在判定 corruption 前做一次 exact task stabilization re-read。
            request = self._request_store.get(normalized_task_id)
            if request is None:
                raise ProductTaskQueryError(
                    "PRODUCT_TASK_LINEAGE_INVALID",
                    "workflow checkpoint exists without authoritative ProductTask request",
                )

        self._require_exact_request(request, normalized_task_id)
        if checkpoint.task_id != normalized_task_id:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "workflow checkpoint task_id does not match authoritative request",
            )

        flow = project_wall_thickness_product_flow(checkpoint, self._saga_store)
        return ProductTaskQueryView(
            task_id=request.task_id,
            request_hash=request.request_hash,
            state=ProductTaskQueryState.WORKFLOW,
            flow=flow,
        )

    @staticmethod
    def _require_exact_request(request: ProductTaskRequest, task_id: str) -> None:
        """防御异常 adapter 返回错误 task body，禁止 query 靠调用 locator 猜测修正。"""

        if not isinstance(request, ProductTaskRequest) or request.task_id != task_id:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "request store returned a ProductTask request for a different task",
            )


__all__ = [
    "ProductTaskCheckpointReadPort",
    "ProductTaskQueryError",
    "ProductTaskQueryService",
]
