from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/superpowers/modernization/canonical-v2-convergence-ledger.md"
EVIDENCE = ROOT / "docs/superpowers/modernization/canonical-v2-convergence-evidence.md"
BOUNDARY_TEST = ROOT / "tests/architecture/test_canonical_v2_boundaries.py"
CAPABILITY_HANDOFF = ROOT / "docs/superpowers/specs/2026-09-19-capability-phase-handoff.md"
ALLOWED_DISPOSITIONS = {
    "KEEP",
    "ADAPTER_ONLY",
    "CUTOVER_READY",
    "BLOCKED",
    "RETIREABLE",
}
REQUIRED_DEBTS = (
    "legacy_lane_package_declaration",
    "hitl_payload_ownership",
    "diverged_compensation_executor",
    "checkpoint_retention_gc",
)
EXPECTED_CAPABILITY_ORDER = [
    "HITL pause/resume",
    "real E2E workflow",
    "semantic -> plan -> approve -> execute -> reconcile",
    "MCP/Agent front door",
    "real AutoCAD/Revit acceptance",
]


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


def _contract_block(path: Path, fence: str) -> dict[str, str]:
    """解析稳定 fenced key=value contract。"""
    text = path.read_text(encoding="utf-8")
    marker = f"```{fence}"
    start = text.index(marker) + len(marker)
    end = text.index("```", start)
    values: dict[str, str] = {}
    for raw in text[start:end].splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _declared_item_guards() -> dict[str, str]:
    """读取 boundary test 声明的 item→guard test 映射，并验证目标 test 真存在。"""
    tree = ast.parse(BOUNDARY_TEST.read_text(encoding="utf-8"), filename=str(BOUNDARY_TEST))
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "ITEM_GUARD_TESTS"
            for target in node.targets
        ):
            continue
        mapping = ast.literal_eval(node.value)
        assert isinstance(mapping, dict)
        assert all(test_name in functions for test_name in mapping.values())
        return mapping
    raise AssertionError("ITEM_GUARD_TESTS declaration is missing")


def test_phase_ii_terminal_dispositions_are_closeout_safe() -> None:
    """逐 row 验证 terminal disposition、owner、evidence 与 merged-main gate。"""
    rows = _ledger_rows(LEDGER.read_text(encoding="utf-8"))
    assert rows
    guards = _declared_item_guards()

    for row in rows:
        assert row["disposition"] in ALLOWED_DISPOSITIONS
        for field in ("producer", "consumers", "authoritative_owner", "rollback"):
            assert row[field].strip()
            assert row[field].strip() not in {"UNKNOWN", "TBD"}
        assert all(value.strip() not in {"UNKNOWN", "TBD"} for value in row.values())

        evidence_fields = (
            row["parity_evidence"],
            row["real_host_evidence"],
            row["cutover_blocker"],
        )
        if any("EVIDENCE_MISSING:" in value for value in evidence_fields):
            assert row["disposition"] == "BLOCKED"
            assert row["authoritative_owner"].strip() not in {"", "UNKNOWN", "TBD"}
            assert row["retirement_preconditions"].strip() not in {"", "UNKNOWN", "TBD"}

        if row["disposition"] in {"KEEP", "ADAPTER_ONLY", "BLOCKED"}:
            assert row["item_id"] in guards

        if row["disposition"] == "RETIREABLE":
            assert row["merged_main_run"].startswith("run:")
            assert row["observation_status"] == "GREEN"


def test_phase_ii_pr55_debts_have_owner_and_next_action() -> None:
    """PR #55 四项遗留债务必须全部有 owner 与下一动作。"""
    debt = _contract_block(EVIDENCE, "phase-ii-debt-handoff")
    for debt_id in REQUIRED_DEBTS:
        assert debt[f"{debt_id}_owner"]
        assert debt[f"{debt_id}_next_action"]


def test_capability_phase_handoff_freezes_successor_order_and_blocking_policy() -> None:
    """Capability successor 必须固定顺序，并只允许显式 hard prerequisite 阻塞。"""
    assert CAPABILITY_HANDOFF.is_file()
    text = CAPABILITY_HANDOFF.read_text(encoding="utf-8")
    order = re.findall(r"^\d+\.\s+(.+)$", text, flags=re.MULTILINE)
    assert order[:5] == EXPECTED_CAPABILITY_ORDER

    contract = _contract_block(CAPABILITY_HANDOFF, "capability-phase-handoff")
    assert contract["successor"] == "Capability Phase"
    assert contract["ordinary_hygiene_blocks_start"] == "NO"
    assert contract["non_blocking_debt_blocks_start"] == "NO"
    assert contract["hard_prerequisite_policy"] == "EXPLICIT_ONLY"
