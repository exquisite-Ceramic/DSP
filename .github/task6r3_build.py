from __future__ import annotations

from pathlib import Path


def append_once(path: Path, marker: str, addition: str) -> None:
    """只在 marker 尚不存在时追加隔离验证代码，保证 diagnostic push 可重复执行。"""

    source = path.read_text(encoding="utf-8")
    if marker in source:
        return
    path.write_text(source + addition, encoding="utf-8")


graph_path = Path("tests/orchestrator/test_langgraph_graph.py")
graph_source = graph_path.read_text(encoding="utf-8")
if "import pytest\n" not in graph_source:
    import_anchor = "from uuid import UUID\n\nfrom design_orchestrator"
    if import_anchor not in graph_source:
        raise SystemExit("graph import anchor not found")
    graph_source = graph_source.replace(
        import_anchor,
        "from uuid import UUID\n\nimport pytest\nfrom design_orchestrator",
        1,
    )
    graph_path.write_text(graph_source, encoding="utf-8")

append_once(
    graph_path,
    "def test_task6r3_saver_backed_exact_refs_survive_json_round_trip",
    r'''


def _freshness_graph_before_impact():
    """使用真实 InMemorySaver 把 production graph 停在 analyze_impact 执行前。"""

    services = _FreshnessGraphServices(async_first=False)
    saver = InMemorySaver()
    graph = build_workflow_graph(services).compile(checkpointer=saver)
    config = {
        "configurable": {
            "thread_id": "task-freshness-before-impact",
            "checkpoint_ns": "",
        }
    }
    initial_state = {
        "checkpoint_contract_version": 2,
        "task_id": "task-freshness-before-impact",
        "phase": WorkflowPhase.RESOLVE_HOST_CONTEXT.value,
    }
    graph.invoke(initial_state, config=config)
    pause_id = graph.get_state(config).values["pending_interaction"]["pause_id"]
    graph.invoke(
        Command(
            resume={
                "pause_id": pause_id,
                "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
                "payload": {},
            }
        ),
        config=config,
        interrupt_before=["analyze_impact"],
    )
    return services, saver, graph, config


def _round_trip_exact_refs(values: dict[str, object]) -> dict[str, StableRef]:
    """只从 saver 读回的 JSON-compatible values 重建三个 StableRef。"""

    persisted = {
        field_name: values[field_name]
        for field_name in (
            "operation_ref",
            "planning_snapshot_ref",
            "snapshot_set_ref",
        )
    }
    restored = json.loads(json.dumps(persisted, sort_keys=True))
    return {
        field_name: StableRef(**restored[field_name])
        for field_name in persisted
    }


def test_task6r3_saver_backed_exact_refs_survive_json_round_trip() -> None:
    """真实 LangGraph saver 中的三个 exact refs 必须可经 JSON round-trip 恢复。"""

    services, _, graph, config = _freshness_graph_before_impact()
    snapshot = graph.get_state(config)

    assert snapshot.next == ("analyze_impact",)
    assert FORBIDDEN_KEYS.isdisjoint(snapshot.values)
    restored = _round_trip_exact_refs(snapshot.values)
    assert restored == {
        "operation_ref": services.bound_ref,
        "planning_snapshot_ref": services.planning_ref,
        "snapshot_set_ref": services.snapshot_set_ref,
    }
    assert services.impact_calls == []


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("operation_ref", None),
        ("planning_snapshot_ref", None),
        ("snapshot_set_ref", None),
        ("operation_ref", {"ref_id": "", "content_hash": "a" * 64}),
        ("planning_snapshot_ref", {"ref_id": "PS-42", "content_hash": "invalid"}),
        ("snapshot_set_ref", {"ref_id": "PSS-42", "unexpected": "value"}),
    ),
    ids=(
        "missing-operation",
        "missing-planning",
        "missing-snapshot-set",
        "malformed-operation-id",
        "malformed-planning-hash",
        "malformed-snapshot-set-shape",
    ),
)
def test_task6r3_graph_rejects_missing_or_malformed_ref_before_service_dispatch(
    field_name: str,
    invalid_value: object,
) -> None:
    """graph 只对缺失/编码非法 ref fail closed，且不得调用 WorkflowServices Impact seam。"""

    services, _, graph, config = _freshness_graph_before_impact()
    graph.update_state(
        config,
        {field_name: invalid_value},
        as_node="ensure_operation_freshness",
    )

    with pytest.raises(ValueError):
        graph.invoke(None, config=config)
    assert services.impact_calls == []
''',
)

