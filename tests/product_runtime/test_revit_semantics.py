"""Task 5：真实 request-aware Revit semantic boundary 的 TDD contract。"""

from __future__ import annotations

from pathlib import Path

import design_product_runtime
import pytest
from design_orchestrator.workflow_contracts import StableRef
from design_product_runtime import ProductTaskRequest
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
    ReconstructionResult,
    SemanticAspect,
    SemanticDepth,
    build_context_contract,
)
from semantic_service import (
    ProviderRef,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
)


class _RequestStore:
    """只暴露 Task 5 所需 exact-task lookup，并记录实际查询。"""

    def __init__(self, request: ProductTaskRequest) -> None:
        self._request = request
        self.lookups: list[str] = []

    def get(self, task_id: str) -> ProductTaskRequest | None:
        self.lookups.append(task_id)
        if task_id == self._request.task_id:
            return self._request
        return None


class _ContextReader:
    """模拟已由 Task 4 严格验证过的 Revit context READ port。"""

    def __init__(self, observation: RevitContextObservation) -> None:
        self.observation = observation
        self.calls: list[dict[str, str]] = []

    def read(
        self,
        *,
        command_id: str,
        document_id: str,
        host_instance_id: str,
    ) -> RevitContextObservation:
        self.calls.append(
            {
                "command_id": command_id,
                "document_id": document_id,
                "host_instance_id": host_instance_id,
            }
        )
        return self.observation


class _SnapshotTransport:
    """只 fake 外部 Host transport；snapshot port 与其证据校验保持 production 实现。"""

    def __init__(
        self,
        *,
        revision: int = 41,
        wall_unique_id: str = "WALL-UNIQUE-1",
        thickness_mm: float = 275.0,
    ) -> None:
        self.revision = revision
        self.wall_unique_id = wall_unique_id
        self.thickness_mm = thickness_mm
        self.commands = []

    def request(self, command):
        self.commands.append(command)
        return {
            "status": "OK",
            "revision_after": self.revision,
            "payload": {
                "document_id": "DOC-1",
                "host_instance_id": "revit-runtime-1",
                "wall_unique_id": self.wall_unique_id,
                "wall_type_unique_id": "WALL-TYPE-UNIQUE-1",
                "native_kind": "Wall",
                "builtin_category": "OST_Walls",
                "wall_thickness_mm": self.thickness_mm,
                "location_signature": "LOCATION-SIGNATURE-1",
                "relationship_signature": "RELATIONSHIP-SIGNATURE-1",
                "revision_before": self.revision,
                "revision_after": self.revision,
            },
        }


class _RecordingSemanticService(SemanticService):
    """调用真实 SemanticService，只记录其真实 projection 输出供 contract 断言。"""

    def __init__(self, registry, environments) -> None:
        super().__init__(registry, environments)
        self.projected_claims = ()

    def project_facts(self, facts, environment_id):
        claims = super().project_facts(facts, environment_id)
        self.projected_claims = claims
        return claims


def _boundary_type():
    """能力缺失应表现为 focused RED，而不是 pytest collection error。"""

    boundary_type = getattr(
        design_product_runtime,
        "RevitWallThicknessSemanticBoundary",
        None,
    )
    assert boundary_type is not None, "RevitWallThicknessSemanticBoundary is not implemented"
    return boundary_type


def _request(*, task_id: str = "task-A", thickness_mm: float = 300.0) -> ProductTaskRequest:
    """构造本 vertical 的 immutable INTENT authority。"""

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


def _observation(
    *,
    document_id: str = "DOC-1",
    host_instance_id: str = "revit-runtime-1",
    revision: int = 41,
    selected_elements: tuple[RevitSelectedElement, ...] | None = None,
) -> RevitContextObservation:
    """构造 Task 4 已验证 shape 的 Host context evidence。"""

    return RevitContextObservation(
        document_id=document_id,
        document_title="Product Fixture",
        host_instance_id=host_instance_id,
        revision=revision,
        selected_elements=(
            selected_elements
            if selected_elements is not None
            else (
                RevitSelectedElement(
                    unique_id="WALL-UNIQUE-1",
                    native_kind="Wall",
                ),
            )
        ),
    )


def _identity_registry() -> IdentityRegistry:
    """注册已有 semantic identity；产品边界只能 lookup，不能临时发明 identity。"""

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


