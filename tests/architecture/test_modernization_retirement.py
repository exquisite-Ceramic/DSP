"""M6 legacy baseline retirement 的反漂移契约。

Task 15 只能删除已经完成 canonical cutover、并具备 merged-main/Host observation 证据的旧路径。
Task 14 对 MOD-001 / MOD-012 的结论是 NO_CUTOVER，因此本轮 M6 必须显式记录
NO_RETIREMENTS，而不能把 Python 3.11、.NET 8 或架构兼容桥误当成可清理遗留项。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs" / "superpowers" / "modernization" / "modernization-ledger.md"
RUNTIME_MATRIX = ROOT / "docs" / "superpowers" / "modernization" / "runtime-matrix.md"
WORKFLOW = ROOT / ".github" / "workflows" / "repository-regression.yml"
GLOBAL_JSON = ROOT / "global.json"


def _ledger_row(mod_id: str) -> list[str]:
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {mod_id} |"):
            parts = [part.strip() for part in line.split("|")]
            assert len(parts) == 14, f"unexpected ledger column count for {mod_id}: {len(parts)}"
            return parts
    raise AssertionError(f"missing {mod_id} in modernization ledger")


def test_m6_requires_explicit_no_retirements_decision_without_cutover() -> None:
    """没有 M5 cutover/observation 证据时，M6 必须显式记录 NO_RETIREMENTS。"""

    runtime_matrix = RUNTIME_MATRIX.read_text(encoding="utf-8")
    ledger = LEDGER.read_text(encoding="utf-8")

    assert "`MOD-001`: `NO_CUTOVER`" in runtime_matrix
    assert "`MOD-012`: `NO_CUTOVER`" in runtime_matrix
    assert "## M6 Task 15 retirement decision" in ledger
    assert "`NO_RETIREMENTS`" in ledger
    assert "merged-main" in ledger


def test_no_cutover_keeps_python_and_dotnet_baselines_active() -> None:
    """M5 未切换时，3.11/.NET 8 canonical 与候选 compatibility lane 都必须保留。"""

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'python-version: "3.11"\n            lane: canonical' in workflow
    assert 'python-version: "3.14"\n            lane: compatibility' in workflow
    assert 'dotnet-version: "8.0.x"' in workflow
    assert 'dotnet-version: "10.0.x"' in workflow

    sdk = json.loads(GLOBAL_JSON.read_text(encoding="utf-8"))["sdk"]
    assert sdk["version"] == "8.0.100"
    assert sdk["rollForward"] == "latestFeature"


def test_t4_compatibility_bridges_are_not_m6_retirement_candidates() -> None:
    """MOD-016 架构兼容桥必须继续留在 Architecture Modernization Review。"""

    row = _ledger_row("MOD-016")
    assert row[5] == "T4"
    assert row[6] == "DEFER_ARCHITECTURE"
    assert row[9] == "DEFERRED"
    assert row[10] == "DEFERRED"
