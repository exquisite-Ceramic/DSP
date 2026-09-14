from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODERNIZATION = ROOT / "docs" / "superpowers" / "modernization"


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
