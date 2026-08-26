"""Retry policy for write commands (retryable errors only)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from host_contracts.result import HostCommandResult

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryPolicy:
    """Exponential backoff for retryable failures.

    Only results whose error carries ``retryable == "IMMEDIATE"`` are
    retried (spec §19.2); the idempotency key guarantees a replay is safe.
    """

    def __init__(self, max_attempts: int = 3, base_delay_s: float = 0.25, max_delay_s: float = 5.0) -> None:
        self.max_attempts = max(1, max_attempts)
        self.base_delay_s = base_delay_s
        self.max_delay_s = max_delay_s

    async def run(self, attempt: Callable[[], Awaitable[T]]) -> T:
        last: T | None = None
        for i in range(self.max_attempts):
            last = await attempt()
            if isinstance(last, HostCommandResult) and self._should_retry(last):
                delay = min(self.base_delay_s * (2**i), self.max_delay_s)
                logger.warning("retry %d/%d after %ss: %s", i + 1, self.max_attempts, delay, last.error)
                await asyncio.sleep(delay)
                continue
            return last
        assert last is not None
        return last

    @staticmethod
    def _should_retry(result: HostCommandResult) -> bool:
        return not result.ok and result.error is not None and result.error.retryable == "IMMEDIATE"
