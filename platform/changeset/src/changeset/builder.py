"""Builder: groups raw deltas into ChangeSets by intent and revision window."""

from __future__ import annotations

import uuid

from host_contracts.delta import HostDelta

from changeset.model import ChangeSet


class ChangeSetBuilder:
    """Collapses a stream of deltas into change sets.

    Phase 2 placeholder: currently one change set per flush with a caller
    supplied intent; later this will correlate deltas with the command that
    produced them (via correlationId) and with semantic_runtime snapshots.
    """

    def __init__(self) -> None:
        self._pending: list[HostDelta] = []

    def feed(self, delta: HostDelta) -> None:
        self._pending.append(delta)

    def flush(self, intent: str, document_id: str, base_revision: int) -> ChangeSet:
        deltas = self._pending
        self._pending = []
        return ChangeSet(
            id=str(uuid.uuid4()),
            intent=intent,
            document_id=document_id,
            base_revision=base_revision,
            deltas=deltas,
        )
