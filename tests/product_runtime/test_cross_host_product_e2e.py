"""Task 15：Cross-Host Product Vertical real-owner E2E acceptance。"""

from __future__ import annotations

from design_product_runtime.revit_semantics import RevitWallThicknessSemanticBoundary
from semantic_runtime import HostBinding, IdentityRegistry

from tests.execution_coordination._materialized_support import materialized_fixture
from tests.product_runtime.test_product_task_query_v2 import _accepted


class _V2AcceptedReader:
    """只暴露 server-owned V2 accepted input；禁止测试回退到 V1 request。"""

    def __init__(self) -> None:
        self.accepted = _accepted(materialized_fixture().ctx)

    def get_v2(self, task_id: str):
        """按 exact task 返回 V2 accepted input。"""

        assert task_id == self.accepted.request.task_id
        return self.accepted

    def get(self, task_id: str):
        """V2 semantic path 若尝试 V1 request reader，立即暴露 authority 回退。"""

        raise AssertionError(f"V2 semantic path must not use V1 request reader: {task_id}")


class _ContextReader:
    """外部 Host transport double；只返回当前 Revit selection evidence。"""

    def __init__(self, native_target_id: str) -> None:
        """冻结本测试从 accepted binding 取得的 exact Revit native target。"""

        self._native_target_id = native_target_id

    def read(
        self,
        *,
        command_id: str,
        document_id: str,
        host_instance_id: str,
    ):
        """返回 production semantic boundary 所需的 Revit context observation。"""

        from revit_sidecar import RevitContextObservation, RevitSelectedElement

        assert command_id
        return RevitContextObservation(
            document_id=document_id,
            document_title="Cross-Host Task 15",
            host_instance_id=host_instance_id,
            revision=41,
            selected_elements=(
                RevitSelectedElement(
                    unique_id=self._native_target_id,
                    native_kind="Wall",
                ),
            ),
        )


def test_v2_accepted_input_enters_real_revit_semantic_boundary_without_v1_rewrite() -> None:
    """V2 request hash/session/project 必须原样参与 Revit context identity。"""

    accepted_reader = _V2AcceptedReader()
    request = accepted_reader.accepted.request
    binding = accepted_reader.accepted.session_binding_payload
    revit = next(
        item for item in binding["members"] if item["host_kind"] == "REVIT"
    )
    identities = IdentityRegistry()
    identities.ensure_identity(binding["semantic_target_id"])
    identities.bind_host(
        HostBinding(
            semantic_id=binding["semantic_target_id"],
            host_type="revit",
            document_id=revit["document_id"],
            native_id=revit["native_target_id"],
            native_kind="Wall",
        )
    )
    boundary = RevitWallThicknessSemanticBoundary(
        request_store=accepted_reader,
        context_reader=_ContextReader(revit["native_target_id"]),
        identity_registry=identities,
        session_ref=request.session_ref,
        document_id=revit["document_id"],
        host_instance_id=revit["host_instance_id"],
    )

    context_ref = boundary.resolve_host_context(request.task_id)
    inputs = boundary.load_context_inputs(context_ref)

    assert inputs.task_id == request.task_id
    assert inputs.project_id == request.project_id
    assert inputs.document_ref == revit["document_id"]
    assert context_ref.content_hash is not None



class _EvidencePort:
    """只记录 evidence router 委托；不执行 Host I/O。"""

    def __init__(self, label: str) -> None:
        self.label = label
        self.bundle_calls = []
        self.evidence_calls = []

    def build_bundle(self, **kwargs):
        """返回可辨认 sentinel，证明 exact runtime 路由。"""

        self.bundle_calls.append(kwargs)
        return ("bundle", self.label)

    def build_evidence(self, **kwargs):
        """返回可辨认 sentinel，证明 convergence evidence 也走同一 exact route。"""

        self.evidence_calls.append(kwargs)
        return ("evidence", self.label)


