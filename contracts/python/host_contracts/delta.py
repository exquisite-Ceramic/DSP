"""HostDelta: lightweight change stream (spec §12.3 / §26.8).

Revisions bracket the change; entity refs are grouped by change kind
(added / modified / erased). An entity MUST NOT appear in both ``added``
and ``erased`` unless the contract later defines such a lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from host_contracts.entity_ref import HostEntityRef


@dataclass(slots=True)
class HostDelta:
    revision_before: int = 0
    revision_after: int = 0
    added: list[HostEntityRef] = field(default_factory=list)
    modified: list[HostEntityRef] = field(default_factory=list)
    erased: list[HostEntityRef] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.revision_after < self.revision_before:
            errors.append("revision_after must be >= revision_before")
        added_keys = {(r.document_id, r.native_id) for r in self.added}
        erased_keys = {(r.document_id, r.native_id) for r in self.erased}
        overlap = sorted(added_keys & erased_keys)
        if overlap:
            errors.append(f"entity in both added and erased: {overlap}")
        return errors

    @classmethod
    def from_dict(cls, data: dict) -> "HostDelta":
        return cls(
            revision_before=data.get("revision_before", 0),
            revision_after=data.get("revision_after", 0),
            added=[HostEntityRef.from_dict(r) for r in data.get("added", [])],
            modified=[HostEntityRef.from_dict(r) for r in data.get("modified", [])],
            erased=[HostEntityRef.from_dict(r) for r in data.get("erased", [])],
        )

    def to_dict(self) -> dict:
        return {
            "revision_before": self.revision_before,
            "revision_after": self.revision_after,
            "added": [r.to_dict() for r in self.added],
            "modified": [r.to_dict() for r in self.modified],
            "erased": [r.to_dict() for r in self.erased],
        }
