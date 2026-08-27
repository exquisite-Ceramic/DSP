"""Append-only semantic change journal and entity/aspect dirty tracking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from semantic_runtime.freshness import FreshnessState, SemanticAspect


@dataclass(frozen=True, slots=True)
class HostDeltaRecord:
    document_id: str
    host_revision: str
    semantic_id: str
    change_type: str
    affected_aspects: tuple[SemanticAspect, ...]

    def __post_init__(self) -> None:
        document_id = self.document_id.strip()
        host_revision = self.host_revision.strip()
        semantic_id = self.semantic_id.strip()
        change_type = self.change_type.strip().upper()
        if not document_id or not host_revision or not semantic_id or not change_type:
            raise ValueError("document_id, host_revision, semantic_id, and change_type are required")
        aspects = tuple(sorted(set(self.affected_aspects), key=lambda item: item.value))
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "host_revision", host_revision)
        object.__setattr__(self, "semantic_id", semantic_id)
        object.__setattr__(self, "change_type", change_type)
        object.__setattr__(self, "affected_aspects", aspects)


@dataclass(frozen=True, slots=True)
class JournalEntry:
    sequence: int
    actor: str
    delta: HostDeltaRecord


class ChangeJournal:
    """Small append-only MVP journal for Human/Agent host deltas."""

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []

    def append(self, *, actor: str, delta: HostDeltaRecord) -> JournalEntry:
        actor = actor.strip().upper()
        if actor not in {"HUMAN", "AGENT"}:
            raise ValueError("actor must be HUMAN or AGENT")
        entry = JournalEntry(sequence=len(self._entries) + 1, actor=actor, delta=delta)
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)


class DirtyMap:
    """Freshness state keyed by document + semantic entity + aspect."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str, SemanticAspect], FreshnessState] = {}

    def state(
        self,
        document_id: str,
        semantic_id: str,
        aspect: SemanticAspect,
    ) -> FreshnessState:
        return self._states.get(
            (document_id, semantic_id, aspect),
            FreshnessState.UNKNOWN,
        )

    def mark_dirty(
        self,
        document_id: str,
        semantic_id: str,
        aspects: Iterable[SemanticAspect],
    ) -> None:
        for aspect in aspects:
            self._states[(document_id, semantic_id, aspect)] = FreshnessState.DIRTY

    def mark_fresh(
        self,
        document_id: str,
        semantic_ids: Iterable[str],
        aspects: Iterable[SemanticAspect],
    ) -> None:
        aspect_tuple = tuple(aspects)
        for semantic_id in semantic_ids:
            for aspect in aspect_tuple:
                self._states[(document_id, semantic_id, aspect)] = FreshnessState.FRESH

    def apply(self, entry: JournalEntry) -> None:
        self.mark_dirty(
            entry.delta.document_id,
            entry.delta.semantic_id,
            entry.delta.affected_aspects,
        )
