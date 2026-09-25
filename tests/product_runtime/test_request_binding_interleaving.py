"""Task 5 Step 5/6/7：ProductTask INTENT、exact ContextSnapshot 与恢复隔离 contract。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from design_orchestrator.artifact_postgres import create_postgres_artifact_store
from design_orchestrator.canonical_operations import (
    MVP_CANONICAL_OPERATIONS,
    SET_WALL_THICKNESS_V1,
)
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    OperationResolutionInputs,
    ParameterBindingInputs,
)
from design_orchestrator.langgraph_runtime import LangGraphWorkflowRuntime
from design_orchestrator.operation_resolver import (
    ClassificationGuarantee,
    OperationResolver,
    ResolutionContext,
    SemanticEligibilityContext,
    SemanticEligibilityEntity,
)
from design_orchestrator.parameter_binder import (
    BoundOperationProposal,
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowPhase,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)
from design_product_runtime import (
    ProductTaskRequest,
    RevitSemanticBoundaryError,
    RevitWallThicknessSemanticBoundary,
    create_postgres_product_task_request_store,
)
from design_product_runtime.contracts import ProductTaskRequestError
from revit_sidecar import RevitContextObservation, RevitSelectedElement
from semantic_runtime import (
    AspectGuarantee,
    HostBinding,
    IdentityRegistry,
    InMemorySnapshotRegistry,
    ReconstructionResult,
    SemanticAspect,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    build_context_contract,
)


class _RequestStore:
    """按 exact task id 返回 immutable request，并记录所有 lookup。"""

    def __init__(self, *requests: ProductTaskRequest) -> None:
        self._requests = {request.task_id: request for request in requests}
        self.lookups: list[str] = []

    def get(self, task_id: str) -> ProductTaskRequest | None:
        self.lookups.append(task_id)
        return self._requests.get(task_id)


class _NoHostReread:
    """Parameter binding 已有 ContextSnapshot authority 后不得重新读取当前 Host context。"""

    def read(self, **kwargs):
        del kwargs
        raise AssertionError("parameter binding must not re-read current Revit context")


def _request(task_id: str, thickness_mm: float) -> ProductTaskRequest:
    """构造本 vertical 的 exact immutable user INTENT。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id="project-1",
        host_kind="REVIT",
        session_ref="revit-session-1",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={
            "thickness": {
                "value": thickness_mm,
                "unit": "mm",
            }
        },
    )


def _context_snapshot() -> SemanticSnapshot:
    """构造只携带 authoritative semantic target/lineage 的 ContextSnapshot。"""

    contract = build_context_contract(
        "DOC-1",
        ("semantic-wall-1",),
        project_id="project-1",
    )
    return SemanticSnapshot.create(
        contract,
        ReconstructionResult(
            document_ref="DOC-1",
            host_revision="41",
            coverage=contract.coverage,
            guarantees=(AspectGuarantee(SemanticAspect.IDENTITY),),
            projection_ref=SemanticProjectionRef(
                "projection-binding-step5",
                "a" * 64,
                "dsp.semantic.projection-facts.v1",
                "b" * 64,
                "c" * 64,
            ),
            semantic_environment_ref=SemanticEnvironmentRef(
                "semantic-env-binding-step5",
                "d" * 64,
            ),
        ),
    )


def _snapshot_registry(*snapshots: SemanticSnapshot) -> InMemorySnapshotRegistry:
    """把 exact ContextSnapshot 放入 Semantic Runtime owner registry。"""

    registry = InMemorySnapshotRegistry()
    for snapshot in snapshots:
        registry.put_snapshot(snapshot)
    return registry


