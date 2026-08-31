from __future__ import annotations

from typing import Protocol


class PipeEndpoint(Protocol):
    def exchange(self, packet: bytes) -> bytes: ...
