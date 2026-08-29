from pathlib import Path

import design_approval_scope
from design_approval_scope import ApprovalScopeBoundary, ExecutionSliceScopeRule

ROOT = (
    Path(__file__).resolve().parents[2]
    / "platform"
    / "approval_scope"
    / "src"
    / "design_approval_scope"
)


def test_public_api_is_explicitly_frozen():
    assert hasattr(design_approval_scope, "__all__")
    assert "ApprovalScopePlanner" in design_approval_scope.__all__
    assert "bind_changeset" in design_approval_scope.__all__


def test_step28_source_has_no_host_provider_or_legacy_changeset_leakage():
    source = "\n".join(path.read_text() for path in ROOT.glob("*.py"))
    forbidden = (
        "design_orchestrator",
        "HostCommand",
        "platform.changeset",
        "AutoCAD",
        "Revit",
        "Tekla",
        "provider_tool",
        "native_id",
        "ApprovalRecord",
        "ExecutionGrant",
        "PolicySnapshot",
    )
    for token in forbidden:
        assert token not in source


def test_public_contract_has_no_future_execution_slice_id():
    assert "execution_slice_id" not in ExecutionSliceScopeRule.__dataclass_fields__
    assert "execution_slice_id" not in ApprovalScopeBoundary.__dataclass_fields__
