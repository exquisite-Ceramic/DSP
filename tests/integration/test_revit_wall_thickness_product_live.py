"""Task 10：真实 Revit Product Vertical mandatory live acceptance。"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest
from design_execution_planning import (
    MaterializationRoutingEvidence,
    MaterializationRuntimeRoute,
    compute_materialization_routing_hash,
)
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    SliceReconciliationStatusV2,
)
from design_orchestrator import WorkflowPhase, WorkflowResumeCommand
from design_product_runtime import ProductFlowStatus
from design_provider_binding import (
    compute_host_binding_fingerprint,
    compute_provider_snapshot_hash_v2,
)
from host_contracts import HostCommand
from revit_sidecar.named_pipe import NamedPipeTransport

from tests.integration.test_phase_h_revit_wall_thickness_live import _load_fixture_manifest
from tests.orchestrator import test_real_owner_workflow_end_to_end as _owner_support
from tests.product_runtime import conftest as _product_support


REPO_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED_LIVE_ENV = (
    "DSP_REVIT_VERSION",
    "DSP_REVIT_TFM",
    "DSP_REVIT_API_DIR",
    "DSP_REVIT_PIPE",
    "DSP_REVIT_FIXTURE",
    "DSP_TEST_POSTGRES_DSN",
)


def _live_skip_reason() -> str | None:
    """默认 CI 只能收集并 SKIP；只有显式 live switch 才允许触碰真实 Revit。"""

    if os.environ.get("DSP_REVIT_LIVE") != "1":
        return "set DSP_REVIT_LIVE=1 to run the real Revit product acceptance gate"
    missing = tuple(name for name in _REQUIRED_LIVE_ENV if not os.environ.get(name))
    if missing:
        return "missing live Revit product environment: " + ", ".join(missing)
    return None


_LIVE_SKIP_REASON = _live_skip_reason()
pytestmark = pytest.mark.skipif(
    _LIVE_SKIP_REASON is not None,
    reason=_LIVE_SKIP_REASON or "live Revit product gate disabled",
)


class _RecordingNamedPipeTransport:
    """只记录真实 named-pipe I/O；所有响应仍来自正在运行的 Revit AgentHost。"""

    def __init__(self, pipe_name: str) -> None:
        self._inner = NamedPipeTransport(pipe_name=pipe_name)
        self.calls: list[tuple[HostCommand, dict]] = []
        self.current_revision = 0

    def request(self, command: HostCommand) -> dict:
        """原样委托真实 transport，并维护 RevisionBarrier 可读取的最新 Host revision。"""

        response = self._inner.request(command)
        self.calls.append((command, response))
        revision = response.get("revision_after")
        if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0:
            self.current_revision = revision
        return response


def _discover_live_context(
    transport: _RecordingNamedPipeTransport,
    fixture_path: Path,
) -> tuple[str, str, int, tuple[Mapping[str, object], ...]]:
    """先只读发现真实 document/runtime/selection，绝不通过产品 request 注入模型身份。"""

    response = transport.request(
        HostCommand(
            command_id=f"CMD-T10-DISCOVER-{uuid.uuid4().hex}",
            document_id=str(fixture_path),
            mode="READ",
            operation="context.current_selection",
            target_native_refs=[],
            arguments={},
            preconditions=[],
            idempotency_key=None,
        )
    )
    assert response["status"] == "OK"
    payload = response["payload"]
    assert isinstance(payload, Mapping)

    document_id = payload["document_id"]
    host_instance_id = payload["host_instance_id"]
    selected_elements = payload["selected_elements"]
    revision = response["revision_after"]
    assert isinstance(document_id, str) and document_id.strip()
    assert isinstance(host_instance_id, str) and host_instance_id.strip()
    assert isinstance(selected_elements, list)
    assert isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0
    return (
        document_id.strip(),
        host_instance_id.strip(),
        revision,
        tuple(selected_elements),
    )


def _patch_live_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    document_id: str,
    host_instance_id: str,
    wall_unique_id: str,
) -> None:
    """把 Task 9 已审查 composition 的环境 evidence seam 绑定到本次真实 Revit 身份。"""

    monkeypatch.setattr(_product_support, "_DOCUMENT_REF", document_id)
    monkeypatch.setattr(_product_support, "_HOST_INSTANCE_ID", host_instance_id)
    monkeypatch.setattr(_product_support, "_WALL_UNIQUE_ID", wall_unique_id)
    monkeypatch.setattr(_owner_support, "_DOCUMENT_REF", document_id)

    class _LiveMaterializationRoutingBoundary(
        _owner_support._MaterializationRoutingBoundary
    ):
        """仅替换 runtime identity；routing hash 仍按 production contract 重算。"""

        def routing_evidence(self, materialization_plan, topology_snapshot):
            base = super().routing_evidence(materialization_plan, topology_snapshot)
            routes = tuple(
                MaterializationRuntimeRoute(
                    materialization_id=route.materialization_id,
                    host_runtime_ref=replace(
                        route.host_runtime_ref,
                        host_instance_id=host_instance_id,
                    ),
                )
                for route in base.routes
            )
            return MaterializationRoutingEvidence(
                routing_snapshot_id=base.routing_snapshot_id,
                routes=routes,
                routing_snapshot_hash=compute_materialization_routing_hash(routes),
            )

    class _LiveProviderExecutionSnapshotBoundary(
        _owner_support._ProviderExecutionSnapshotBoundary
    ):
        """仅把 reviewed provider runtime evidence 的 native target 换成真实 Wall.UniqueId。"""

        def __call__(self, execution_slice):
            base = super().__call__(execution_slice)
            old_target = base.native_target_bindings[0]
            unsigned_target = replace(
                old_target,
                native_id=wall_unique_id,
                host_binding_fingerprint="0" * 64,
            )
            target = replace(
                unsigned_target,
                host_binding_fingerprint=compute_host_binding_fingerprint(unsigned_target),
            )
            candidate = base.provider_candidates[0]
            old_material = base.candidate_binding_materials[
                candidate.candidate_fingerprint
            ]
            provider_arguments = dict(old_material.provider_arguments)
            provider_arguments["native_ids"] = [wall_unique_id]
            material = replace(
                old_material,
                native_targets=(target,),
                provider_arguments=provider_arguments,
            )
            unsigned_snapshot = replace(
                base,
                host_runtime_ref=execution_slice.host_runtime_ref,
                native_target_bindings=(target,),
                candidate_binding_materials={
                    candidate.candidate_fingerprint: material,
                },
                snapshot_hash="0" * 64,
            )
            return replace(
                unsigned_snapshot,
                snapshot_hash=compute_provider_snapshot_hash_v2(unsigned_snapshot),
            )

    monkeypatch.setattr(
        _product_support,
        "_MaterializationRoutingBoundary",
        _LiveMaterializationRoutingBoundary,
    )
    monkeypatch.setattr(
        _product_support,
        "_ProviderExecutionSnapshotBoundary",
        _LiveProviderExecutionSnapshotBoundary,
    )


def _accept_command(proposal) -> WorkflowResumeCommand:
    """接受当前 durable operation proposal，保留原 pause identity。"""

    assert proposal.checkpoint.pending_interaction is not None
    return WorkflowResumeCommand(
        resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        pause_id=proposal.checkpoint.pending_interaction.pause_id,
    )


def _git_head() -> str:
    """记录本次 live evidence 实际运行的 exact repository HEAD。"""

    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def test_revit_wall_thickness_product_live_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 ProductFlow 必须经完整 owner 链完成一次 300mm commit 与独立 READ 证明。"""

    if os.name != "nt":
        pytest.fail("DSP_REVIT_LIVE=1 requires the pinned Windows/Revit acceptance machine")

    fixture_path = Path(os.environ["DSP_REVIT_FIXTURE"]).resolve()
    manifest = _load_fixture_manifest(fixture_path)
    isolated_wall = manifest["isolated_wall_unique_id"]
    transport = _RecordingNamedPipeTransport(os.environ["DSP_REVIT_PIPE"])

    document_id, host_instance_id, baseline_revision, selected = _discover_live_context(
        transport,
        fixture_path,
    )
    assert Path(document_id).resolve() == fixture_path
    assert len(selected) == 1
    assert selected[0]["unique_id"] == isolated_wall
    assert selected[0]["native_kind"] == "Wall"

    _patch_live_environment(
        monkeypatch,
        document_id=document_id,
        host_instance_id=host_instance_id,
        wall_unique_id=isolated_wall,
    )

    task_id = f"task-revit-product-live-{uuid.uuid4().hex}"
    case = _product_support._compose_case(
        os.environ["DSP_TEST_POSTGRES_DSN"],
        task_id,
        reset_schema=True,
        host=transport,
    )
    try:
        proposal = case.flow.submit(case.request)
        assert proposal.status is ProductFlowStatus.WAITING
        assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert proposal.checkpoint.context_snapshot_ref is not None
        assert proposal.checkpoint.operation_ref is not None

        durable_request = case.request_store.get(task_id)
        assert durable_request is not None
        assert durable_request.request_hash == case.request.request_hash
        assert durable_request.intent_arguments == {
            "thickness": {"value": 300.0, "unit": "mm"}
        }

        completed = case.flow.resume(task_id, _accept_command(proposal))
        assert completed.status is ProductFlowStatus.SUCCEEDED
        assert completed.workflow_phase is WorkflowPhase.COMPLETED
        assert completed.saga_id is not None

        execute_calls = [
            (index, command, response)
            for index, (command, response) in enumerate(transport.calls)
            if command.operation == "set_wall_thickness"
        ]
        assert len(execute_calls) == 1
        execute_index, execute_command, execute_response = execute_calls[0]
        assert execute_command.mode == "EXECUTE"
        assert execute_command.document_id == document_id
        assert len(execute_command.target_native_refs) == 1
        assert execute_command.target_native_refs[0].native_id == isolated_wall
        assert execute_command.arguments["thickness"] == {"value": 300.0, "unit": "mm"}
        assert execute_command.preconditions == [{"revision": baseline_revision}]
        assert execute_response["status"] == "OK"

        committed_revision = execute_response["revision_after"]
        assert committed_revision == baseline_revision + 1

        post_commit_reads = [
            (index, command, response)
            for index, (command, response) in enumerate(transport.calls)
            if index > execute_index and command.operation == "read_wall_thickness_snapshot"
        ]
        assert len(post_commit_reads) == 1
        _, read_command, read_response = post_commit_reads[0]
        assert read_command.mode == "READ"
        assert read_command.document_id == document_id
        assert len(read_command.target_native_refs) == 1
        assert read_command.target_native_refs[0].native_id == isolated_wall
        assert read_command.idempotency_key is None

        read_payload = read_response["payload"]
        assert read_response["status"] == "OK"
        assert read_response["revision_after"] == committed_revision
        assert read_payload["document_id"] == document_id
        assert read_payload["host_instance_id"] == host_instance_id
        assert read_payload["wall_unique_id"] == isolated_wall
        assert read_payload["revision_before"] == committed_revision
        assert read_payload["revision_after"] == committed_revision
        assert read_payload["wall_thickness_mm"] == pytest.approx(300.0, abs=1e-6)

        saga = case.saga_store.get_saga(completed.saga_id)
        assert saga is not None
        assert saga.status is ExecutionSagaStatusV2.SUCCEEDED
        assert len(saga.slice_states) == 1
        slice_state = saga.slice_states[0]
        assert slice_state.status is SliceReconciliationStatusV2.SUCCEEDED
        assert slice_state.actual_delta_hash is not None
        assert slice_state.scope_comparison_hash is not None
        assert slice_state.verification_hash is not None
        assert saga.convergence_result_hash is not None

        reread = case.flow.get(task_id)
        assert reread is not None
        assert reread.status is ProductFlowStatus.SUCCEEDED
        assert reread.saga_id == completed.saga_id

        print(
            json.dumps(
                {
                    "task_id": task_id,
                    "request_hash": case.request.request_hash,
                    "context_snapshot_ref": proposal.checkpoint.context_snapshot_ref.ref_id,
                    "context_snapshot_hash": proposal.checkpoint.context_snapshot_ref.content_hash,
                    "operation_space_ref": proposal.checkpoint.operation_ref.ref_id,
                    "operation_space_hash": proposal.checkpoint.operation_ref.content_hash,
                    "bound_operation_ref": (
                        completed.checkpoint.operation_ref.ref_id
                        if completed.checkpoint.operation_ref is not None
                        else None
                    ),
                    "changeset_ref": (
                        completed.checkpoint.changeset_ref.ref_id
                        if completed.checkpoint.changeset_ref is not None
                        else None
                    ),
                    "approval_ref": (
                        completed.checkpoint.approval_ref.ref_id
                        if completed.checkpoint.approval_ref is not None
                        else None
                    ),
                    "execution_plan_ref": (
                        completed.checkpoint.execution_plan_ref.ref_id
                        if completed.checkpoint.execution_plan_ref is not None
                        else None
                    ),
                    "saga_id": completed.saga_id,
                    "host_instance_id": host_instance_id,
                    "document_id": document_id,
                    "wall_unique_id": isolated_wall,
                    "fixture_sha256": manifest["rvt_sha256"],
                    "revision_before": baseline_revision,
                    "revision_after": committed_revision,
                    "independent_read_command_id": read_command.command_id,
                    "independent_read_revision_before": read_payload["revision_before"],
                    "independent_read_revision_after": read_payload["revision_after"],
                    "measured_width_mm": read_payload["wall_thickness_mm"],
                    "verification_hash": slice_state.verification_hash,
                    "convergence_result_hash": saga.convergence_result_hash,
                    "product_status": completed.status.value,
                    "saga_status": saga.status.value,
                    "revit_version": os.environ["DSP_REVIT_VERSION"],
                    "revit_tfm": os.environ["DSP_REVIT_TFM"],
                    "revit_api_dir": os.environ["DSP_REVIT_API_DIR"],
                    "pipe": os.environ["DSP_REVIT_PIPE"],
                    "exact_head": _git_head(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    finally:
        _product_support._close_case(case)


def test_revit_wall_thickness_product_live_negative_evidence_limitation() -> None:
    """明确记录本 harness 没有 deterministic external-change injection seam，不伪造 live negative。"""

    pytest.skip(
        "NOT_RUN_ENVIRONMENT_LIMITATION: current pinned Revit harness has no reviewed "
        "deterministic external-change injection seam; Task 9 offline negatives "
        "remain mandatory"
    )