def test_cross_host_evidence_router_delegates_by_exact_runtime_without_host_io() -> None:
    """coordinator 的单 evidence seam 必须安全路由到两个 production adapter。"""

    from design_execution_planning import HostRuntimeRef
    from design_product_runtime.cross_host_reference_composition import (
        CrossHostVerificationEvidenceRouter,
    )

    autocad_runtime = HostRuntimeRef("autocad", "AUTOCAD-E2E", "DOC-A")
    revit_runtime = HostRuntimeRef("revit", "REVIT-E2E", "DOC-R")
    autocad = _EvidencePort("autocad")
    revit = _EvidencePort("revit")
    router = CrossHostVerificationEvidenceRouter(
        (
            (autocad_runtime, autocad),
            (revit_runtime, revit),
        )
    )

    class _Slice:
        def __init__(self, runtime_ref) -> None:
            self.host_runtime_ref = runtime_ref

    auto_slice = _Slice(autocad_runtime)
    revit_slice = _Slice(revit_runtime)

    assert router.build_bundle(execution_slice=auto_slice, marker="a") == (
        "bundle",
        "autocad",
    )
    assert router.build_bundle(execution_slice=revit_slice, marker="r") == (
        "bundle",
        "revit",
    )
    assert router.build_evidence(execution_slice=auto_slice, marker="a") == (
        "evidence",
        "autocad",
    )
    assert router.build_evidence(execution_slice=revit_slice, marker="r") == (
        "evidence",
        "revit",
    )
    assert len(autocad.bundle_calls) == 1
    assert len(revit.bundle_calls) == 1
    assert len(autocad.evidence_calls) == 1
    assert len(revit.evidence_calls) == 1


def test_cross_host_evidence_router_rejects_unconfigured_exact_runtime() -> None:
    """同 host type 但 instance/document 不同也不得 fuzzy resolve。"""

    import pytest
    from design_execution_planning import HostRuntimeRef
    from design_product_runtime.cross_host_reference_composition import (
        CrossHostVerificationEvidenceRouter,
    )

    configured = HostRuntimeRef("revit", "REVIT-E2E", "DOC-R")
    router = CrossHostVerificationEvidenceRouter(
        ((configured, _EvidencePort("revit")),)
    )

    class _Slice:
        host_runtime_ref = HostRuntimeRef("revit", "REVIT-E2E", "OTHER-DOC")

    with pytest.raises(
        ValueError,
        match="PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED",
    ):
        router.build_bundle(execution_slice=_Slice())



class _Task15Clock:
    """为 coordinator/Host adapters 提供单调、确定的 canonical UTC 审计时间。"""

    def __init__(self) -> None:
        self._sequence = 0

    def now(self) -> str:
        """每次调用推进一秒；时间只用于审计，不参与业务 authority。"""

        self._sequence += 1
        return f"2026-10-07T07:00:{self._sequence:02d}Z"


class _Task15AutoCadDispatcher:
    """只模拟 AutoCAD 外部 dispatcher I/O；平台 adapters 全部使用 production。"""

    def __init__(
        self,
        *,
        host_instance_id: str,
        document_id: str,
        native_id: str,
        revision: int,
        events: list[str],
    ) -> None:
        self.host_instance_id = host_instance_id
        self.document_id = document_id
        self.native_id = native_id
        self.revision = revision
        self.width_mm = 200.0
        self.events = events
        self.execute_count = 0
        self.read_count = 0

    async def extract_design_facts(self, handles):
        """readiness 与 verification 都通过同一个真实 normalized-fact surface。"""

        from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter

        assert tuple(handles) == (self.native_id,)
        self.read_count += 1
        self.events.append(
            f"autocad.read:{self.revision}:{self.width_mm}"
        )
        return DesignFactAdapter().normalize_snapshot(
            {
                "hostInstanceId": self.host_instance_id,
                "documentId": self.document_id,
                "revision": self.revision,
                "entities": [
                    {
                        "nativeId": self.native_id,
                        "nativeKind": "LWPOLYLINE",
                        "layer": "A-WALL",
                        "properties": {
                            "constantWidth": {
                                "value": self.width_mm,
                                "unit": "mm",
                            }
                        },
                    }
                ],
            }
        )

    async def set_wall_thickness(
        self,
        handles,
        thickness_mm,
        *,
        idempotency_key,
        revision,
    ):
        """模拟一次 exact logical commit，并返回 public HostCommandResult。"""

        from host_contracts import HostCommandResult

        assert tuple(handles) == (self.native_id,)
        assert idempotency_key
        assert revision == self.revision
        before = self.width_mm
        self.execute_count += 1
        self.events.append("autocad.execute")
        self.width_mm = float(thickness_mm)
        self.revision += 1
        return HostCommandResult(
            command_id="TASK15-AUTOCAD-COMMIT",
            status="OK",
            payload={
                "updated": 1,
                "beforeWidths": {self.native_id: before},
                "widths": {self.native_id: self.width_mm},
                "unit": "mm",
            },
            revision_after=self.revision,
        )


