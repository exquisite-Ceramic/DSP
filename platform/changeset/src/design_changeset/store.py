"""Step29 owner-local immutable ChangeSet reference store."""

from __future__ import annotations

import re

from .contracts import CanonicalChangeSet, ChangeSetError

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _validate_reference(changeset: CanonicalChangeSet) -> None:
    """Validate stable reference fields without pulling Step28 into this owner store."""
    if not isinstance(changeset, CanonicalChangeSet):
        raise TypeError("changeset must be CanonicalChangeSet")
    if (
        not changeset.changeset_id.strip()
        or _HASH_PATTERN.fullmatch(changeset.changeset_hash) is None
    ):
        raise ChangeSetError(
            "CHANGESET_REFERENCE_INTEGRITY_INVALID",
            "ChangeSet reference requires a stable id and lowercase SHA-256 hash",
        )


class InMemoryChangeSetStore:
    """Reference in-memory lookup surface for immutable canonical ChangeSets."""

    def __init__(self) -> None:
        self._items: dict[str, CanonicalChangeSet] = {}

    def put(self, changeset: CanonicalChangeSet) -> None:
        """Store one ChangeSet; identical replay is safe and conflicts fail closed."""
        existing = self._items.get(changeset.changeset_id)
        if existing is not None and existing != changeset:
            raise ChangeSetError(
                "CHANGESET_REFERENCE_CONFLICT",
                f"ChangeSet reference conflicts: {changeset.changeset_id}",
            )
        _validate_reference(changeset)
        if existing is None:
            self._items[changeset.changeset_id] = changeset

    def get(self, changeset_id: str) -> CanonicalChangeSet:
        """Resolve one owner artifact and re-check its stable reference fields."""
        try:
            changeset = self._items[changeset_id]
        except KeyError as exc:
            raise ChangeSetError(
                "CHANGESET_REFERENCE_NOT_FOUND",
                f"ChangeSet reference is unresolved: {changeset_id}",
            ) from exc
        _validate_reference(changeset)
        return changeset


__all__ = ["InMemoryChangeSetStore"]
