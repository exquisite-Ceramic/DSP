"""Sidecar-side idempotency bookkeeping (ADR-003)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from host_contracts.result import HostCommandResult


@dataclass
class _Entry:
    result: HostCommandResult
    completed: bool = True


class IdempotencyStore:
    """In-memory record of completed write commands keyed by idempotency key.

    The plugin keeps the authoritative cache; this store only prevents the
    sidecar from re-sending a key that already succeeded.
    """

    def __init__(self, max_entries: int = 1024) -> None:
        self._entries: dict[str, _Entry] = {}
        self._max = max_entries

    async def is_completed(self, key: str) -> bool:
        entry = self._entries.get(key)
        return entry is not None and entry.completed

    async def recall(self, key: str) -> HostCommandResult:
        entry = self._entries.get(key)
        if entry is None:
            raise KeyError(f"no completed command for key {key!r}")
        return replace(entry.result, replayed=True)

    async def complete(self, key: str, result: HostCommandResult) -> None:
        if len(self._entries) >= self._max:
            # Drop oldest insertion (dict preserves insertion order).
            self._entries.pop(next(iter(self._entries)))
        self._entries[key] = _Entry(result=result, completed=True)