def _registry_with_second_wall() -> IdentityRegistry:
    """为 recovery mismatch 测试准备第二个合法 Wall binding。"""

    registry = _identity_registry()
    registry.ensure_identity("semantic-wall-2")
    registry.bind_host(
        HostBinding(
            semantic_id="semantic-wall-2",
            host_type="revit",
            document_id="DOC-1",
            native_id="WALL-UNIQUE-2",
            native_kind="Wall",
        )
    )
    return registry


def _boundary(
    *,
    request: ProductTaskRequest | None = None,
    observation: RevitContextObservation | None = None,
    identity_registry: IdentityRegistry | None = None,
):
    """显式注入 environment-owned session/document/runtime identity，不把它们塞进 request。"""

    request_store = _RequestStore(request or _request())
    context_reader = _ContextReader(observation or _observation())
    boundary = _boundary_type()(
        request_store=request_store,
        context_reader=context_reader,
        identity_registry=identity_registry or _identity_registry(),
        session_ref="revit-session-1",
        document_id="DOC-1",
        host_instance_id="revit-runtime-1",
    )
    return boundary, request_store, context_reader


def _real_semantic_service():
    """按仓库真实 provider manifests 注册并 pin 本 vertical 所需 semantic environment。"""

    providers = (
        IFC43_PROVIDER,
        DSP_CORE_PROVIDER,
        ENTERPRISE_MAPPING_PROVIDER,
    )
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
    return _RecordingSemanticService(registry, environments), environment


def _reconstruction_boundary(
    *,
    identity_registry: IdentityRegistry | None = None,
    snapshot_revision: int = 41,
    snapshot_wall_unique_id: str = "WALL-UNIQUE-1",
    snapshot_thickness_mm: float = 275.0,
):
    """只 fake Host transport，其他 reconstruction collaborators 使用真实 production 实现。"""

    request_store = _RequestStore(_request())
    context_reader = _ContextReader(_observation(revision=snapshot_revision))
    snapshot_transport = _SnapshotTransport(
        revision=snapshot_revision,
        wall_unique_id=snapshot_wall_unique_id,
        thickness_mm=snapshot_thickness_mm,
    )
    semantic_service, semantic_environment = _real_semantic_service()
    try:
        boundary = _boundary_type()(
            request_store=request_store,
            context_reader=context_reader,
            identity_registry=identity_registry or _identity_registry(),
            session_ref="revit-session-1",
            document_id="DOC-1",
            host_instance_id="revit-runtime-1",
            snapshot_reader=RevitWallThicknessSnapshotReadPort(snapshot_transport),
            design_fact_adapter=DesignFactAdapter(),
            semantic_service=semantic_service,
            semantic_environment=semantic_environment,
        )
    except TypeError as exc:
        pytest.fail(f"real Revit semantic reconstruction composition is not implemented: {exc}")
    return boundary, snapshot_transport, semantic_service, semantic_environment


