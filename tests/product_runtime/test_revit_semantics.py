"""Task 5：真实 request-aware Revit semantic boundary 的 TDD contract。"""

from __future__ import annotations

import design_product_runtime
import pytest
from design_orchestrator.workflow_contracts import StableRef
from design_product_runtime import ProductTaskRequest
from revit_sidecar import RevitContextObservation, RevitSelectedElement
from semantic_runtime import HostBinding, IdentityRegistry


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


def _load_context_inputs(boundary, context_ref: StableRef):
    """把 Step 2 能力缺失表现为单一、可诊断的 RED。"""

    method = getattr(boundary, "load_context_inputs", None)
    assert method is not None, "load_context_inputs is not implemented"
    return method(context_ref)


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
