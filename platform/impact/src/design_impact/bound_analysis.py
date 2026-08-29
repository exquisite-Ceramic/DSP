"""Backward-compatible public Step27 binding hardening for Step29 joins."""

from __future__ import annotations

from dataclasses import dataclass

from .analyzer import ImpactAnalysisRequest, ImpactAnalyzer as _ImpactAnalyzer, _canonical_hash
from .contracts import ImpactAnalysis as _ImpactAnalysis


def _bound_operation_fingerprint(request: ImpactAnalysisRequest) -> str:
    bound = request.bound_operation
    return _canonical_hash(
        {
            "canonical_operation": bound.operation.canonical_operation,
            "canonical_operation_version": bound.operation.version,
            "arguments": bound.arguments,
        }
    )


@dataclass(frozen=True, slots=True)
class ImpactAnalysis(_ImpactAnalysis):
    """Public Step27 result with an explicit D6 material-operation binding."""

    bound_operation_fingerprint: str = ""

    def __post_init__(self) -> None:
        _ImpactAnalysis.__post_init__(self)
        if self.bound_operation_fingerprint:
            normalized = str(self.bound_operation_fingerprint).strip()
            if not normalized:
                raise ValueError("bound_operation_fingerprint must be non-empty when supplied")
            object.__setattr__(self, "bound_operation_fingerprint", normalized)


class ImpactAnalyzer(_ImpactAnalyzer):
    """Step27 analyzer that exposes the D6 operation material already committed by analysis."""

    def analyze(self, request: ImpactAnalysisRequest) -> ImpactAnalysis:
        result = super().analyze(request)
        return ImpactAnalysis(
            analysis_id=result.analysis_id,
            canonical_operation=result.canonical_operation,
            direct_targets=result.direct_targets,
            planning_snapshot_ref=result.planning_snapshot_ref,
            snapshot_set_ref=result.snapshot_set_ref,
            semantic_environment_ref=result.semantic_environment_ref,
            predicted_impacts=result.predicted_impacts,
            propagation_bundles=result.propagation_bundles,
            exceptions=result.exceptions,
            analysis_fingerprint=result.analysis_fingerprint,
            bound_operation_fingerprint=_bound_operation_fingerprint(request),
        )


__all__ = ["ImpactAnalysis", "ImpactAnalyzer"]