def _context_contract(*, root_entities: tuple[str, ...] = ("semantic-wall-1",)):
    """要求 real reconstruction 为 Wall classification 与 thickness property 提供 canonical 证据。"""

    return build_context_contract(
        "DOC-1",
        root_entities,
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


def _load_context_inputs(boundary, context_ref: StableRef):
    """把 Step 2 能力缺失表现为单一、可诊断的 RED。"""

    method = getattr(boundary, "load_context_inputs", None)
    assert method is not None, "load_context_inputs is not implemented"
    return method(context_ref)


def _reconstruct(boundary, contract, *, expected_host_revision: str = "41"):
    """把 Step 3 能力缺失表现为单一、可诊断的 RED。"""

    method = getattr(boundary, "reconstruct", None)
    assert method is not None, "reconstruct is not implemented"
    return method(contract, expected_host_revision)


def test_resolve_host_context_uses_exact_request_and_existing_host_binding() -> None:
    """exact task request + authoritative Host selection 必须解析到已有 semantic identity。"""

    boundary, request_store, context_reader = _boundary()

    context_ref = boundary.resolve_host_context("task-A")

    assert isinstance(context_ref, StableRef)
    assert context_ref.content_hash is not None
    assert len(context_ref.content_hash) == 64
    assert request_store.lookups == ["task-A"]
    assert len(context_reader.calls) == 1
    assert context_reader.calls[0]["document_id"] == "DOC-1"
    assert context_reader.calls[0]["host_instance_id"] == "revit-runtime-1"


def test_context_observation_hash_is_deterministic_and_binds_host_revision() -> None:
    """相同 exact observation 必须同 hash；revision 变化必须改变 context identity。"""

    first, _, _ = _boundary(observation=_observation(revision=41))
    rebuilt, _, _ = _boundary(observation=_observation(revision=41))
    changed, _, _ = _boundary(observation=_observation(revision=42))

    first_ref = first.resolve_host_context("task-A")
    rebuilt_ref = rebuilt.resolve_host_context("task-A")
    changed_ref = changed.resolve_host_context("task-A")

    assert rebuilt_ref == first_ref
    assert changed_ref.content_hash != first_ref.content_hash


@pytest.mark.parametrize(
    "selected_elements",
    [
        (),
        (
            RevitSelectedElement(unique_id="WALL-UNIQUE-1", native_kind="Wall"),
            RevitSelectedElement(unique_id="WALL-UNIQUE-2", native_kind="Wall"),
        ),
    ],
)
def test_resolve_host_context_requires_exactly_one_selection(
    selected_elements: tuple[RevitSelectedElement, ...],
) -> None:
    """exactly-one 是 Product Runtime 规则，不下沉到 Task 4 transport port。"""

    boundary, _, _ = _boundary(
        observation=_observation(selected_elements=selected_elements),
    )

    with pytest.raises(ValueError, match="selection"):
        boundary.resolve_host_context("task-A")


def test_resolve_host_context_requires_wall_native_kind() -> None:
    """首个 vertical 只接受 Host 明确观测为 Wall 的 selected native entity。"""

    boundary, _, _ = _boundary(
        observation=_observation(
            selected_elements=(
                RevitSelectedElement(
                    unique_id="WALL-UNIQUE-1",
                    native_kind="FamilyInstance",
                ),
            )
        )
    )

    with pytest.raises(ValueError, match="Wall"):
        boundary.resolve_host_context("task-A")


def test_resolve_host_context_requires_preexisting_identity_binding() -> None:
    """Host selection 不得由产品边界临时创造 semantic identity。"""

    boundary, _, _ = _boundary(identity_registry=IdentityRegistry())

    with pytest.raises((KeyError, ValueError), match="identity|binding|semantic"):
        boundary.resolve_host_context("task-A")


def test_context_hash_binds_exact_request_lineage_not_process_current_request() -> None:
    """同一 Host observation 的不同 task/request 仍必须形成不同 exact context lineage。"""

    task_a, _, _ = _boundary(request=_request(task_id="task-A", thickness_mm=300.0))
    task_b, _, _ = _boundary(request=_request(task_id="task-B", thickness_mm=350.0))

    ref_a = task_a.resolve_host_context("task-A")
    ref_b = task_b.resolve_host_context("task-B")

    assert ref_a.content_hash != ref_b.content_hash


def test_fresh_boundary_rebuilds_context_inputs_only_from_exact_host_reread() -> None:
    """restart 后不能依赖进程缓存；exact re-read 应重建 freshness 所需最小输入。"""

    initial, _, _ = _boundary(observation=_observation(revision=41))
    context_ref = initial.resolve_host_context("task-A")
    fresh, request_store, context_reader = _boundary(observation=_observation(revision=41))

    inputs = _load_context_inputs(fresh, context_ref)

    assert inputs.task_id == "task-A"
    assert inputs.project_id == "project-1"
    assert inputs.document_ref == "DOC-1"
    assert inputs.root_entities == ("semantic-wall-1",)
    assert request_store.lookups == ["task-A"]
    assert len(context_reader.calls) == 1


def test_load_context_inputs_rejects_changed_revision() -> None:
    """captured context 后 Host revision 变化必须 fail closed，不能接受 latest context。"""

    initial, _, _ = _boundary(observation=_observation(revision=41))
    context_ref = initial.resolve_host_context("task-A")
    fresh, _, _ = _boundary(observation=_observation(revision=42))

    with pytest.raises(ValueError, match="context|hash|revision"):
        _load_context_inputs(fresh, context_ref)


def test_load_context_inputs_rejects_changed_selection_even_when_both_walls_are_known() -> None:
    """selection 从 Wall A 漂移到合法 Wall B 仍是 context mismatch，不允许 latest fallback。"""

    registry = _registry_with_second_wall()
    initial, _, _ = _boundary(identity_registry=registry)
    context_ref = initial.resolve_host_context("task-A")
    fresh, _, _ = _boundary(
        identity_registry=registry,
        observation=_observation(
            selected_elements=(
                RevitSelectedElement(unique_id="WALL-UNIQUE-2", native_kind="Wall"),
            )
        ),
    )

    with pytest.raises(ValueError, match="context|hash|selection"):
        _load_context_inputs(fresh, context_ref)


def test_load_context_inputs_rejects_changed_document_identity() -> None:
    """Host re-read 若返回另一 document，必须在 freshness input assembly 前 fail closed。"""

    initial, _, _ = _boundary()
    context_ref = initial.resolve_host_context("task-A")
    fresh, _, _ = _boundary(observation=_observation(document_id="DOC-OTHER"))

    with pytest.raises(ValueError, match="context|document|identity"):
        _load_context_inputs(fresh, context_ref)


def test_reconstruct_uses_exact_host_binding_and_strict_snapshot_read() -> None:
    """reconstruction 必须从 semantic root 的 exact HostBinding 读取同一 Revit Wall revision。"""

    boundary, snapshot_transport, _, _ = _reconstruction_boundary()
    contract = _context_contract()

    result = _reconstruct(boundary, contract)

    assert isinstance(result, ReconstructionResult)
    assert result.document_ref == "DOC-1"
    assert result.host_revision == "41"
    assert result.coverage == contract.coverage
    assert len(snapshot_transport.commands) == 1
    command = snapshot_transport.commands[0]
    assert command.mode == "READ"
    assert command.operation == "read_wall_thickness_snapshot"
    assert [item.native_id for item in command.target_native_refs] == ["WALL-UNIQUE-1"]


def test_reconstruct_projects_revit_facts_through_real_pinned_semantic_service() -> None:
    """canonical Wall/WallThickness 必须来自正式 enterprise mapping，而不是产品层常量。"""

    boundary, _, semantic_service, semantic_environment = _reconstruction_boundary(
        snapshot_thickness_mm=275.0,
    )

    result = _reconstruct(boundary, _context_contract())

    projected = {
        (
            claim.predicate,
            claim.canonical_term_id,
            claim.value,
            claim.unit,
            claim.assurance,
        )
        for claim in semantic_service.projected_claims
    }
    assert ("classification", "ifc:IfcWall", None, None, "RULE_DERIVED") in projected
    assert ("property", "dsp:WallThickness", 275.0, "mm", "RULE_DERIVED") in projected
    assert result.semantic_environment_ref.environment_id == semantic_environment.environment_id
    assert result.semantic_environment_ref.content_hash == semantic_environment.content_hash
    assert result.projection_ref.normalized_fact_batch_hash is not None
    assert len(result.projection_ref.normalized_fact_batch_hash) == 64
    assert len(result.projection_ref.projection_hash) == 64
    assert len(result.projection_ref.provider_set_hash) == 64
    assert len(result.projection_ref.mapping_profile_set_hash) == 64


def test_reconstruct_reports_only_guarantees_supported_by_real_projection() -> None:
    """CLASSIFICATION/PROPERTIES progressive guarantees 必须与真实 RULE_DERIVED claims 对齐。"""

    boundary, _, _, _ = _reconstruction_boundary()

    result = _reconstruct(boundary, _context_contract())

    guarantees = {item.aspect: item for item in result.guarantees}
    assert set(guarantees) == {
        SemanticAspect.IDENTITY,
        SemanticAspect.CLASSIFICATION,
        SemanticAspect.PROPERTIES,
    }
    for aspect in (SemanticAspect.CLASSIFICATION, SemanticAspect.PROPERTIES):
        guarantee = guarantees[aspect]
        assert guarantee.coverage_state is CoverageState.RESOLVED
        assert guarantee.semantic_depth is SemanticDepth.CANONICAL
        assert guarantee.assurance_level is AssuranceLevel.RULE_DERIVED


def test_reconstruct_requires_exact_revit_host_binding_for_contract_root() -> None:
    """freshness coverage 里的 semantic root 没有 exact Revit binding 时禁止 latest/reverse fallback。"""

    boundary, _, _, _ = _reconstruction_boundary()
    contract = _context_contract(root_entities=("semantic-wall-missing",))

    with pytest.raises((KeyError, ValueError), match="identity|binding|semantic"):
        _reconstruct(boundary, contract)


def test_product_semantic_boundary_source_does_not_hardcode_ifc_wall() -> None:
    """产品 composition 不能把 canonical Wall 分类重新写成应用层常量。"""

    source_path = Path(design_product_runtime.__file__).with_name("revit_semantics.py")
    assert "ifc:IfcWall" not in source_path.read_text(encoding="utf-8")
