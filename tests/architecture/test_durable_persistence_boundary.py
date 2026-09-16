import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "platform" / "execution_reconciliation"


def test_execution_reconciliation_owns_postgres_dependency() -> None:
    data = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    deps = tuple(data["project"]["dependencies"])
    assert any(item.startswith("psycopg") for item in deps)


def test_domain_state_modules_do_not_import_psycopg() -> None:
    for name in ("saga_state_v2.py", "saga_contracts_v2.py", "saga_v2.py"):
        text = (PACKAGE / "src" / "design_execution_reconciliation" / name).read_text(
            encoding="utf-8"
        )
        assert "psycopg" not in text