class _Task15RevitTransport:
    """只模拟 Revit named-pipe I/O；readiness/execution/snapshot adapters 保持 production。"""

    def __init__(
        self,
        *,
        host_instance_id: str,
        document_id: str,
        native_id: str,
        revision: int,
        events: list[str],
    ) -> None:
        self.host_instance_id = host_instance_id
        self.document_id = document_id
        self.native_id = native_id
        self.revision = revision
        self.width_mm = 200.0
        self.events = events
        self.execute_count = 0
        self.snapshot_read_count = 0

    def request(self, command):
        """按 public HostCommand operation 返回严格、可关联的 Host evidence。"""

        assert command.document_id == self.document_id
        assert command.target_native_refs[0].native_id == self.native_id
        if command.operation == "check_wall_thickness_readiness":
            self.events.append(f"revit.readiness:{self.revision}")
            return {
                "status": "OK",
                "revision_after": self.revision,
                "payload": {
                    "document_id": self.document_id,
                    "wall_unique_id": self.native_id,
                    "current_width": {"value": self.width_mm, "unit": "mm"},
                    "isolation_ready": True,
                    "plan_ready": True,
                },
            }
        if command.operation == "set_wall_thickness":
            expected_revision = command.preconditions[0]["revision"]
            assert expected_revision == self.revision
            before_revision = self.revision
            self.execute_count += 1
            self.events.append("revit.execute")
            self.width_mm = float(command.arguments["thickness"]["value"])
            self.revision += 1
            return {
                "command_id": command.command_id,
                "status": "OK",
                "revision_after": self.revision,
                "payload": {
                    "wall_unique_id": self.native_id,
                    "wall_type_unique_id": "TASK15-REVIT-WALL-TYPE",
                    "editable_layer_index": 1,
                    "width_before_internal": 200.0 / 304.8,
                    "width_after_internal": self.width_mm / 304.8,
                    "width_after_mm": self.width_mm,
                    "requested_width_mm": self.width_mm,
                    "transaction_attempt_count": 1,
                },
                "verification": {
                    "identity_invariant_proven": True,
                    "location_invariant_proven": True,
                    "relationship_invariant_proven": True,
                    "document_change_observed": True,
                    "revision_before": before_revision,
                    "revision_after": self.revision,
                    "normalized_wider_effects": [],
                },
                "replayed": False,
            }
        if command.operation == "read_wall_thickness_snapshot":
            self.snapshot_read_count += 1
            self.events.append(
                f"revit.read:{self.revision}:{self.width_mm}"
            )
            return {
                "status": "OK",
                "revision_after": self.revision,
                "payload": {
                    "document_id": self.document_id,
                    "host_instance_id": self.host_instance_id,
                    "wall_unique_id": self.native_id,
                    "wall_type_unique_id": "TASK15-REVIT-WALL-TYPE",
                    "native_kind": "Wall",
                    "builtin_category": "OST_Walls",
                    "wall_thickness_mm": self.width_mm,
                    "location_signature": "TASK15-LOCATION",
                    "relationship_signature": "TASK15-RELATIONSHIP",
                    "revision_before": self.revision,
                    "revision_after": self.revision,
                },
            }
        raise AssertionError(f"unexpected Revit Task 15 operation: {command.operation}")