def _boundary():
    """同一 fresh boundary 同时可按 task id 读取 A/B，两者共享相同 snapshot authority。"""

    request_store = _RequestStore(
        _request("task-A", 300.0),
        _request("task-B", 350.0),
    )
    snapshot = _context_snapshot()
    boundary = RevitWallThicknessSemanticBoundary(
        request_store=request_store,
        context_reader=_NoHostReread(),
        identity_registry=IdentityRegistry(),
        session_ref="revit-session-1",
        document_id="DOC-1",
        host_instance_id="revit-runtime-1",
        snapshot_registry=_snapshot_registry(snapshot),
    )
    return boundary, request_store, snapshot


def _binding_boundary(request_store, snapshot: SemanticSnapshot):
    """为 failure-path contract 复用同一 exact snapshot，不引入 current Host fallback。"""

    return RevitWallThicknessSemanticBoundary(
        request_store=request_store,
        context_reader=_NoHostReread(),
        identity_registry=IdentityRegistry(),
        session_ref="revit-session-1",
        document_id="DOC-1",
        host_instance_id="revit-runtime-1",
        snapshot_registry=_snapshot_registry(snapshot),
    )


def _load_binding_inputs(
    boundary: RevitWallThicknessSemanticBoundary,
    task_id: str,
    snapshot: SemanticSnapshot,
) -> ParameterBindingInputs:
    """统一走 production binding-input seam，避免测试直接构造 binder DTO。"""

    method = getattr(boundary, "load_parameter_binding_inputs", None)
    assert method is not None, "load_parameter_binding_inputs is not implemented"
    result = method(
        task_id,
        StableRef("operation-space-step5", "e" * 64),
        StableRef(snapshot.snapshot_id, snapshot.hash),
    )
    assert isinstance(result, ParameterBindingInputs)
    return result


def test_binding_inputs_split_user_intent_from_snapshot_context() -> None:
    """thickness 只来自 ProductTask；target/lineage 只来自 exact ContextSnapshot。"""

    boundary, request_store, snapshot = _boundary()

    inputs = _load_binding_inputs(boundary, "task-A", snapshot)

    assert isinstance(inputs.proposal, OperationProposal)
    assert inputs.proposal.canonical_operation == "set_wall_thickness.v1"
    assert inputs.proposal.intent_arguments == {
        "thickness": {"value": 300.0, "unit": "mm"}
    }
    assert "targets" not in inputs.proposal.intent_arguments
    assert isinstance(inputs.context, ParameterBindingContext)
    assert inputs.context.context_snapshot_id == snapshot.snapshot_id
    assert inputs.context.context_snapshot_hash == snapshot.hash
    assert inputs.context.document_ref == "DOC-1"
    assert inputs.context.semantic_environment_ref == "semantic-env-binding-step5"
    assert inputs.context.selection == ("semantic-wall-1",)
    assert request_store.lookups == ["task-A"]


def test_binding_inputs_keep_300_and_350_task_intents_isolated() -> None:
    """同一 snapshot 下交错读取 task-B/A 仍必须返回各自 immutable INTENT。"""

    boundary, request_store, snapshot = _boundary()

    task_b = _load_binding_inputs(boundary, "task-B", snapshot)
    task_a = _load_binding_inputs(boundary, "task-A", snapshot)

    assert task_b.proposal.intent_arguments["thickness"]["value"] == 350.0
    assert task_a.proposal.intent_arguments["thickness"]["value"] == 300.0
    assert task_b.context.selection == task_a.context.selection == ("semantic-wall-1",)
    assert request_store.lookups == ["task-B", "task-A"]


def test_binding_inputs_reject_context_snapshot_hash_mismatch() -> None:
    """binding target 必须来自 exact owner snapshot；相同 id 的错误 hash 不得被接受。"""

    boundary, _, snapshot = _boundary()
    method = getattr(boundary, "load_parameter_binding_inputs", None)
    assert method is not None, "load_parameter_binding_inputs is not implemented"

    with pytest.raises((KeyError, ValueError), match="hash|snapshot|lineage"):
        method(
            "task-A",
            StableRef("operation-space-step5", "e" * 64),
            StableRef(snapshot.snapshot_id, "f" * 64),
        )


