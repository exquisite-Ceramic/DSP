from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/superpowers/modernization/canonical-v2-convergence-ledger.md"
EVIDENCE = ROOT / "docs/superpowers/modernization/canonical-v2-convergence-evidence.md"


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


def test_retireable_rows_require_merged_main_observation() -> None:
    """RETIREABLE 必须由 merged-main evidence 授权，不能靠 branch-local GREEN。"""
    rows = _ledger_rows(LEDGER.read_text(encoding="utf-8"))
    for row in rows:
        if row["disposition"] != "RETIREABLE":
            continue
        assert row["merged_main_run"].startswith("run:")
        assert row["observation_status"] == "GREEN"
        assert row["rollback"] not in {"", "UNKNOWN", "TBD", "N/A"}


def test_zero_retirement_state_is_explicitly_recorded() -> None:
    """没有 RETIREABLE item 时必须显式记录零 retirement 授权。"""
    rows = _ledger_rows(LEDGER.read_text(encoding="utf-8"))
    if any(row["disposition"] == "RETIREABLE" for row in rows):
        return

    assert EVIDENCE.is_file()
    evidence = EVIDENCE.read_text(encoding="utf-8")
    assert "NO_RETIREMENTS_AUTHORIZED" in evidence
