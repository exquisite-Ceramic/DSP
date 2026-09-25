"""Task 7 RED：Step33 V2 evidence seam 必须携带 admitted authority 与 binding lineage。"""

from __future__ import annotations

import inspect

import design_execution_coordination
from design_execution_coordination.ports import ConvergenceEvidencePort


def test_task7_exports_explicit_verification_evidence_unavailable() -> None:
    """known-commit evidence acquisition failure 需要稳定、可区分的显式异常。"""

    assert hasattr(design_execution_coordination, "VerificationEvidenceUnavailable"), (
        "Task 7 requires VerificationEvidenceUnavailable to distinguish unavailable "
        "independent READ evidence from semantic/integrity failures"
    )


def test_task7_v2_evidence_port_receives_exact_admitted_lineage() -> None:
    """evidence builder 必须拿到 exact authority + binding set，禁止重新猜 Host/native identity。"""

    parameters = inspect.signature(ConvergenceEvidencePort.build_bundle).parameters

    assert "authority" in parameters
    assert "binding_set" in parameters
