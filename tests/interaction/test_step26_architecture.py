from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
INTERACTION_PACKAGE = ROOT / "platform" / "interaction" / "src" / "design_interaction"


def test_interaction_core_exists_as_standalone_platform_package() -> None:
    assert (INTERACTION_PACKAGE / "contracts.py").is_file()
    assert (INTERACTION_PACKAGE / "coordinator.py").is_file()
    assert (INTERACTION_PACKAGE / "__init__.py").is_file()


def test_interaction_core_does_not_import_host_product_packages() -> None:
    forbidden = re.compile(
        r"^\s*(?:from|import)\s+.*(?:autocad|autodesk|revit|tekla)",
        flags=re.IGNORECASE | re.MULTILINE,
    )

    for path in INTERACTION_PACKAGE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert forbidden.search(text) is None, f"Host product import leaked into {path}"
