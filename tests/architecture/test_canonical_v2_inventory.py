from __future__ import annotations

import re
from pathlib import Path


LEDGER = Path("docs/superpowers/modernization/canonical-v2-convergence-ledger.md")

REQUIRED_COLUMNS = (
    "item_id",
    "area",
    "v1_contract_or_path",
    "v2_contract_or_path",
    "bridge_or_adapter",
    "producer",
    "consumers",
    "public_exports",
    "runtime_callers",
    "test_callers",
    "host_dependency",
    "authoritative_owner",
    "persistence_owner",
    "semantic_delta",
    "parity_evidence",
    "real_host_evidence",
    "cutover_blocker",
    "disposition",
    "retirement_preconditions",
    "rollback",
    "exact_head_run",
    "merged_main_run",
    "observation_status",
)


def _inventory_status(text: str) -> dict[str, str]:
    """解析 Inventory status 的稳定 key=value 区块。"""
    status: dict[str, str] = {}
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "```inventory-status":
            in_block = True
            continue
        if in_block and line == "```":
            break
        if in_block and "=" in line:
            key, value = line.split("=", 1)
            status[key.strip()] = value.strip()
    return status


def test_phase_ii_ledger_has_complete_schema() -> None:
    """Ledger 必须完整冻结 spec 20 字段和 3 个 observation 字段。"""
    text = LEDGER.read_text(encoding="utf-8")
    header = next(line for line in text.splitlines() if line.startswith("| item_id |"))
    for column in REQUIRED_COLUMNS:
        assert f"| {column} " in header


def test_inventory_budget_is_machine_readable_and_bounded() -> None:
    """Inventory 的 2 工作日 / 3 tasks / 1 PR 必须可执行验证。"""
    status = _inventory_status(LEDGER.read_text(encoding="utf-8"))
    assert status["working_day_budget"] == "2"
    assert status["task_budget"] == "3"
    pr_identity = status["dedicated_inventory_pr"]
    assert pr_identity == "PENDING" or re.fullmatch(r"#\d+", pr_identity)
    assert int(status["tasks_used"]) <= 3