owner_path = Path("tests/orchestrator/test_canonical_owner_ports.py")
append_once(
    owner_path,
    "class _Task6R3GraphServices",
    r'''


class _Task6R3GraphServices:
    """只把 production graph 推到 Impact seam；Impact 本身委托 DefaultWorkflowServices。"""

    def __init__(
        self,
        *,
        bound_ref: StableRef,
        freshness_owner: object | None,
        freshness_result: OperationFreshnessResult | None,
        impact_services: DefaultWorkflowServices | None,
    ) -> None:
        self.bound_ref = bound_ref
        self._freshness_owner = freshness_owner
        self._freshness_result = freshness_result
        self._impact_services = impact_services
        self.workflow_impact_calls: list[tuple[StableRef, StableRef, StableRef]] = []

    def resolve_host_context(self, task_id: str) -> StableRef:
        """前置 graph 节点只需要一个稳定 context navigation ref。"""

        return StableRef(f"graph-context:{task_id}", "1" * 64)

    def ensure_context_freshness(self, snapshot_ref: StableRef) -> StableRef:
        """保持测试 context navigation 不变。"""

        return snapshot_ref

    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef:
        """返回 proposal pause 使用的稳定 operation-space ref。"""

        return StableRef("graph-operation-space", "2" * 64)

    def bind_parameters(self, operation_ref: StableRef) -> StableRef:
        """Human ACCEPT 后切换到 owner store 中真实存在的 bound operation ref。"""

        return self.bound_ref

    def ensure_operation_freshness(
        self,
        operation_ref: StableRef,
    ) -> OperationFreshnessResult:
        """可调用 adapter A 的真实 freshness，或返回已构造的 owner-valid mismatch tuple。"""

        assert operation_ref == self.bound_ref
        if self._freshness_owner is not None:
            result = self._freshness_owner.ensure_operation_freshness(operation_ref)
            assert isinstance(result, OperationFreshnessResult)
            return result
        assert self._freshness_result is not None
        return self._freshness_result

    def analyze_impact(
        self,
        operation_ref: StableRef,
        planning_snapshot_ref: StableRef,
        snapshot_set_ref: StableRef,
    ) -> StableRef:
        """记录 WorkflowServices seam 调用，再委托真实 DefaultWorkflowServices→adapter。"""

        self.workflow_impact_calls.append(
            (operation_ref, planning_snapshot_ref, snapshot_set_ref)
        )
        if self._impact_services is None:
            raise AssertionError("impact services are required after checkpoint resume")
        return self._impact_services.analyze_impact(
            operation_ref,
            planning_snapshot_ref,
            snapshot_set_ref,
        )

    def build_changeset(
        self,
        task_id: str,
        operation_ref: StableRef,
        impact_ref: StableRef,
    ) -> StableRef:
        """Impact 成功后只返回测试导航 ref；Task 6R.3 不重新测试 ChangeSet owner。"""

        return StableRef("graph-changeset", "3" * 64)

    def preview(self, changeset_ref: StableRef) -> StableRef:
        """返回 presentation navigation ref。"""

        return StableRef("graph-preview", "4" * 64)

    def request_approval(self, changeset_ref: StableRef) -> AsyncOperationRef:
        """在 Impact 成功后用既有 async wait 稳定截断 graph。"""

        return AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="approval",
            operation_id="graph-approval-wait",
        )


def _task6r3_graph_before_impact(services: _Task6R3GraphServices, *, saver=None):
    """经 production build_workflow_graph + InMemorySaver 持久化到 Impact 执行前。"""

    from design_orchestrator.langgraph_graph import build_workflow_graph
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    actual_saver = saver or InMemorySaver()
    graph = build_workflow_graph(services).compile(checkpointer=actual_saver)
    config = {
        "configurable": {
            "thread_id": "task6r3-owner-checkpoint",
            "checkpoint_ns": "",
        }
    }
    initial_state = {
        "checkpoint_contract_version": 2,
        "task_id": "task6r3-owner-checkpoint",
        "phase": "RESOLVE_HOST_CONTEXT",
    }
    graph.invoke(initial_state, config=config)
    pause_id = graph.get_state(config).values["pending_interaction"]["pause_id"]
    graph.invoke(
        Command(
            resume={
                "pause_id": pause_id,
                "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
                "payload": {},
            }
        ),
        config=config,
        interrupt_before=["analyze_impact"],
    )
    return actual_saver, graph, config


def _task6r3_default_services(adapter, artifact_store: _ArtifactStore):
    """构造真实 DefaultWorkflowServices，只在 Impact seam 使用 external adapter。"""

    return DefaultWorkflowServices(
        operation_resolver=OperationResolver((MOVE_V1,)),
        parameter_binder=ParameterBinder(
            MVP_CANONICAL_OPERATIONS,
            MVP_BINDING_RECIPES,
        ),
        artifact_store=artifact_store,
        external_owners=adapter,
    )


def test_task6r3_complete_mismatch_reaches_adapter_but_not_real_impact() -> None:
    """三个合法 refs 的关系错配允许过 graph，但必须由 adapter 在真实 Impact 前拒绝。"""

    import json

    (
        adapter,
        artifact_store,
        _,
        impact_analyzer,
        revision,
        _,
        bound_ref,
    ) = _task6_lineage_case()
    result_42 = _require_freshness_result(adapter, bound_ref)
    revision.revision = "43"
    result_43 = _require_freshness_result(adapter, bound_ref)
    mismatch = OperationFreshnessResult(
        operation_ref=result_42.operation_ref,
        planning_snapshot_ref=result_42.planning_snapshot_ref,
        snapshot_set_ref=result_43.snapshot_set_ref,
    )
    impact_services = _task6r3_default_services(adapter, artifact_store)
    graph_services = _Task6R3GraphServices(
        bound_ref=bound_ref,
        freshness_owner=None,
        freshness_result=mismatch,
        impact_services=impact_services,
    )
    _, graph, config = _task6r3_graph_before_impact(graph_services)
    persisted = graph.get_state(config).values
    restored = json.loads(
        json.dumps(
            {
                field_name: persisted[field_name]
                for field_name in (
                    "operation_ref",
                    "planning_snapshot_ref",
                    "snapshot_set_ref",
                )
            },
            sort_keys=True,
        )
    )
    assert restored["snapshot_set_ref"]["ref_id"] == result_43.snapshot_set_ref.ref_id

    with pytest.raises(ValueError):
        graph.invoke(None, config=config)
    assert len(graph_services.workflow_impact_calls) == 1
    assert impact_analyzer.requests == []


def test_task6r3_rebuilt_adapter_consumes_only_saver_restored_exact_refs() -> None:
    """重建 adapter 后只依赖 saver refs + 同一 owner stores，不依赖旧 adapter 私有 lineage。"""

    import json

    (
        adapter_a,
        artifact_store,
        snapshot_registry,
        impact_store,
        _,
        _,
        semantic_reconstruction,
    ) = _task6_adapter()
    context_ref = adapter_a.ensure_context_freshness(adapter_a.resolve_host_context("task-6"))
    assert isinstance(context_ref, StableRef)
    bound = _task6_bound_operation(context_ref)
    bound_ref = artifact_store.put(
        kind="bound_operation_proposal",
        value=bound,
        content_hash=workflow_artifact_content_hash(bound),
    )
    semantic_reconstruction.operation_ready = True

    services_a = _Task6R3GraphServices(
        bound_ref=bound_ref,
        freshness_owner=adapter_a,
        freshness_result=None,
        impact_services=None,
    )
    saver, graph_a, config = _task6r3_graph_before_impact(services_a)
    snapshot = graph_a.get_state(config)
    persisted = {
        field_name: snapshot.values[field_name]
        for field_name in (
            "operation_ref",
            "planning_snapshot_ref",
            "snapshot_set_ref",
        )
    }
    restored_payload = json.loads(json.dumps(persisted, sort_keys=True))
    restored_refs = {
        field_name: StableRef(**restored_payload[field_name])
        for field_name in persisted
    }

    del graph_a, services_a, adapter_a

    impact_analyzer_b = _CountingImpactAnalyzer()
    adapter_b, *_ = _task6_adapter(
        artifact_store=artifact_store,
        overrides={
            "snapshot_registry": snapshot_registry,
            "impact_store": impact_store,
            "impact_analyzer": impact_analyzer_b,
            "semantic_reconstruction": semantic_reconstruction,
        },
    )
    impact_services_b = _task6r3_default_services(adapter_b, artifact_store)
    services_b = _Task6R3GraphServices(
        bound_ref=bound_ref,
        freshness_owner=None,
        freshness_result=None,
        impact_services=impact_services_b,
    )
    from design_orchestrator.langgraph_graph import build_workflow_graph

    graph_b = build_workflow_graph(services_b).compile(checkpointer=saver)
    graph_b.invoke(None, config=config)

    assert len(services_b.workflow_impact_calls) == 1
    assert len(impact_analyzer_b.requests) == 1
    request = impact_analyzer_b.requests[0]
    assert request.planning_snapshot_ref.snapshot_id == restored_refs[
        "planning_snapshot_ref"
    ].ref_id
    assert request.snapshot_set_ref.snapshot_set_id == restored_refs[
        "snapshot_set_ref"
    ].ref_id
''',
)
