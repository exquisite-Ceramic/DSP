from __future__ import annotations

import ast
import importlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/superpowers/modernization/canonical-v2-convergence-ledger.md"
GUARDED_LEGACY_ITEMS = {
    "CV2-001",
    "CV2-002",
    "CV2-003",
    "CV2-004",
    "CV2-005",
    "CV2-006",
    "CV2-007",
    "CV2-008",
}
ITEM_GUARD_TESTS = {
    "CV2-001": "test_stage_b_freezes_disposition_specific_legacy_consumers",
    "CV2-002": "test_stage_b_freezes_disposition_specific_legacy_consumers",
    "CV2-003": "test_stage_b_freezes_disposition_specific_legacy_consumers",
    "CV2-004": "test_stage_b_freezes_disposition_specific_legacy_consumers",
    "CV2-005": "test_stage_b_freezes_disposition_specific_legacy_consumers",
    "CV2-006": "test_stage_b_freezes_disposition_specific_legacy_consumers",
    "CV2-007": "test_stage_b_freezes_disposition_specific_legacy_consumers",
    "CV2-008": "test_stage_b_freezes_disposition_specific_legacy_consumers",
    "CV2-009": "test_stage_b_keeps_long_term_ownership_and_verification_boundaries",
    "CV2-010": "test_stage_b_keeps_long_term_ownership_and_verification_boundaries",
    "CV2-011": "test_stage_b_freezes_real_host_mixed_authority_boundary",
}
AUTOCAD_READINESS = (
    ROOT / "hosts/autocad/sidecar/src/autocad_sidecar/execution/readiness.py"
)
REVIT_READINESS = ROOT / "hosts/revit/sidecar/src/revit_sidecar/readiness.py"
REVIT_RESULT_ADAPTER = (
    ROOT / "hosts/revit/sidecar/src/revit_sidecar/execution_result_adapter.py"
)


def _production_python_roots() -> tuple[Path, ...]:
    """从 repository metadata 派生 production Python roots，并纳入 tools。"""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    members = {
        ROOT / value
        for value in config["tool"]["uv"]["workspace"]["members"]
    }
    pythonpath = {
        ROOT / value
        for value in config["tool"]["pytest"]["ini_options"]["pythonpath"]
        if not value.startswith("tests/")
    }
    roots = members | pythonpath | {ROOT / "tools"}
    return tuple(sorted(path for path in roots if path.exists()))