def test_binding_inputs_fail_closed_when_exact_request_is_unavailable() -> None:
    """request 丢失时禁止从 current/latest Host 或其他 task 推断 INTENT。"""

    snapshot = _context_snapshot()
    request_store = _RequestStore(_request("task-B", 350.0))
    boundary = _binding_boundary(request_store, snapshot)

    with pytest.raises(RevitSemanticBoundaryError) as captured:
        _load_binding_inputs(boundary, "task-A", snapshot)

    assert captured.value.code == "REVIT_PRODUCT_REQUEST_UNAVAILABLE"
    assert request_store.lookups == ["task-A"]


def test_binding_inputs_propagate_durable_request_hash_integrity_failure(
    product_task_postgres_dsn: str,
) -> None:
    """真实 owner row hash 损坏必须在 binder input assembly 前 fail closed。"""

    with psycopg.connect(product_task_postgres_dsn, autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS product_task CASCADE")

    request = _request("task-A", 300.0)
    store = create_postgres_product_task_request_store(product_task_postgres_dsn)
    store.create(request)
    store.close()

    with psycopg.connect(product_task_postgres_dsn, autocommit=True) as admin:
        admin.execute(
            "UPDATE product_task.request SET request_hash = %s WHERE task_id = %s",
            ("0" * 64, request.task_id),
        )

    reopened = create_postgres_product_task_request_store(product_task_postgres_dsn)
    snapshot = _context_snapshot()
    boundary = _binding_boundary(reopened, snapshot)
    try:
        with pytest.raises(ProductTaskRequestError) as captured:
            _load_binding_inputs(boundary, request.task_id, snapshot)
    finally:
        reopened.close()

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"


@dataclass(frozen=True, slots=True)
class _WallCapabilityProfile:
    """只为 Step 7 pre-binder resolution 提供环境拥有的 Wall capability facts。"""

    provider_server: str = "revit.product-step7"
    provider_tool: str = "set_wall_thickness"
    canonical_operation: str = "set_wall_thickness.v1"
    category: str = "MODEL_OPERATION"
    entity_constraints: tuple[str, ...] = ("Wall",)
    execution_freshness: tuple[dict[str, object], ...] = (
        {"aspect": "PROPERTIES", "required_state": "FRESH"},
    )
    effects: tuple[str, ...] = ("PROPERTIES",)
    risk: str | None = "LOW"
    preview_supported: bool = True
    rollback_supported: bool = False
    verification_contract: dict[str, object] | None = None
    input_schema: dict[str, object] | None = None
    output_schema: dict[str, object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "verification_contract",
            dict(SET_WALL_THICKNESS_V1.verification_contract),
        )
        object.__setattr__(
            self,
            "input_schema",
            {
                "type": "object",
                "properties": {
                    "native_ids": {"type": "array", "items": {"type": "string"}},
                    "canonical_arguments": {"type": "object"},
                },
                "required": ["native_ids", "canonical_arguments"],
                "additionalProperties": False,
            },
        )


def _recovery_snapshot(
    *,
    semantic_id: str,
    revision: int,
    projection_seed: str,
) -> SemanticSnapshot:
    """给两个 workflow 各自冻结不同的 ContextSnapshot lineage。"""

    contract = build_context_contract(
        "DOC-1",
        (semantic_id,),
        project_id="project-1",
    )
    return SemanticSnapshot.create(
        contract,
        ReconstructionResult(
            document_ref="DOC-1",
            host_revision=str(revision),
            coverage=contract.coverage,
            guarantees=(AspectGuarantee(SemanticAspect.IDENTITY),),
            projection_ref=SemanticProjectionRef(
                f"projection-binding-step7-{projection_seed}",
                projection_seed * 64,
                "dsp.semantic.projection-facts.v1",
                "b" * 64,
                "c" * 64,
            ),
            semantic_environment_ref=SemanticEnvironmentRef(
                "semantic-env-binding-step7",
                "d" * 64,
            ),
        ),
    )


def _recovery_identity_registry() -> IdentityRegistry:
    """Task A/B 目标都来自 Host selection；request 本身不携带 target identity。"""

    registry = IdentityRegistry()
    for semantic_id, native_id in (
        ("semantic-wall-A", "WALL-UNIQUE-A"),
        ("semantic-wall-B", "WALL-UNIQUE-B"),
    ):
        registry.ensure_identity(semantic_id)
        registry.bind_host(
            HostBinding(
                semantic_id=semantic_id,
                host_type="revit",
                document_id="DOC-1",
                native_id=native_id,
                native_kind="Wall",
            )
        )
    return registry


class _RecoveryContextReader:
    """按 ProductTask-derived command id 返回各自当前 Revit selection。"""

    def __init__(
        self,
        request_a: ProductTaskRequest,
        request_b: ProductTaskRequest,
    ) -> None:
        self.calls: list[str] = []
        self._observations = {
            self._command_id(request_a): RevitContextObservation(
                document_id="DOC-1",
                document_title="Step 7 Fixture",
                host_instance_id="revit-runtime-1",
                revision=41,
                selected_elements=(
                    RevitSelectedElement(
                        unique_id="WALL-UNIQUE-A",
                        native_kind="Wall",
                    ),
                ),
            ),
            self._command_id(request_b): RevitContextObservation(
                document_id="DOC-1",
                document_title="Step 7 Fixture",
                host_instance_id="revit-runtime-1",
                revision=42,
                selected_elements=(
                    RevitSelectedElement(
                        unique_id="WALL-UNIQUE-B",
                        native_kind="Wall",
                    ),
                ),
            ),
        }

    @staticmethod
    def _command_id(request: ProductTaskRequest) -> str:
        suffix = sha256(
            f"{request.task_id}\n{request.request_hash}".encode()
        ).hexdigest()[:24]
        return f"PRODUCT-CONTEXT-{suffix}"

    def read(
        self,
        *,
        command_id: str,
        document_id: str,
        host_instance_id: str,
    ) -> RevitContextObservation:
        assert document_id == "DOC-1"
        assert host_instance_id == "revit-runtime-1"
        self.calls.append(command_id)
        return self._observations[command_id]


class _InterleavingOwnerPorts:
    """只把 Step 7 所需 pre-binder facts 与真实 product binder seam 接进 graph。"""

    def __init__(
        self,
        *,
        boundary: RevitWallThicknessSemanticBoundary,
        snapshots_by_task: dict[str, SemanticSnapshot],
        resume_only: bool,
    ) -> None:
        self._boundary = boundary
        self._snapshots_by_task = dict(snapshots_by_task)
        self._resume_only = resume_only

    def _forbid_prebinder_replay(self, operation: str) -> None:
        if self._resume_only:
            raise AssertionError(f"restart must not replay pre-binder operation: {operation}")

    def resolve_host_context(self, task_id: str) -> StableRef:
        self._forbid_prebinder_replay("resolve_host_context")
        return self._boundary.resolve_host_context(task_id)

    def ensure_context_freshness(self, context_ref: StableRef) -> StableRef:
        self._forbid_prebinder_replay("ensure_context_freshness")
        inputs = self._boundary.load_context_inputs(context_ref)
        snapshot = self._snapshots_by_task[inputs.task_id]
        assert snapshot.project_id == inputs.project_id
        assert snapshot.document_ref == inputs.document_ref
        assert snapshot.coverage.root_entities == inputs.root_entities
        return StableRef(snapshot.snapshot_id, snapshot.hash)

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs:
        self._forbid_prebinder_replay("load_operation_resolution_inputs")
        snapshot = next(
            item
            for item in self._snapshots_by_task.values()
            if item.snapshot_id == snapshot_ref.ref_id and item.hash == snapshot_ref.content_hash
        )
        semantic_id = snapshot.coverage.root_entities[0]
        return OperationResolutionInputs(
            profiles=(_WallCapabilityProfile(),),
            context=ResolutionContext(
                host_provider_servers=frozenset({"revit.product-step7"}),
                semantic_context=SemanticEligibilityContext(
                    context_snapshot_id=snapshot.snapshot_id,
                    context_snapshot_hash=snapshot.hash,
                    document_ref=snapshot.document_ref,
                    semantic_environment_ref="semantic-env-binding-step7",
                    entities=(
                        SemanticEligibilityEntity(
                            semantic_id=semantic_id,
                            canonical_classifications=("ifc:IfcWall",),
                            classification_guarantee=ClassificationGuarantee(True),
                        ),
                    ),
                ),
            ),
        )

    def load_parameter_binding_inputs(
        self,
        task_id: str,
        operation_space_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> ParameterBindingInputs:
        return self._boundary.load_parameter_binding_inputs(
            task_id,
            operation_space_ref,
            context_snapshot_ref,
        )

    def ensure_operation_freshness(
        self,
        operation_ref: StableRef,
    ) -> AsyncOperationRef:
        """在 binder 后立刻制造可持久化 wait，使测试只观察 Task 5 的 bound artifact。"""

        return AsyncOperationRef(
            kind=AsyncOperationKind.RECONSTRUCTION_JOB,
            owner="product-step7-proof",
            operation_id=f"bound:{operation_ref.ref_id}",
        )


def _interleaving_runtime(
    *,
    request_store,
    context_reader,
    identity_registry: IdentityRegistry,
    snapshots_by_task: dict[str, SemanticSnapshot],
    snapshot_registry: InMemorySnapshotRegistry,
    artifact_store,
    checkpointer,
    resume_only: bool,
) -> LangGraphWorkflowRuntime:
    """每次构造都新建 boundary、services 与 runtime，模拟进程级 composition 重建。"""

    boundary = RevitWallThicknessSemanticBoundary(
        request_store=request_store,
        context_reader=context_reader,
        identity_registry=identity_registry,
        session_ref="revit-session-1",
        document_id="DOC-1",
        host_instance_id="revit-runtime-1",
        snapshot_registry=snapshot_registry,
    )
    owners = _InterleavingOwnerPorts(
        boundary=boundary,
        snapshots_by_task=snapshots_by_task,
        resume_only=resume_only,
    )
    services = DefaultWorkflowServices(
        operation_resolver=OperationResolver((SET_WALL_THICKNESS_V1,)),
        parameter_binder=ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES),
        artifact_store=artifact_store,
        external_owners=owners,
    )
    return LangGraphWorkflowRuntime(services=services, checkpointer=checkpointer)


def _accepted_command(checkpoint) -> WorkflowResumeCommand:
    """只消费 checkpoint 上持久化的 exact human pause identity。"""

    assert checkpoint.pending_interaction is not None
    return WorkflowResumeCommand(
        resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        pause_id=checkpoint.pending_interaction.pause_id,
    )


def _assert_bound_recovery(
    *,
    artifact_store,
    checkpoint,
    expected_thickness: float,
    expected_snapshot: SemanticSnapshot,
    expected_target: str,
) -> None:
    """从 durable artifact owner 读取 binder 结果，而不是观察进程内临时 DTO。"""

    assert checkpoint.phase is WorkflowPhase.ENSURE_OPERATION_FRESHNESS
    assert checkpoint.operation_ref is not None
    bound = artifact_store.get(checkpoint.operation_ref)
    assert isinstance(bound, BoundOperationProposal)
    assert bound.operation.canonical_operation == "set_wall_thickness.v1"
    assert bound.arguments["thickness"] == {
        "value": expected_thickness,
        "unit": "mm",
    }
    assert bound.arguments["targets"] == [expected_target]
    assert bound.context_snapshot_ref.context_snapshot_id == expected_snapshot.snapshot_id
    assert bound.context_snapshot_ref.context_snapshot_hash == expected_snapshot.hash
    assert bound.context_snapshot_ref.document_ref == "DOC-1"
    assert bound.semantic_environment_ref == "semantic-env-binding-step7"


def test_300_350_interleaving_survives_request_boundary_and_runtime_restart(
    product_task_postgres_dsn: str,
) -> None:
    """B→A 恢复必须保留各自 immutable INTENT 与 exact ContextSnapshot lineage。"""

    run_id = uuid4().hex
    task_a = f"task-step7-A-{run_id}"
    task_b = f"task-step7-B-{run_id}"
    request_a = _request(task_a, 300.0)
    request_b = _request(task_b, 350.0)
    snapshot_a = _recovery_snapshot(
        semantic_id="semantic-wall-A",
        revision=41,
        projection_seed="1",
    )
    snapshot_b = _recovery_snapshot(
        semantic_id="semantic-wall-B",
        revision=42,
        projection_seed="2",
    )
    snapshots_by_task = {task_a: snapshot_a, task_b: snapshot_b}

    first_requests = create_postgres_product_task_request_store(product_task_postgres_dsn)
    first_artifacts = create_postgres_artifact_store(product_task_postgres_dsn)
    first_checkpointer = create_postgres_checkpointer(product_task_postgres_dsn)
    try:
        first_requests.create(request_a)
        first_requests.create(request_b)
        first_runtime = _interleaving_runtime(
            request_store=first_requests,
            context_reader=_RecoveryContextReader(request_a, request_b),
            identity_registry=_recovery_identity_registry(),
            snapshots_by_task=snapshots_by_task,
            snapshot_registry=_snapshot_registry(snapshot_a, snapshot_b),
            artifact_store=first_artifacts,
            checkpointer=first_checkpointer,
            resume_only=False,
        )

        pause_a = first_runtime.start(WorkflowStartRequest(task_id=task_a))
        pause_b = first_runtime.start(WorkflowStartRequest(task_id=task_b))
        assert pause_a.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert pause_b.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert pause_a.context_snapshot_ref == StableRef(snapshot_a.snapshot_id, snapshot_a.hash)
        assert pause_b.context_snapshot_ref == StableRef(snapshot_b.snapshot_id, snapshot_b.hash)
        assert pause_a.operation_ref is not None
        assert pause_b.operation_ref is not None
    finally:
        first_requests.close()
        first_artifacts.close()
        first_checkpointer.close()

    reopened_requests = create_postgres_product_task_request_store(product_task_postgres_dsn)
    reopened_artifacts = create_postgres_artifact_store(product_task_postgres_dsn)
    reopened_checkpointer = create_postgres_checkpointer(product_task_postgres_dsn)
    try:
        restarted_runtime = _interleaving_runtime(
            request_store=reopened_requests,
            context_reader=_NoHostReread(),
            identity_registry=IdentityRegistry(),
            snapshots_by_task=snapshots_by_task,
            snapshot_registry=_snapshot_registry(snapshot_a, snapshot_b),
            artifact_store=reopened_artifacts,
            checkpointer=reopened_checkpointer,
            resume_only=True,
        )

        resumed_b = restarted_runtime.resume(task_b, _accepted_command(pause_b))
        _assert_bound_recovery(
            artifact_store=reopened_artifacts,
            checkpoint=resumed_b,
            expected_thickness=350.0,
            expected_snapshot=snapshot_b,
            expected_target="semantic-wall-B",
        )

        resumed_a = restarted_runtime.resume(task_a, _accepted_command(pause_a))
        _assert_bound_recovery(
            artifact_store=reopened_artifacts,
            checkpoint=resumed_a,
            expected_thickness=300.0,
            expected_snapshot=snapshot_a,
            expected_target="semantic-wall-A",
        )

        assert resumed_b.operation_ref != resumed_a.operation_ref
        assert reopened_requests.get(task_b) == request_b
        assert reopened_requests.get(task_a) == request_a
    finally:
        reopened_requests.close()
        reopened_artifacts.close()
        reopened_checkpointer.close()
