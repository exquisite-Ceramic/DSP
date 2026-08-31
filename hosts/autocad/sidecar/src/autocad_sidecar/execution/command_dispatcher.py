"""Command dispatcher: routes typed calls to adapters with retry + idempotency."""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from typing import Any

from design_fact_contracts import NormalizedDesignFactBatch
from host_contracts.command import HostCommand
from host_contracts.result import HostCommandResult

from autocad_sidecar.adapter.context_adapter import ContextAdapter
from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.adapter.interaction_adapter import InteractionAdapter
from autocad_sidecar.adapter.model_adapter import ModelAdapter
from autocad_sidecar.adapter.view_adapter import ViewAdapter
from autocad_sidecar.execution.idempotency import IdempotencyStore
from autocad_sidecar.execution.retry import RetryPolicy


def _finite_number(value: object, field_name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    return value


def _offset_arguments(
    handles: list[str],
    distance: Mapping[str, Any],
    side_point: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    if not isinstance(handles, list) or len(handles) != 1:
        raise ValueError("offset requires exactly one handle")
    handle = handles[0]
    if not isinstance(handle, str) or not handle.strip():
        raise ValueError("offset handle must be a non-empty string")

    if not isinstance(distance, Mapping):
        raise TypeError("distance must be an object")
    if distance.get("unit") != "mm":
        raise ValueError("distance unit must be mm")
    distance_value = _finite_number(distance.get("value"), "distance.value")
    if distance_value <= 0:
        raise ValueError("distance.value must be positive")

    if not isinstance(side_point, Mapping):
        raise TypeError("side_point must be an object")
    if side_point.get("unit") != "mm":
        raise ValueError("side_point unit must be mm")
    normalized_point = {
        axis: _finite_number(side_point.get(axis), f"side_point.{axis}")
        for axis in ("x", "y", "z")
    }
    normalized_point["unit"] = "mm"

    return (
        [handle.strip()],
        {"value": distance_value, "unit": "mm"},
        normalized_point,
    )


class CommandDispatcher:
    """Public entry point for agents and the test client.

    Handles Host context/view/model/interaction calls plus the internal Step 19
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
        self._interaction = InteractionAdapter(host)
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

    async def pick_point(
        self,
        *,
        idempotency_key: str,
        prompt: str | None = None,
    ) -> HostCommandResult:
        """Run one Host Canvas point prompt without automatic prompt retry."""
        key = str(idempotency_key).strip()
        if not key:
            raise ValueError("pick_point requires a stable idempotency_key")
        if await self._idempotency.is_completed(key):
            return await self._idempotency.recall(key)

        document = await self._context.current_document()
        if not document.ok:
            return document
        document_id = str((document.payload or {}).get("documentId") or "")
        if not document_id:
            raise RuntimeError("current_document response is missing documentId")

        result = await self._interaction.pick_point(
            document_id=document_id,
            idempotency_key=key,
            prompt=prompt,
        )
        if result.ok:
            await self._idempotency.complete(key, result)
        return result

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

    async def offset(
        self,
        handles: list[str],
        distance: Mapping[str, Any],
        side_point: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
        revision: int | None = None,
    ) -> HostCommandResult:
        normalized_handles, normalized_distance, normalized_side_point = (
            _offset_arguments(handles, distance, side_point)
        )
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
            return await self._model.offset(
                normalized_handles,
                normalized_distance,
                normalized_side_point,
                document_id=document_id,
                idempotency_key=key,
                revision=revision,
            )

        result = await self._retry.run(attempt)
        if result.ok:
            await self._idempotency.complete(key, result)
        return result

    async def set_wall_thickness(
        self,
        handles: list[str],
        thickness_mm: float,
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
            return await self._model.set_wall_thickness(
                handles,
                thickness_mm,
                document_id=document_id,
                idempotency_key=key,
                revision=revision,
            )

        result = await self._retry.run(attempt)
        if result.ok:
            await self._idempotency.complete(key, result)
        return result


# Task8 CI carrier: no semantic behavior change.
