"""Task 5 Step 4：真实 Revit semantic eligibility 到 OperationResolver 输入的 TDD contract。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from design_orchestrator.canonical_operations import SET_WALL_THICKNESS_V1
from design_orchestrator.default_workflow_services import OperationResolutionInputs
from design_orchestrator.operation_resolver import (
    OperationResolver,
    ResolutionContext,
    SemanticEligibilityContext,
)
from design_orchestrator.workflow_contracts import StableRef
from design_product_runtime import ProductTaskRequest, RevitWallThicknessSemanticBoundary
from dsp_core_semantic_provider import DSP_CORE_PROVIDER
from enterprise_mapping_provider import ENTERPRISE_MAPPING_PROVIDER
from ifc43_semantic_provider import IFC43_PROVIDER
from revit_sidecar import (
    RevitContextObservation,
    RevitSelectedElement,
    RevitWallThicknessSnapshotReadPort,
)
from revit_sidecar.design_fact_adapter import DesignFactAdapter
from semantic_runtime import (
    AspectRequirement,
    AssuranceLevel,
    CoverageState,
    HostBinding,
    IdentityRegistry,
    InMemorySnapshotRegistry,
    SemanticAspect,
    SemanticDepth,
    SemanticSnapshot,
    build_context_contract,
)
from semantic_service import (
    ProviderRef,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
)


@dataclass(frozen=True, slots=True)
class _WallCapabilityProfile:
    """模拟 environment-owned provider descriptor；resolver 仍消费正式 structural contract。"""

    provider_server: str = "revit.product"
    provider_tool: str = "set_wall_thickness"
    canonical_operation: str = "set_wall_thickness.v1"
    category: str = "MODEL_OPERATION"
    entity_constraints: tuple[str, ...] = ("Wall",)
    execution_freshness: tuple[dict[str, Any], ...] = (
        {"aspect": "PROPERTIES", "required_state": "FRESH"},
    )
    effects: tuple[str, ...] = ("PROPERTIES",)
    risk: str | None = "LOW"
    preview_supported: bool = True
    rollback_supported: bool = False
    verification_contract: dict[str, Any] = field(
        default_factory=lambda: dict(SET_WALL_THICKNESS_V1.verification_contract)
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: dict(SET_WALL_THICKNESS_V1.input_schema)
    )
    output_schema: dict[str, Any] | None = None


class _RequestStore:
    def __init__(self, request: ProductTaskRequest) -> None:
        self._request = request

    def get(self, task_id: str) -> ProductTaskRequest | None:
        return self._request if task_id == self._request.task_id else None


class _ContextReader:
    def read(self, *, command_id: str, document_id: str, host_instance_id: str):
        del command_id
        return RevitContextObservation(
            document_id=document_id,
            document_title="Product Fixture",
            host_instance_id=host_instance_id,
            revision=41,
            selected_elements=(
                RevitSelectedElement(unique_id="WALL-UNIQUE-1", native_kind="Wall"),
            ),
        )


class _SnapshotTransport:
    def request(self, command):
        return {
            "status": "OK",
            "revision_after": 41,
            "payload": {
                "document_id": command.document_id,
                "host_instance_id": "revit-runtime-1",
                "wall_unique_id": "WALL-UNIQUE-1",
                "wall_type_unique_id": "WALL-TYPE-UNIQUE-1",
                "native_kind": "Wall",
                "builtin_category": "OST_Walls",
                "wall_thickness_mm": 275.0,
                "location_signature": "LOCATION-SIGNATURE-1",
                "relationship_signature": "RELATIONSHIP-SIGNATURE-1",
                "revision_before": 41,
                "revision_after": 41,
            },
        }


def _request() -> ProductTaskRequest:
    return ProductTaskRequest.create(
        task_id="task-A",
        project_id="project-1",
        host_kind="REVIT",
        session_ref="revit-session-1",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


def _identity_registry() -> IdentityRegistry:
    registry = IdentityRegistry()
    registry.ensure_identity("semantic-wall-1")
    registry.bind_host(
        HostBinding(
            semantic_id="semantic-wall-1",
            host_type="revit",
            document_id="DOC-1",
            native_id="WALL-UNIQUE-1",
            native_kind="Wall",
        )
    )
    return registry


def _semantic_service():
    providers = (IFC43_PROVIDER, DSP_CORE_PROVIDER, ENTERPRISE_MAPPING_PROVIDER)
    registry = SemanticProviderRegistry()
    for provider in providers:
        registry.register(provider)
    environments = SemanticEnvironmentStore()
    environment = environments.pin(
        tuple(
            ProviderRef(provider.manifest.provider_id, provider.manifest.version)
            for provider in providers
        ),
        registry,
    )
    return SemanticService(registry, environments), environment


def _context_contract():
    return build_context_contract(
        "DOC-1",
        ("semantic-wall-1",),
        (
            AspectRequirement(
                SemanticAspect.CLASSIFICATION,
                minimum_coverage=CoverageState.RESOLVED,
                semantic_depth=SemanticDepth.CANONICAL,
                minimum_assurance=AssuranceLevel.RULE_DERIVED,
            ),
            AspectRequirement(
                SemanticAspect.PROPERTIES,
                minimum_coverage=CoverageState.RESOLVED,
                semantic_depth=SemanticDepth.CANONICAL,
                minimum_assurance=AssuranceLevel.RULE_DERIVED,
            ),
        ),
        project_id="project-1",
    )


def _configured_boundary():
    semantic_service, environment = _semantic_service()
    common = {
        "request_store": _RequestStore(_request()),
        "context_reader": _ContextReader(),
        "identity_registry": _identity_registry(),
        "session_ref": "revit-session-1",
        "document_id": "DOC-1",
        "host_instance_id": "revit-runtime-1",
        "snapshot_reader": RevitWallThicknessSnapshotReadPort(_SnapshotTransport()),
        "design_fact_adapter": DesignFactAdapter(),
        "semantic_service": semantic_service,
        "semantic_environment": environment,
    }
    seed = RevitWallThicknessSemanticBoundary(**common)
    contract = _context_contract()
    snapshot = SemanticSnapshot.create(contract, seed.reconstruct(contract, "41"))
    snapshots = InMemorySnapshotRegistry()
    snapshots.put_snapshot(snapshot)
    profile = _WallCapabilityProfile()
    try:
        boundary = RevitWallThicknessSemanticBoundary(
            **common,
            snapshot_registry=snapshots,
            capability_profiles=(profile,),
        )
    except TypeError as exc:
        pytest.fail(f"Step 4 operation-resolution composition is not implemented: {exc}")
    return boundary, snapshot, profile


def _load_inputs(boundary, snapshot_ref: StableRef):
    method = getattr(boundary, "load_operation_resolution_inputs", None)
    assert method is not None, "load_operation_resolution_inputs is not implemented"
    return method(snapshot_ref)


def test_operation_resolution_inputs_are_bound_to_exact_context_snapshot() -> None:
    """eligibility read model 必须绑定 exact ContextSnapshot id/hash/document/environment。"""

    boundary, snapshot, profile = _configured_boundary()

    inputs = _load_inputs(boundary, StableRef(snapshot.snapshot_id, snapshot.hash))

    assert isinstance(inputs, OperationResolutionInputs)
    assert inputs.profiles == (profile,)
    assert isinstance(inputs.context, ResolutionContext)
    semantic_context = inputs.context.semantic_context
    assert isinstance(semantic_context, SemanticEligibilityContext)
    assert semantic_context.context_snapshot_id == snapshot.snapshot_id
    assert semantic_context.context_snapshot_hash == snapshot.hash
    assert semantic_context.document_ref == snapshot.document_ref
    assert (
        semantic_context.semantic_environment_ref
        == snapshot.semantic_environment_ref.environment_id
    )
    assert inputs.context.host_provider_servers == frozenset({"revit.product"})


def test_operation_resolution_uses_real_projection_claims_and_existing_resolver() -> None:
    """canonical Wall classification 来自真实 projection；Product Runtime 不重新实现 resolver。"""

    boundary, snapshot, _ = _configured_boundary()
    inputs = _load_inputs(boundary, StableRef(snapshot.snapshot_id, snapshot.hash))

    entities = inputs.context.semantic_context.entities
    assert len(entities) == 1
    assert entities[0].semantic_id == "semantic-wall-1"
    assert entities[0].canonical_classifications == ("ifc:IfcWall",)
    assert entities[0].classification_guarantee is not None
    assert entities[0].classification_guarantee.machine_decision_supported is True

    result = OperationResolver((SET_WALL_THICKNESS_V1,)).resolve(
        inputs.profiles,
        inputs.context,
    )
    assert [item.canonical_operation for item in result.resolved_operations] == [
        "set_wall_thickness.v1"
    ]


def test_operation_resolution_rejects_context_snapshot_hash_mismatch() -> None:
    """snapshot ref 必须携带 exact owner hash；禁止按 id 接受 stale/latest 语义。"""

    boundary, snapshot, _ = _configured_boundary()

    with pytest.raises(ValueError, match="hash|snapshot|lineage"):
        _load_inputs(boundary, StableRef(snapshot.snapshot_id, "0" * 64))
