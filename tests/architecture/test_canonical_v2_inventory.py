from __future__ import annotations

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

ALLOWED_DISPOSITIONS = {
    "KEEP",
    "ADAPTER_ONLY",
    "CUTOVER_READY",
    "BLOCKED",
    "RETIREABLE",
}

REQUIRED_INVENTORY_AREAS = {
    "execution_planning",
    "materialization_planning_seam",
    "provider_binding",
    "gateway_authorization",
    "execution_coordination",
    "execution_reconciliation",
    "execution_saga",
    "convergence_compensation",
    "orchestrator",
    "workflow_test_ops",
    "real_host_acceptance",
}


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
    has_numeric_pr = pr_identity.startswith("#") and pr_identity[1:].isdigit()
    assert pr_identity == "PENDING" or has_numeric_pr
    assert int(status["tasks_used"]) <= 3


def test_known_parallel_public_surfaces_are_exactly_in_ledger() -> None:
    """已证实的 V1/V2 surface 必须精确出现在对应列，禁止 V2 子串误判。"""
    rows = _ledger_rows(LEDGER.read_text(encoding="utf-8"))
    pairs = {
        (row["v1_contract_or_path"], row["v2_contract_or_path"])
        for row in rows
    }
    assert (
        "design_execution_planning:ExecutionPlan",
        "design_execution_planning:ExecutionPlanV2",
    ) in pairs
    assert (
        "design_provider_binding:ProviderBindingSet",
        "design_provider_binding:ProviderBindingSetV2",
    ) in pairs


def test_inventory_closeout_rows_are_terminal_owned_and_complete() -> None:
    """Stage A 必须覆盖 mandatory areas，并把缺失证据收口成受约束 BLOCKED。"""
    text = LEDGER.read_text(encoding="utf-8")
    rows = _ledger_rows(text)
    assert rows

    observed_areas = {row["area"] for row in rows}
    assert REQUIRED_INVENTORY_AREAS <= observed_areas

    status = _inventory_status(text)
    pr_identity = status["dedicated_inventory_pr"]
    assert pr_identity.startswith("#") and pr_identity[1:].isdigit()
    assert status["tasks_used"] == "3"

    for row in rows:
        assert row["disposition"] in ALLOWED_DISPOSITIONS
        for field in (
            "producer",
            "consumers",
            "authoritative_owner",
            "persistence_owner",
            "retirement_preconditions",
            "rollback",
        ):
            assert row[field] not in {"", "UNKNOWN", "TBD"}

        has_missing_evidence = any(
            "EVIDENCE_MISSING:" in row[field]
            for field in ("parity_evidence", "real_host_evidence", "cutover_blocker")
        )
        if has_missing_evidence:
            assert row["disposition"] == "BLOCKED"
            assert row["authoritative_owner"] not in {"", "UNKNOWN", "TBD"}
            assert row["retirement_preconditions"] not in {"", "UNKNOWN", "TBD"}
