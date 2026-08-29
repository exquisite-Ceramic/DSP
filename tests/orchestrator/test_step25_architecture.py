from __future__ import annotations

from pathlib import Path


D6_SOURCE = Path(
    "platform/orchestrator/src/design_orchestrator/parameter_binder.py"
)


def test_step25_d6_module_exists_as_focused_orchestrator_boundary() -> None:
    assert D6_SOURCE.is_file()


def test_step25_d6_module_does_not_leak_host_or_provider_native_concepts() -> None:
    source = D6_SOURCE.read_text(encoding="utf-8").lower()

    forbidden = (
        "autocad",
        "revit",
        "tekla",
        "hostcommand",
        "providerbinding",
        "provider_tool",
        "provider_server",
        "elementid",
        "handle",
        "from host_contracts",
        "import host_contracts",
        "from autocad_sidecar",
        "import autocad_sidecar",
        "from semantic_runtime",
        "import semantic_runtime",
    )

    for token in forbidden:
        assert token not in source, f"Step25 D6 leaked forbidden concept: {token}"
