"""ExecutionSlice: the smallest independently executable piece of a change set."""

from __future__ import annotations

from dataclasses import dataclass, field

from host_contracts.delta import HostDelta


@dataclass(slots=True)
class ExecutionSlice:
    """A slice is a single entity operation with enough context to execute
    or revert it in isolation (phase 2: feeds the capability resolver)."""

    delta: HostDelta
    executable: bool = True
    reversible: bool = True
    preconditions: dict = field(default_factory=dict)

    @property
    def handle(self) -> str:
        return self.delta.entity_ref.handle
