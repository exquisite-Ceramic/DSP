"""M5 canonical cutover 的反漂移契约。

Task 14 只能切换已经 VERIFIED 的运行时/SDK 项。若候选仍是 APPROVED，旧 canonical
baseline 必须保持不变，并在 runtime matrix / ledger 中显式记录 NO_CUTOVER。
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
GLOBAL_JSON = ROOT / "global.json"
WORKFLOW = ROOT / ".github" / "workflows" / "repository-regression.yml"
RUNTIME_MATRIX = ROOT / "docs" / "superpowers" / "modernization" / "runtime-matrix.md"
LEDGER = ROOT / "docs" / "superpowers" / "modernization" / "modernization-ledger.md"
REVIT_CORE = (
    ROOT
    / "hosts"
    / "revit"
    / "plugin"
    / "Revit.AgentHost.Core"
    / "Revit.AgentHost.Core.csproj"
)
AUTOCAD_NATIVE = (
    ROOT
    / "hosts"
    / "autocad"
    / "plugin"
    / "AutoCAD.AgentHost"
    / "AutoCAD.AgentHost.csproj"
)
REVIT_NATIVE = ROOT / "hosts" / "revit" / "plugin" / "Revit.AgentHost" / "Revit.AgentHost.csproj"


def _ledger_status(mod_id: str) -> tuple[str, str]:
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.startswith(f"| {mod_id} |"):
            continue
        parts = [part.strip() for part in line.split("|")]
        assert len(parts) == 14, f"unexpected ledger column count for {mod_id}: {len(parts)}"
        return parts[9], parts[10]
    raise AssertionError(f"missing {mod_id} in modernization ledger")


def test_unverified_runtime_candidates_cannot_become_canonical() -> None:
    """未 VERIFIED 的 Python/.NET 候选不得在 M5 偷偷成为 canonical。"""

    assert _ledger_status("MOD-001") == ("APPROVED", "APPROVED")
    assert _ledger_status("MOD-012") == ("APPROVED", "APPROVED")

    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert pyproject["project"]["requires-python"] == ">=3.11"
    assert pyproject["tool"]["ruff"]["target-version"] == "py311"

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'python-version: "3.11"\n            lane: canonical' in workflow
    assert 'python-version: "3.14"\n            lane: compatibility' in workflow
    assert 'dotnet-version: "8.0.x"' in workflow
    assert 'dotnet-version: "10.x"' in workflow

    sdk = json.loads(GLOBAL_JSON.read_text(encoding="utf-8"))["sdk"]
    assert sdk == {
        "version": "8.0.100",
        "rollForward": "latestFeature",
        "allowPrerelease": False,
    }

    revit_core = REVIT_CORE.read_text(encoding="utf-8")
    assert "<TargetFrameworks>net8.0</TargetFrameworks>" in revit_core
    assert "DspEnableNet10Compatibility" in revit_core
    assert "net8.0;net10.0" in revit_core


def test_m5_no_cutover_decision_is_explicit_in_governance_records() -> None:
    """M5 即使没有合格 cutover，也必须留下机器可检索的决策记录。"""

    runtime_matrix = RUNTIME_MATRIX.read_text(encoding="utf-8")
    ledger = LEDGER.read_text(encoding="utf-8")

    assert "## M5 Task 14 canonical cutover decision" in runtime_matrix
    assert "`MOD-001`: `NO_CUTOVER`" in runtime_matrix
    assert "`MOD-012`: `NO_CUTOVER`" in runtime_matrix
    assert "Task 14 cutover decision `NO_CUTOVER`" in ledger


def test_native_host_targets_remain_owned_by_the_host_matrix() -> None:
    """M5 repository baseline不得覆盖 Task 13 的 native Host TFM ownership。"""

    autocad = AUTOCAD_NATIVE.read_text(encoding="utf-8")
    revit = REVIT_NATIVE.read_text(encoding="utf-8")

    assert "<TargetFramework>net8.0-windows</TargetFramework>" in autocad
    assert "<TargetFramework>$(DspRevitTargetFramework)</TargetFramework>" in revit
    assert "DspRevitTargetFramework must be supplied" in revit
