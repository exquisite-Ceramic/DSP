"""Step27 owner-local immutable ImpactAnalysis reference store."""

from __future__ import annotations

from .contracts import ImpactAnalysis, ImpactError


def _validate_analysis_reference(analysis: ImpactAnalysis) -> None:
    """Check the owner-issued reference fields without inventing a second hash algorithm."""
    if not isinstance(analysis, ImpactAnalysis):
        raise TypeError("analysis must be ImpactAnalysis")
    if not analysis.analysis_id.strip() or not analysis.analysis_fingerprint.strip():
        raise ImpactError(
            "IMPACT_ANALYSIS_REFERENCE_INTEGRITY_INVALID",
            "impact analysis reference requires id and fingerprint",
        )


class InMemoryImpactAnalysisStore:
    """Reference in-memory lookup surface for immutable Step27 analyses."""

    def __init__(self) -> None:
        self._items: dict[str, ImpactAnalysis] = {}

    def put(self, analysis: ImpactAnalysis) -> None:
        """Store one analysis; exact replay is idempotent and conflicts fail closed."""
        existing = self._items.get(analysis.analysis_id)
        if existing is not None and existing != analysis:
            raise ImpactError(
                "IMPACT_ANALYSIS_REFERENCE_CONFLICT",
                f"impact analysis reference conflicts: {analysis.analysis_id}",
            )
        _validate_analysis_reference(analysis)
        if existing is None:
            self._items[analysis.analysis_id] = analysis

    def get(self, analysis_id: str) -> ImpactAnalysis:
        """Resolve the owner artifact and re-check its stable reference fields."""
        try:
            analysis = self._items[analysis_id]
        except KeyError as exc:
            raise ImpactError(
                "IMPACT_ANALYSIS_REFERENCE_NOT_FOUND",
                f"impact analysis reference is unresolved: {analysis_id}",
            ) from exc
        _validate_analysis_reference(analysis)
        return analysis


__all__ = ["InMemoryImpactAnalysisStore"]
