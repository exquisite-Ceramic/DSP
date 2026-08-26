"""Host health monitoring."""

from __future__ import annotations

import asyncio
import logging

from autocad_sidecar.adapter.host_adapter import HostAdapter

logger = logging.getLogger(__name__)


class StatusMonitor:
    """Periodically polls the plugin's status envelope to detect
    disconnects / document switches."""

    def __init__(self, host: HostAdapter, interval_s: float = 5.0) -> None:
        self._host = host
        self._interval_s = interval_s
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                status = await self._host.get_status()
                logger.debug("host status: %s", status.to_dict())
            except Exception as exc:  # noqa: BLE001 - monitor must survive
                logger.warning("status poll failed: %s", exc)
            await asyncio.sleep(self._interval_s)
