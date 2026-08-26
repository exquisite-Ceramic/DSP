"""ChangeSet: a semantically grouped batch of host deltas."""

from __future__ import annotations

from dataclasses import dataclass, field

from host_contracts.delta import HostDelta


@dataclass(slots=True)
class ChangeSet:
    """One unit of meaning for the agent: a set of deltas produced by a
    single intent (command, user edit, undo)."""

    id: str
    intent: str  # e.g. "model.move", "user.edit", "undo"
    document_id: str
    base_revision: int
    deltas: list[HostDelta] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def target_revision(self) -> int:
        return max((d.revision for d in self.deltas), default=self.base_revision)

    def add(self, delta: HostDelta) -> None:
        self.deltas.append(delta)
