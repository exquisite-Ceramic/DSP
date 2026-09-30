"""Task 9 diagnostic：探测 ContextSnapshot 后 composition rebuild 的真实 fail-closed 边界。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from design_orchestrator import WorkflowPhase, WorkflowResumeCommand
from design_product_runtime import ProductFlowStatus


def _load_product_runtime_acceptance_helpers():
    """复用现有 Product Runtime acceptance fixture，不复制第二套 composition 测试基础设施。"""

    helper_path = (
        Path(__file__).resolve().parents[1] / "product_runtime" / "conftest.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_task9_product_runtime_acceptance_helpers",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _postgres_dsn() -> str:
    """probe 只在显式 PostgreSQL 17 lane 运行。"""

    import os

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def test_context_snapshot_pause_rebuild_fails_closed_without_host_mutation() -> None:
    """销毁首个 composition 后，新 SnapshotRegistry 不得把 durable pause 猜成可恢复。"""

    helpers = _load_product_runtime_acceptance_helpers()
    dsn = _postgres_dsn()
    task_id = "task-front-door-context-restart-probe"
    first = helpers._build_reference_case(
        dsn,
        task_id,
        reset_schema=True,
    )
    host = first.host
    request = first.request
    try:
        proposal = first.flow.submit(request)
        assert proposal.status is ProductFlowStatus.WAITING
        assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        pending = proposal.checkpoint.pending_interaction
        assert pending is not None
        context_ref = proposal.checkpoint.context_snapshot_ref
        assert context_ref is not None
        snapshot = first.snapshot_registry.get_snapshot(context_ref.ref_id)
        assert snapshot.hash == context_ref.content_hash
        assert host.execute_count == 0
        command = WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            pause_id=pending.pause_id,
        )
    finally:
        helpers._close_case(first)

    rebuilt = helpers._build_reference_case(
        dsn,
        task_id,
        reset_schema=False,
        host=host,
        request=request,
    )
    try:
        restored = rebuilt.flow.get(task_id)
        assert restored is not None
        assert restored.status is ProductFlowStatus.WAITING
        assert restored.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert restored.checkpoint.context_snapshot_ref == context_ref
        assert host.execute_count == 0

        with pytest.raises(Exception) as captured:
            rebuilt.flow.resume(task_id, command)

        print(
            "TASK9_RESTART_ERROR",
            type(captured.value).__module__,
            type(captured.value).__name__,
            getattr(captured.value, "code", None),
            str(captured.value),
        )
        assert host.execute_count == 0
    finally:
        helpers._close_case(rebuilt)
