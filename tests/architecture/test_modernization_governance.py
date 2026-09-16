from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODERNIZATION = ROOT / "docs" / "superpowers" / "modernization"
ROOT_README = ROOT / "README.md"
SUPERPOWERS_README = ROOT / "docs" / "superpowers" / "README.md"
ARCHITECTURE_REVIEW_INPUT = MODERNIZATION / "architecture-modernization-review-input.md"


def _ledger_rows() -> list[dict[str, str]]:
    ledger = (MODERNIZATION / "modernization-ledger.md").read_text(encoding="utf-8")
    lines = [line for line in ledger.splitlines() if line.startswith("| MOD-")]
    columns = (
        "ID",
        "Area",
        "Current",
        "Candidate",
        "Risk",
        "Decision",
        "Owner",
        "Consumers",
        "Status",
        "Execution state",
        "Evidence",
        "Rollback",
    )
    rows: list[dict[str, str]] = []
    for line in lines:
        values = [value.strip() for value in line.strip().strip("|").split("|")]
        assert len(values) == len(columns), f"unexpected ledger column count: {line}"
        rows.append(dict(zip(columns, values, strict=True)))
    return rows


def test_modernization_governance_files_and_seed_ids_exist() -> None:
    required = {
        "modernization-ledger.md",
        "runtime-matrix.md",
        "dependency-inventory.md",
        "host-compatibility-matrix.md",
        "modernization-risk-register.md",
    }
    assert required <= {path.name for path in MODERNIZATION.glob("*.md")}

    ledger = (MODERNIZATION / "modernization-ledger.md").read_text(encoding="utf-8")
    for number in range(1, 17):
        assert f"MOD-{number:03d}" in ledger
    for token in ("T0", "T1", "T2", "T3", "T4", "DEFER"):
        assert token in ledger


def test_m0_inventory_covers_all_audit_areas_and_known_roots() -> None:
    inventory = (MODERNIZATION / "dependency-inventory.md").read_text(encoding="utf-8")
    runtime = (MODERNIZATION / "runtime-matrix.md").read_text(encoding="utf-8")
    host = (MODERNIZATION / "host-compatibility-matrix.md").read_text(encoding="utf-8")
    joined = "\n".join((inventory, runtime, host))

    for marker in (
        "A1 Runtime",
        "A2 Dependency",
        "A3 Deprecation",
        "A4 Build & Packaging",
        "A5 Protocol & Schema",
        "A6 Host Compatibility",
        "A7 CI & Toolchain",
    ):
        assert marker in joined

    for path in (
        "pyproject.toml",
        "contracts/python/pyproject.toml",
        "hosts/autocad/sidecar/pyproject.toml",
        "hosts/revit/sidecar/pyproject.toml",
        "global.json",
        "contracts/proto/host_transport_v1.proto",
        "hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj",
        "hosts/revit/plugin/Revit.AgentHost.Core/Revit.AgentHost.Core.csproj",
        "hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj",
    ):
        assert path in inventory


def test_m0_decisions_are_complete_and_executable_boundary_is_frozen() -> None:
    rows = _ledger_rows()
    assert [row["ID"] for row in rows] == [f"MOD-{number:03d}" for number in range(1, 17)]

    allowed_decisions = {"KEEP", "PIN_LOCK", "UPGRADE", "MIGRATE", "DEFER_ARCHITECTURE"}
    allowed_execution_states = {"APPROVED", "DEFERRED", "REJECTED"}

    required_fields = (
        "Risk",
        "Decision",
        "Owner",
        "Consumers",
        "Execution state",
        "Evidence",
        "Rollback",
    )
    for row in rows:
        for field in required_fields:
            assert row[field], f"{row['ID']} missing {field}"
        assert row["Decision"] in allowed_decisions, f"{row['ID']} invalid decision"
        assert row["Execution state"] in allowed_execution_states, f"{row['ID']} not frozen"
        if "T4" in row["Risk"]:
            assert row["Execution state"] != "APPROVED", f"{row['ID']} T4 cannot be executable"
            assert row["Decision"] == "DEFER_ARCHITECTURE"

    bridges = next(row for row in rows if row["ID"] == "MOD-016")
    assert bridges["Risk"] == "T4"
    assert bridges["Decision"] == "DEFER_ARCHITECTURE"
    assert bridges["Execution state"] == "DEFERRED"


def test_technology_modernization_closeout_is_terminal_and_handoff_only() -> None:
    """Task 16 必须关闭全部技术现代化状态，并把 T4 仅作为后续评审输入。"""

    rows = _ledger_rows()
    terminal_statuses = {"VERIFIED", "DEFERRED", "REJECTED", "CLOSED_NO_CUTOVER"}
    for row in rows:
        assert row["Status"] in terminal_statuses, (
            f"{row['ID']} non-terminal status: {row['Status']}"
        )

    statuses = {row["ID"]: row["Status"] for row in rows}
    assert statuses["MOD-001"] == "CLOSED_NO_CUTOVER"
    assert statuses["MOD-012"] == "CLOSED_NO_CUTOVER"
    assert statuses["MOD-004"] == "VERIFIED"
    assert statuses["MOD-013"] == "VERIFIED"

    ledger = (MODERNIZATION / "modernization-ledger.md").read_text(encoding="utf-8")
    assert "MOD-001 remains `APPROVED / APPROVED`" not in ledger
    assert "MOD-012 remains `APPROVED / APPROVED`" not in ledger

    assert ARCHITECTURE_REVIEW_INPUT.is_file(), "missing architecture modernization review input"
    handoff = ARCHITECTURE_REVIEW_INPUT.read_text(encoding="utf-8")
    for row in rows:
        if "T4" in row["Risk"]:
            assert row["ID"] in handoff, f"missing T4 handoff for {row['ID']}"

    for recommendation in ("KEEP", "ASSESS TARGETED CHANGE", "ASSESS LARGER PROGRAM"):
        assert recommendation in handoff
    assert "evidence-only" in handoff.lower()
    assert "does not authorize implementation" in handoff.lower()
    assert "IMPLEMENTED" not in handoff

    root_readme = ROOT_README.read_text(encoding="utf-8")
    lifecycle = SUPERPOWERS_README.read_text(encoding="utf-8")
    assert "Next capability phase:** NOT YET DEFINED" in root_readme
    assert "Next capability phase — NOT YET DEFINED" in lifecycle
    assert "Technology Modernization — COMPLETED" in root_readme
    assert (
        "2026-09-13-dsp-modernization-design.md`]"
        "(specs/2026-09-13-dsp-modernization-design.md) | COMPLETED"
    ) in lifecycle
    assert (
        "2026-09-13-dsp-modernization.md`]"
        "(plans/2026-09-13-dsp-modernization.md) | COMPLETED"
    ) in lifecycle

    risk_register = (MODERNIZATION / "modernization-risk-register.md").read_text(encoding="utf-8")
    assert "Technology Modernization closeout: COMPLETED" in risk_register
    assert "architecture-modernization-review-input.md" in risk_register
