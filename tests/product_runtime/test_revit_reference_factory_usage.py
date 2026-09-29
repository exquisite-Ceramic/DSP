from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mandatory_product_acceptance_uses_public_reference_factory() -> None:
    """mandatory offline/live path 不得继续手拼 owner graph 或依赖 tests.orchestrator helpers。"""

    support_source = (REPO_ROOT / "tests/product_runtime/conftest.py").read_text(
        encoding="utf-8"
    )
    live_source = (
        REPO_ROOT / "tests/integration/test_revit_wall_thickness_product_live.py"
    ).read_text(encoding="utf-8")

    assert "tests.orchestrator" not in support_source
    assert "tests.orchestrator" not in live_source
    assert "build_revit_wall_thickness_reference_composition" in support_source
    assert "_product_support._compose_case(" not in live_source
