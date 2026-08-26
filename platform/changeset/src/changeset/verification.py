"""Verification: checks a change set actually produced the expected state."""

from __future__ import annotations

from dataclasses import dataclass

from changeset.execution_unit import ExecutionUnit
from host_contracts.delta import HostDelta


@dataclass(slots=True)
class VerificationReport:
    ok: bool
    mismatches: list[str] = field(default_factory=list)


class ChangeSetVerifier:
    """Compares observed host deltas against expected change-set content.

    Phase 2 placeholder: structural checks only. Later this consults
    semantic_runtime snapshots for deep state comparison.
    """

    def verify(self, unit: ExecutionUnit, observed: list[HostDelta]) -> VerificationReport:
        expected_handles = {s.handle for s in unit.slices}
        observed_handles = {d.entity_ref.handle for d in observed}
        missing = sorted(expected_handles - observed_handles)
        extra = sorted(observed_handles - expected_handles)
        mismatches: list[str] = []
        if missing:
            mismatches.append(f"missing deltas for: {', '.join(missing)}")
        if extra:
            mismatches.append(f"unexpected deltas for: {', '.join(extra)}")
        return VerificationReport(ok=not mismatches, mismatches=mismatches)
