"""Task 7 Step 3：Operation Resolution artifact availability / legacy rehydrate RED 契约。

这组测试只冻结 ``WorkflowServices`` 的 deterministic artifact 恢复边界：

1. 已存在的 durable ``ResolutionResult`` 必须直接复用，不能重新运行 resolver；
2. v2 checkpoint 的 artifact 缺失必须 fail closed，禁止用 owner read model 偷偷重建；
3. 只有明确允许 legacy rehydrate、且旧 ref hash 与真实重建结果精确一致时，才能写入新 codec artifact；
4. legacy ref 缺 hash 或 hash 不匹配时必须保持 unavailable，不能制造新的 authoritative truth。

LangGraph checkpoint migration 与 interrupt projection 属于 Task 7 后续步骤，不在本文件覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from design_orchestrator.canonical_operations import MOVE_V1, MVP_CANONICAL_OPERATIONS
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    OperationResolutionInputs,
)
from design_orchestrator.operation_resolver import (
    OperationResolver,
    ResolutionContext,
    ResolutionResult,
    SemanticEligibilityContext,
)
from design_orchestrator.parameter_binder import MVP_BINDING_RECIPES, ParameterBinder
from design_orchestrator.workflow_artifacts import (
    WorkflowArtifactUnavailableError,
    legacy_workflow_artifact_content_hash,
    workflow_artifact_content_hash,
)
from design_orchestrator.workflow_contracts import StableRef


@dataclass(frozen=True, slots=True)
class _Profile:
    """生成稳定 ``ResolutionResult`` 的最小真实 capability profile。"""

    provider_server: str = "autocad.local"
    provider_tool: str = "cad.move"
    canonical_operation: str = "move.v1"
    category: str = "MODEL_OPERATION"
    entity_constraints: tuple[str, ...] = ("LINE", "ARC")
    execution_freshness: tuple[dict[str, Any], ...] = (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    effects: tuple[str, ...] = ("PLACEMENT", "GEOMETRY")
    risk: str | None = "LOW"
    preview_supported: bool = False
    rollback_supported: bool = False
    verification_contract: dict[str, Any] = field(
        default_factory=lambda: {"type": "HOST_READ_BACK"}
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "handles": {"type": "array", "items": {"type": "string"}},
                "dx": {"type": "number"},
                "dy": {"type": "number"},
            },
            "required": ["handles", "dx", "dy"],
        }
    )
    output_schema: dict[str, Any] | None = None


class _ArtifactStore:
    """显式记录 get/put 的内存 artifact store，用于证明恢复路径没有隐藏副作用。"""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.get_calls: list[StableRef] = []
        self.put_calls: list[tuple[str, object, str]] = []

    def seed(self, ref: StableRef, value: object) -> None:
        """直接放入测试既有 durable artifact，不经过待测 producer。"""

        self.values[ref.ref_id] = value

    def get(self, ref: StableRef) -> object:
        """缺失统一模拟 production store 的 ``WorkflowArtifactUnavailableError``。"""

        self.get_calls.append(ref)
        try:
            return self.values[ref.ref_id]
        except KeyError as exc:
            raise WorkflowArtifactUnavailableError(
                "test workflow artifact is unavailable"
            ) from exc

    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef:
        """记录 rehydrate 写入，并返回带 canonical hash 的新 opaque ref。"""

        self.put_calls.append((kind, value, content_hash))
        ref = StableRef(
            ref_id=f"rehydrated-{len(self.put_calls)}",
            content_hash=content_hash,
        )
        self.values[ref.ref_id] = value
        return ref


class _ExternalOwners:
    """Task 7 Step 3 只暴露 operation-resolution owner read model。"""

    def __init__(self) -> None:
        self.resolution_inputs: OperationResolutionInputs | None = None
        self.resolution_calls: list[StableRef] = []

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs:
        """记录 legacy rehydrate 是否真的读取了精确 snapshot-bound inputs。"""

        self.resolution_calls.append(snapshot_ref)
        if self.resolution_inputs is None:
            raise WorkflowArtifactUnavailableError(
                "test operation resolution inputs are unavailable"
            )
        return self.resolution_inputs


def _resolution_context() -> ResolutionContext:
    """构造与 ``MOVE_V1`` 对齐的 deterministic resolver context。"""

    return ResolutionContext(
        host_provider_servers=frozenset({"autocad.local"}),
        semantic_context=SemanticEligibilityContext(
            context_snapshot_id="CS-hitl-recovery",
            context_snapshot_hash="snapshot-hitl-recovery",
            document_ref="drawing-hitl-recovery",
            semantic_environment_ref="semantic-env@hitl-recovery",
            entities=(),
        ),
    )


def _resolution_inputs() -> OperationResolutionInputs:
    """返回可以精确重建 legacy operation-space 的 owner inputs。"""

    return OperationResolutionInputs(
        profiles=(_Profile(),),
        context=_resolution_context(),
    )


def _resolution() -> ResolutionResult:
    """直接运行 production resolver，得到 legacy/new hash 都可验证的真实 artifact。"""

    inputs = _resolution_inputs()
    return OperationResolver((MOVE_V1,)).resolve(inputs.profiles, inputs.context)


def _service(
    store: _ArtifactStore,
    owners: _ExternalOwners,
) -> DefaultWorkflowServices:
    """用 production resolver/binder 组装默认 workflow service。"""

    return DefaultWorkflowServices(
        operation_resolver=OperationResolver((MOVE_V1,)),
        parameter_binder=ParameterBinder(
            MVP_CANONICAL_OPERATIONS,
            MVP_BINDING_RECIPES,
        ),
        artifact_store=store,
        external_owners=owners,
    )


def test_ensure_operation_artifact_prefers_existing_durable_resolution() -> None:
    """Durable artifact 命中时必须原 ref 返回，且 resolver/read-model 均不能被调用。"""

    store = _ArtifactStore()
    owners = _ExternalOwners()
    service = _service(store, owners)
    resolution = _resolution()
    operation_ref = StableRef(
        "durable-operation",
        workflow_artifact_content_hash(resolution),
    )
    store.seed(operation_ref, resolution)

    recovered = service.ensure_operation_artifact(
        operation_ref,
        StableRef("snapshot-current"),
        allow_legacy_rehydrate=False,
    )

    assert recovered.ref == operation_ref
    assert recovered.source == "durable"
    assert store.get_calls == [operation_ref]
    assert store.put_calls == []
    assert owners.resolution_calls == []


def test_v2_missing_operation_artifact_fails_closed_without_rehydrate() -> None:
    """v2 artifact 丢失/损坏时不得依赖当前 owner facts 重算后继续。"""

    store = _ArtifactStore()
    owners = _ExternalOwners()
    owners.resolution_inputs = _resolution_inputs()
    service = _service(store, owners)
    missing_ref = StableRef(
        "missing-v2-operation",
        workflow_artifact_content_hash(_resolution()),
    )

    with pytest.raises(WorkflowArtifactUnavailableError):
        service.ensure_operation_artifact(
            missing_ref,
            StableRef("snapshot-current"),
            allow_legacy_rehydrate=False,
        )

    assert store.get_calls == [missing_ref]
    assert store.put_calls == []
    assert owners.resolution_calls == []


def test_exact_legacy_hash_can_rehydrate_to_new_canonical_artifact() -> None:
    """Legacy ref 只有在真实 resolver 输出与旧 hash 精确相等时才可迁移成新 artifact。"""

    store = _ArtifactStore()
    owners = _ExternalOwners()
    owners.resolution_inputs = _resolution_inputs()
    service = _service(store, owners)
    expected_resolution = _resolution()
    legacy_ref = StableRef(
        "legacy-operation",
        legacy_workflow_artifact_content_hash(expected_resolution),
    )
    snapshot_ref = StableRef("snapshot-legacy")

    recovered = service.ensure_operation_artifact(
        legacy_ref,
        snapshot_ref,
        allow_legacy_rehydrate=True,
    )

    assert recovered.source == "rehydrated"
    assert recovered.ref != legacy_ref
    assert recovered.ref.content_hash == workflow_artifact_content_hash(
        expected_resolution
    )
    assert owners.resolution_calls == [snapshot_ref]
    assert store.get_calls == [legacy_ref]
    assert len(store.put_calls) == 1
    kind, stored_value, stored_hash = store.put_calls[0]
    assert kind == "operation_resolution"
    assert stored_value == expected_resolution
    assert stored_hash == workflow_artifact_content_hash(expected_resolution)


def test_legacy_rehydrate_rejects_missing_old_hash_before_owner_read() -> None:
    """没有 legacy content hash 就没有可验证的历史 identity，必须在读 owner facts 前失败。"""

    store = _ArtifactStore()
    owners = _ExternalOwners()
    owners.resolution_inputs = _resolution_inputs()
    service = _service(store, owners)
    legacy_ref = StableRef("legacy-operation-without-hash", None)

    with pytest.raises(WorkflowArtifactUnavailableError):
        service.ensure_operation_artifact(
            legacy_ref,
            StableRef("snapshot-legacy"),
            allow_legacy_rehydrate=True,
        )

    assert store.get_calls == [legacy_ref]
    assert store.put_calls == []
    assert owners.resolution_calls == []


def test_legacy_rehydrate_rejects_hash_mismatch_without_persisting() -> None:
    """当前 resolver 重建结果与旧 ref hash 不一致时不能生成新的 durable artifact。"""

    store = _ArtifactStore()
    owners = _ExternalOwners()
    owners.resolution_inputs = _resolution_inputs()
    service = _service(store, owners)
    mismatched_ref = StableRef("legacy-operation-mismatch", "f" * 64)
    snapshot_ref = StableRef("snapshot-legacy")

    with pytest.raises(WorkflowArtifactUnavailableError):
        service.ensure_operation_artifact(
            mismatched_ref,
            snapshot_ref,
            allow_legacy_rehydrate=True,
        )

    assert store.get_calls == [mismatched_ref]
    assert store.put_calls == []
    assert owners.resolution_calls == [snapshot_ref]