def test_cross_host_product_happy_path_one_task_one_saga_two_reads_300_converged() -> None:
    """真实双 Host adapters 必须形成一个 Saga、两个独立 300mm READ 与离线 V2 GET。"""

    from autocad_sidecar.execution.wall_thickness_read import (
        AutoCadWallThicknessFactReadPort,
    )
    from design_convergence import CrossHostConvergenceVerifier
    from design_execution_coordination import (
        CrossHostReadinessBarrier,
        MaterializedCoordinationStatus,
        MaterializedExecutionSagaCoordinator,
    )
    from design_execution_reconciliation import (
        ExecutionReconciliationServiceV2,
        ExecutionSagaStatusV2,
        SagaConvergenceOutcome,
    )
    from design_execution_reconciliation.postgres_dispatch_intent import (
        PostgresHostDispatchIntentStore,
    )
    from design_execution_reconciliation.postgres_evidence import (
        PostgresReconciliationEvidenceStore,
    )
    from design_execution_reconciliation.postgres_saga_store_v2 import (
        PostgresExecutionSagaStoreV2,
    )
    from design_impact import SemanticEnvironmentBinding
    from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
    from design_orchestrator.langgraph_checkpoint_reader import (
        LangGraphWorkflowCheckpointReader,
    )
    from design_orchestrator.proposal_decision_postgres import (
        PostgresProposalDecisionStore,
    )
    from design_orchestrator.workflow_contracts import StableRef
    from design_product_runtime import (
        AutoCadWallThicknessVerificationEvidencePort,
        CrossHostRuntimePortBinding,
        CrossHostVerificationEvidenceRouter,
        ProductTaskQueryService,
        ProductTaskRequestV2,
        RevitWallThicknessVerificationEvidencePort,
        build_autocad_wall_thickness_runtime_binding,
        build_cross_host_runtime_registries,
        create_postgres_product_task_request_store,
    )
    from design_product_runtime.revit_reference_composition import (
        _semantic_environment,
    )
    from revit_sidecar import (
        RevitWallThicknessExecutionPort,
        RevitWallThicknessReadinessPort,
        RevitWallThicknessSnapshotReadPort,
    )
    from revit_sidecar.design_fact_adapter import DesignFactAdapter as RevitDesignFactAdapter

    from tests.product_runtime.conftest import build_cross_host_task15_lineage
    from tests.product_runtime.test_cross_host_product_query import (
        _binding,
        _binding_payload,
        _dsn,
        _persist_completed_checkpoint,
        _reset_and_migrate,
    )

    dsn = _dsn()
    _reset_and_migrate(dsn)
    semantic_service, semantic_environment = _semantic_environment()
    ctx = build_cross_host_task15_lineage(
        semantic_environment=SemanticEnvironmentBinding(
            semantic_environment.environment_id,
            semantic_environment.content_hash,
        )
    )
    slices = {
        item.host_runtime_ref.host_type: item
        for item in ctx.execution_plan.execution_slices
    }
    bindings = {
        item.bindings[0].host_runtime_ref.host_type: item
        for item in ctx.binding_sets
    }
    assert tuple(
        item.host_runtime_ref.host_type
        for item in ctx.execution_plan.execution_slices
    ) == ("autocad", "revit")

    events: list[str] = []
    auto_binding = bindings["autocad"].bindings[0]
    revit_binding = bindings["revit"].bindings[0]
    autocad = _Task15AutoCadDispatcher(
        host_instance_id=slices["autocad"].host_runtime_ref.host_instance_id,
        document_id=slices["autocad"].host_runtime_ref.document_ref,
        native_id=auto_binding.native_targets[0].native_id,
        revision=auto_binding.native_binding_metadata["expected_revision"],
        events=events,
    )
    revit = _Task15RevitTransport(
        host_instance_id=slices["revit"].host_runtime_ref.host_instance_id,
        document_id=slices["revit"].host_runtime_ref.document_ref,
        native_id=revit_binding.native_targets[0].native_id,
        revision=revit_binding.native_binding_metadata["expected_revision"],
        events=events,
    )
    clock = _Task15Clock()
    runtime_registries = build_cross_host_runtime_registries(
        (
            build_autocad_wall_thickness_runtime_binding(
                slices["autocad"].host_runtime_ref,
                autocad,
                clock=clock.now,
            ),
            CrossHostRuntimePortBinding(
                runtime_ref=slices["revit"].host_runtime_ref,
                readiness_port=RevitWallThicknessReadinessPort(revit),
                execution_port=RevitWallThicknessExecutionPort(
                    revit,
                    clock=clock.now,
                ),
            ),
        )
    )
    evidence_router = CrossHostVerificationEvidenceRouter(
        (
            (
                slices["autocad"].host_runtime_ref,
                AutoCadWallThicknessVerificationEvidencePort(
                    fact_reader=AutoCadWallThicknessFactReadPort(autocad),
                    semantic_service=semantic_service,
                    semantic_environment=semantic_environment,
                ),
            ),
            (
                slices["revit"].host_runtime_ref,
                RevitWallThicknessVerificationEvidencePort(
                    snapshot_reader=RevitWallThicknessSnapshotReadPort(revit),
                    design_fact_adapter=RevitDesignFactAdapter(),
                    semantic_service=semantic_service,
                    semantic_environment=semantic_environment,
                ),
            ),
        )
    )

    saga_store = PostgresExecutionSagaStoreV2(dsn)
    dispatch_store = PostgresHostDispatchIntentStore(dsn)
    evidence_store = PostgresReconciliationEvidenceStore(dsn)
    request_store = create_postgres_product_task_request_store(dsn)
    decision_store = PostgresProposalDecisionStore(dsn)
    saver = create_postgres_checkpointer(dsn)
    try:
        reconciliation = ExecutionReconciliationServiceV2(
            store=saga_store,
            evidence_store=evidence_store,
        )
        coordinator = MaterializedExecutionSagaCoordinator(
            readiness_barrier=CrossHostReadinessBarrier(
                runtime_registries.readiness
            ),
            reconciliation=reconciliation,
            host_registry=runtime_registries.execution,
            dispatch_intents=dispatch_store,
            evidence_port=evidence_router,
            convergence_verifier=CrossHostConvergenceVerifier(),
            clock=clock,
        )
        result = coordinator.execute(
            ctx.case.changeset,
            ctx.case.boundary_v2,
            ctx.materialization_plan,
            ctx.execution_plan,
            ctx.binding_sets,
            ctx.authorities,
            ctx.case.profile,
        )

        assert result.status is MaterializedCoordinationStatus.SUCCEEDED
        stored = saga_store.get_saga(result.saga_id)
        assert stored is not None
        assert stored.status is ExecutionSagaStatusV2.SUCCEEDED
        assert stored.convergence_outcome is SagaConvergenceOutcome.CONVERGED
        assert autocad.execute_count == 1
        assert revit.execute_count == 1
        assert autocad.read_count == 2
        assert revit.snapshot_read_count == 1
        assert [event for event in events if event.endswith(".execute")] == [
            "autocad.execute",
            "revit.execute",
        ]
        assert events.index("autocad.execute") < events.index(
            "autocad.read:12:300.0"
        )
        assert events.index("revit.execute") < events.index(
            "revit.read:13:300.0"
        )

        binding = _binding(ctx)
        request = ProductTaskRequestV2.create(
            task_id=ctx.case.changeset.task_id,
            project_id=ctx.project_id,
            initiating_host_kind="REVIT",
            session_ref=binding.session_ref,
            session_binding_hash=binding.binding_hash,
            requested_action="SET_BOUND_WALL_THICKNESS",
            intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
        )
        request_store.create_v2(
            request,
            session_binding_hash=binding.binding_hash,
            session_binding_payload=_binding_payload(binding),
        )
        decision_store.claim_accept(
            request.task_id,
            "pause-task15-happy",
            StableRef("subject-task15-happy", "d" * 64),
        )
        _persist_completed_checkpoint(
            saver,
            task_id=request.task_id,
            saga_id=result.saga_id,
        )

        query = ProductTaskQueryService(
            request_store=request_store,
            checkpoint_reader=LangGraphWorkflowCheckpointReader(
                checkpointer=saver
            ),
            saga_store=saga_store,
            proposal_decision_reader=decision_store,
            dispatch_intent_reader=dispatch_store,
            evidence_reader=evidence_store,
        )
        view = query.get(request.task_id)

        assert view is not None
        assert view.version == "V2"
        assert view.status.value == "SUCCEEDED"
        assert view.saga_id == result.saga_id
        assert len(view.materializations) == 2
        assert {
            item.verified_thickness_mm for item in view.materializations
        } == {300.0}
        assert {
            item.host_kind for item in view.materializations
        } == {"AUTOCAD", "REVIT"}
        assert all(item.actual_delta_hash for item in view.materializations)
        assert all(item.verification_hash for item in view.materializations)
        assert all(item.evidence_bundle_hash for item in view.materializations)
    finally:
        saver.close()
        decision_store.close()
        request_store.close()
        evidence_store.close()
        dispatch_store.close()
        saga_store.close()