def _imports(path: Path) -> set[tuple[str, str | None]]:
    """用 AST 提取真实 import，不被注释、docstring 或相似字符串误导。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, str | None]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                found.add((node.module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add((alias.name, None))
    return found


def _production_python_files() -> tuple[Path, ...]:
    """排除 tests/cache/build，只扫描 production Python。"""
    files: set[Path] = set()
    for root in _production_python_roots():
        for path in root.rglob("*.py"):
            if any(
                part in {"tests", "__pycache__", ".venv", "build", "dist"}
                for part in path.parts
            ):
                continue
            files.add(path)
    return tuple(sorted(files))


def _ledger_rows(text: str) -> list[dict[str, str]]:
    """把 compatibility Markdown 表解析为逐列 row。"""
    lines = [line for line in text.splitlines() if line.startswith("|")]
    header_index = next(i for i, line in enumerate(lines) if line.startswith("| item_id |"))
    headers = [cell.strip() for cell in lines[header_index].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        if len(values) != len(headers):
            break
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _split_allowlist(value: str) -> set[str]:
    """把 ledger 的 repo-relative <br> allowlist 解析成集合。"""
    if value.startswith("N/A:"):
        return set()
    return {part.strip() for part in value.split("<br>") if part.strip()}


def _legacy_targets(row: dict[str, str]) -> tuple[tuple[str, str], ...]:
    """只把稳定 module:symbol 形式视为可执行 Python legacy boundary。"""
    targets: list[tuple[str, str]] = []
    for value in row["v1_contract_or_path"].split("<br>"):
        value = value.strip()
        if not value.startswith("design_") or value.count(":") != 1:
            continue
        module, symbol = value.split(":", 1)
        targets.append((module, symbol))
    return tuple(targets)


def current_consumers(module: str, symbol: str) -> set[str]:
    """返回 production roots 中对 public module:symbol 的直接 import consumer。"""
    target = (module, symbol)
    consumers: set[str] = set()
    for path in _production_python_files():
        if target in _imports(path):
            consumers.add(path.relative_to(ROOT).as_posix())
    return consumers


def test_stage_b_freezes_disposition_specific_legacy_consumers() -> None:
    """Stage B 必须冻结每个 package-level legacy boundary 的 production consumer。"""
    text = LEDGER.read_text(encoding="utf-8")
    assert "## Stage B boundary freeze" in text

    rows = _ledger_rows(text)
    assert all(row["disposition"] != "RETIREABLE" for row in rows)

    problems: list[str] = []
    by_id = {row["item_id"]: row for row in rows}
    for item_id in sorted(GUARDED_LEGACY_ITEMS):
        row = by_id[item_id]
        targets = _legacy_targets(row)
        if not targets:
            problems.append(f"{item_id}: missing machine-readable design_*:symbol legacy target")
            continue

        actual: set[str] = set()
        for module, symbol in targets:
            exported = importlib.import_module(module)
            if not hasattr(exported, symbol):
                problems.append(f"{item_id}: lost public export {module}:{symbol}")
                continue
            actual |= current_consumers(module, symbol)

        disposition = row["disposition"]
        if disposition in {"KEEP", "BLOCKED", "CUTOVER_READY"}:
            expected = _split_allowlist(row["runtime_callers"])
            if actual != expected:
                problems.append(
                    f"{item_id}: expected={sorted(expected)} actual={sorted(actual)}"
                )
        elif disposition == "ADAPTER_ONLY":
            adapters = _split_allowlist(row["bridge_or_adapter"])
            if not actual <= adapters:
                problems.append(
                    f"{item_id}: consumers={sorted(actual)} adapters={sorted(adapters)}"
                )
        else:
            problems.append(f"{item_id}: unsupported Stage B disposition {disposition}")

    assert not problems, "\n" + "\n".join(problems)


def test_stage_b_freezes_real_host_mixed_authority_boundary() -> None:
    """Host 专项 row 冻结 Revit V1 result adapter 与两端 V2 readiness 的并存事实。"""
    rows = {
        row["item_id"]: row
        for row in _ledger_rows(LEDGER.read_text(encoding="utf-8"))
    }
    host_row = rows["CV2-011"]
    assert host_row["disposition"] == "BLOCKED"
    assert _split_allowlist(host_row["runtime_callers"]) == {
        REVIT_RESULT_ADAPTER.relative_to(ROOT).as_posix()
    }

    assert (
        "design_gateway_authorization",
        "AdmittedExecutionAuthority",
    ) in _imports(REVIT_RESULT_ADAPTER)
    for readiness in (AUTOCAD_READINESS, REVIT_READINESS):
        imports = _imports(readiness)
        assert (
            "design_execution_planning",
            "ExecutionSliceV2",
        ) in imports
        assert (
            "design_gateway_authorization",
            "AdmittedExecutionAuthorityV2",
        ) in imports
        assert (
            "design_provider_binding",
            "ProviderBindingSetV2",
        ) in imports


def test_stage_b_keeps_long_term_ownership_and_verification_boundaries() -> None:
    """KEEP row 的稳定 public/artifact boundary 必须继续存在。"""
    rows = {
        row["item_id"]: row
        for row in _ledger_rows(LEDGER.read_text(encoding="utf-8"))
    }
    assert rows["CV2-009"]["disposition"] == "KEEP"
    assert rows["CV2-010"]["disposition"] == "KEEP"

    orchestrator = importlib.import_module("design_orchestrator")
    for symbol in ("StableRef", "WorkflowCheckpointView", "DefaultWorkflowServices"):
        assert hasattr(orchestrator, symbol)

    assert (ROOT / ".github/workflows/repository-regression.yml").is_file()
    assert (
        ROOT / ".github/workflows/phase-i-real-cross-host-materialization-saga.yml"
    ).is_file()
