"""Command dispatcher: routes typed calls to adapters with retry + idempotency."""

from __future__ import annotations

import uuid

from design_fact_contracts import NormalizedDesignFactBatch
from host_contracts.command import HostCommand
from host_contracts.result import HostCommandResult

from autocad_sidecar.adapter.context_adapter import ContextAdapter
from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.adapter.model_adapter import ModelAdapter
from autocad_sidecar.adapter.view_adapter import ViewAdapter
from autocad_sidecar.execution.idempotency import IdempotencyStore
from autocad_sidecar.execution.retry import RetryPolicy


class CommandDispatcher:
    """Public entry point for agents and the test client.

    Handles Host context/view/model calls plus the internal Step 19
    native-snapshot-to-design-fact read path.
    """

    def __init__(
        self,
        host: HostAdapter,
        idempotency: IdempotencyStore | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._host = host
        self._idempotency = idempotency or IdempotencyStore()
        self._retry = retry or RetryPolicy()
        self._context = ContextAdapter(host)
        self._view = ViewAdapter(host)
        self._model = ModelAdapter(host)
        self._design_facts = DesignFactAdapter()

    async def current_document(self) -> HostCommandResult:
        return await self._context.current_document()

    async def current_selection(self) -> HostCommandResult:
        return await self._context.current_selection()

    async def extract_design_facts(
        self,
        handles: list[str],
    ) -> NormalizedDesignFactBatch:
        command = HostCommand(
            command_id=str(uuid.uuid4()),
            mode="READ",
            operation="design.extract_native_snapshot",
            arguments={"handles": handles},
        )
        result = await self._host.send_command(command)
        if not result.ok:
            message = (
                result.error.message
                if result.error is not None
                else "native fact extraction failed"
            )
            raise RuntimeError(message)
        return self._design_facts.normalize_snapshot(result.payload or {})

    async def fit(self, handles: list[str] | None = None) -> HostCommandResult:
        return await self._view.fit(handles)

    async def move(
        self,
        handles: list[str],
        dx: float,
        dy: float,
        dz: float = 0.0,
        *,
        idempotency_key: str | None = None,
        revision: int | None = None,
    ) -> HostCommandResult:
        key = idempotency_key or str(uuid.uuid4())
        if await self._idempotency.is_completed(key):
            return await self._idempotency.recall(key)

        document = await self._context.current_document()
        if not document.ok:
            return document
        document_id = str((document.payload or {}).get("documentId") or "")
        if not document_id:
            raise RuntimeError("current_document response is missing documentId")

        async def attempt() -> HostCommandResult:
            return await self._model.move(
                handles,
                dx,
                dy,
                dz,
                document_id=document_id,
                idempotency_key=key,
                revision=revision,
            )

        result = await self._retry.run(attempt)
        if result.ok:
            await self._idempotency.complete(key, result)
        return result
