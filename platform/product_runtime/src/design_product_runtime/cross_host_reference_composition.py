"""Cross-Host Product Vertical 的 exact runtime registry composition seam。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from design_execution_planning import HostRuntimeRef

from .autocad_execution import AutoCadWallThicknessExecutionPort
from .runtime_registry import ExactHostRuntimeRegistry

_REQUIRED_HOST_TYPES = frozenset({"autocad", "revit"})


@dataclass(frozen=True, slots=True)
class CrossHostRuntimePortBinding:
    """一个 exact runtime 同时绑定 readiness 与 execution production port。"""

    runtime_ref: HostRuntimeRef
    readiness_port: object
    execution_port: object

    def __post_init__(self) -> None:
        """只接受当前 vertical 可实际调用的端口 shape。"""

        if not isinstance(self.runtime_ref, HostRuntimeRef):
            raise TypeError("runtime_ref must be HostRuntimeRef")
        if not callable(getattr(self.readiness_port, "check", None)):
            raise TypeError("readiness_port must provide check")
        if not callable(getattr(self.execution_port, "execute", None)):
            raise TypeError("execution_port must provide execute")


@dataclass(frozen=True, slots=True)
class CrossHostRuntimeRegistries:
    """供现有 readiness barrier 与 materialized coordinator 注入的两个 registry。"""

    readiness: ExactHostRuntimeRegistry
    execution: ExactHostRuntimeRegistry


def build_autocad_wall_thickness_runtime_binding(
    runtime_ref: HostRuntimeRef,
    dispatcher,
    *,
    clock=None,
) -> CrossHostRuntimePortBinding:
    """把现有 AutoCAD public dispatcher 组合成 exact readiness/execution runtime binding。"""

    if not isinstance(runtime_ref, HostRuntimeRef):
        raise TypeError("runtime_ref must be HostRuntimeRef")
    if runtime_ref.host_type != "autocad":
        raise ValueError("AutoCAD runtime binding requires host_type='autocad'")

    from autocad_sidecar.execution.readiness import AutoCadWallThicknessReadinessPort
    from autocad_sidecar.execution.wall_thickness import AutoCadWallThicknessMutationPort

    mutation = AutoCadWallThicknessMutationPort(dispatcher)
    return CrossHostRuntimePortBinding(
        runtime_ref=runtime_ref,
        readiness_port=AutoCadWallThicknessReadinessPort(dispatcher),
        execution_port=AutoCadWallThicknessExecutionPort(
            mutation,
            clock=clock,
        ),
    )


class CrossHostVerificationEvidenceRouter:
    """按 exact HostRuntimeRef 路由已有 Host verification evidence adapters。

    该 router 只解决 composition dispatch；不拥有 evidence、admission、readiness 或
    execution authority，也不在构建时触发任何 Host I/O。
    """

    def __init__(
        self,
        entries: Iterable[tuple[HostRuntimeRef, object]],
    ) -> None:
        """冻结 exact runtime→evidence port 映射，并验证最小只读端口 shape。"""

        normalized = []
        for runtime_ref, port in tuple(entries):
            if not isinstance(runtime_ref, HostRuntimeRef):
                raise TypeError("runtime_ref must be HostRuntimeRef")
            if not callable(getattr(port, "build_bundle", None)):
                raise TypeError("evidence port must provide build_bundle")
            if not callable(getattr(port, "build_evidence", None)):
                raise TypeError("evidence port must provide build_evidence")
            normalized.append((runtime_ref, port))
        self._registry = ExactHostRuntimeRegistry(normalized)

    @staticmethod
    def _runtime_from_kwargs(kwargs: dict[str, object]) -> HostRuntimeRef:
        """只从 coordinator 已验证的 ExecutionSlice runtime identity 解析 route。"""

        execution_slice = kwargs.get("execution_slice")
        runtime_ref = getattr(execution_slice, "host_runtime_ref", None)
        if not isinstance(runtime_ref, HostRuntimeRef):
            raise TypeError(
                "execution_slice must expose a HostRuntimeRef host_runtime_ref"
            )
        return runtime_ref

    def build_bundle(self, **kwargs):
        """把独立 READ bundle 构造委托给 exact Host evidence adapter。"""

        port = self._registry.resolve(self._runtime_from_kwargs(kwargs))
        return port.build_bundle(**kwargs)

    def build_evidence(self, **kwargs):
        """把 convergence evidence 构造委托给同一 exact Host adapter。"""

        port = self._registry.resolve(self._runtime_from_kwargs(kwargs))
        return port.build_evidence(**kwargs)


class ProposalDecisionContinuationAdapter:
    """把 Task 5 durable decision owner 适配为 Gate B 的 subject-based continuation port。

    适配器不保存 pause/state 副本，也不做 latest/reverse lookup；它只读取一个 ProductTask
    已冻结的唯一 proposal decision，再校验 exact subject 后调用原 owner transition。
    """

    def __init__(self, decision_store: object) -> None:
        """要求原 owner 提供 exact-task 读取与 Gate-B 原子转移。"""

        if not callable(getattr(decision_store, "get_for_task", None)):
            raise TypeError("decision_store must provide get_for_task")
        if not callable(getattr(decision_store, "invalidate_gate_b", None)):
            raise TypeError("decision_store must provide invalidate_gate_b")
        self._decision_store = decision_store

    @staticmethod
    def _require_subject(record, subject_ref) -> None:
        """确保 exact task 下唯一 durable decision 仍绑定调用方指定 subject。"""

        from design_orchestrator.workflow_contracts import StableRef

        if not isinstance(subject_ref, StableRef):
            raise TypeError("subject_ref must be StableRef")
        if record.subject_ref != subject_ref:
            raise ValueError(
                "PROPOSAL_DECISION_SUBJECT_MISMATCH: "
                "task decision does not match the requested proposal subject"
            )

    def get_by_subject(self, task_id: str, subject_ref):
        """读取 exact task 的唯一 decision，并要求 subject identity 完全一致。"""

        record = self._decision_store.get_for_task(task_id)
        if record is None:
            return None
        self._require_subject(record, subject_ref)
        return record

    def invalidate_gate_b_by_subject(
        self,
        task_id: str,
        subject_ref,
        reason: str,
    ):
        """保留已接受历史，只把同一 durable decision 推进到 STALE_GATE_B。"""

        record = self._decision_store.get_for_task(task_id)
        if record is None:
            raise ValueError(
                "PROPOSAL_DECISION_NOT_FOUND: Gate B requires durable ACCEPT"
            )
        self._require_subject(record, subject_ref)
        return self._decision_store.invalidate_gate_b(
            task_id,
            record.pause_id,
            subject_ref,
            reason,
        )


class _ExactDocumentRevisionObservation:
    """按冻结的 document identity 路由 Host current-revision observation。"""

    def __init__(self, entries: Iterable[tuple[HostRuntimeRef, object]]) -> None:
        """每个 document 只能绑定一个 exact runtime revision port。"""

        values: dict[str, object] = {}
        for runtime_ref, port in tuple(entries):
            if not callable(getattr(port, "current_revision", None)):
                raise TypeError("planning port must provide current_revision")
            document_ref = runtime_ref.document_ref
            if document_ref in values:
                raise ValueError(
                    "PRODUCT_RUNTIME_HOST_RUNTIME_CONFLICT: "
                    "duplicate planning document route"
                )
            values[document_ref] = port
        if not values:
            raise ValueError(
                "PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED: "
                "planning revision routes must not be empty"
            )
        self._values = values

    def current_revision(self, document_ref: str) -> str:
        """只按 exact document identity 解析，不做 host-type/latest fallback。"""

        try:
            port = self._values[document_ref]
        except KeyError as exc:
            raise ValueError(
                "PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED: "
                "exact planning document is not configured"
            ) from exc
        return port.current_revision(document_ref)


class _ExactPlanningMemberReconstruction:
    """按 accepted observation 的 exact runtime identity 路由 reconstruction。"""

    def __init__(self, entries: Iterable[tuple[HostRuntimeRef, object]]) -> None:
        """冻结 runtime→planning port，并验证 reconstruction method。"""

        normalized = []
        for runtime_ref, port in tuple(entries):
            if not callable(getattr(port, "reconstruct_member", None)):
                raise TypeError("planning port must provide reconstruct_member")
            normalized.append((runtime_ref, port))
        self._registry = ExactHostRuntimeRegistry(normalized)

    def reconstruct_member(self, **kwargs):
        """从 accepted observation 构造 exact HostRuntimeRef 后委托原 port。"""

        observation = kwargs.get("accepted_observation")
        host_kind = getattr(observation, "host_kind", None)
        host_instance_id = getattr(observation, "host_instance_id", None)
        document_id = getattr(observation, "document_id", None)
        if not all(
            isinstance(value, str) and value.strip()
            for value in (host_kind, host_instance_id, document_id)
        ):
            raise TypeError(
                "accepted_observation must expose exact host/runtime/document identity"
            )
        runtime_ref = HostRuntimeRef(
            host_type=host_kind.strip().lower(),
            host_instance_id=host_instance_id.strip(),
            document_ref=document_id.strip(),
        )
        port = self._registry.resolve(runtime_ref)
        return port.reconstruct_member(**kwargs)


@dataclass(frozen=True, slots=True)
class CrossHostPlanningComposition:
    """Gate B planning boundary 所需的两个 exact routing seams。"""

    revision_observation: object
    member_reconstruction: object


def build_cross_host_planning_composition(
    entries: Iterable[tuple[HostRuntimeRef, object]],
) -> CrossHostPlanningComposition:
    """构造 exact dual-Host planning routes；构建阶段不触发 Host I/O。"""

    values = tuple(entries)
    if len(values) != 2:
        raise ValueError(
            "CROSS_HOST_PLANNING_RUNTIME_SET_INVALID: exactly two runtimes are required"
        )
    host_types = {
        runtime_ref.host_type
        for runtime_ref, _port in values
        if isinstance(runtime_ref, HostRuntimeRef)
    }
    if host_types != _REQUIRED_HOST_TYPES:
        raise ValueError(
            "CROSS_HOST_PLANNING_RUNTIME_SET_INVALID: "
            "required Host set is AutoCAD + Revit"
        )
    return CrossHostPlanningComposition(
        revision_observation=_ExactDocumentRevisionObservation(values),
        member_reconstruction=_ExactPlanningMemberReconstruction(values),
    )


def build_cross_host_runtime_registries(
    bindings: Iterable[CrossHostRuntimePortBinding],
) -> CrossHostRuntimeRegistries:
    """构造 exact AutoCAD+Revit registries；构建阶段绝不触发 Host I/O。"""

    values = tuple(bindings)
    if len(values) != 2 or any(
        not isinstance(item, CrossHostRuntimePortBinding) for item in values
    ):
        raise ValueError(
            "CROSS_HOST_RUNTIME_SET_INVALID: exactly two runtime bindings are required"
        )
    host_types = {item.runtime_ref.host_type for item in values}
    if host_types != _REQUIRED_HOST_TYPES:
        raise ValueError(
            "CROSS_HOST_RUNTIME_SET_INVALID: required Host set is AutoCAD + Revit"
        )

    readiness = ExactHostRuntimeRegistry(
        (item.runtime_ref, item.readiness_port) for item in values
    )
    execution = ExactHostRuntimeRegistry(
        (item.runtime_ref, item.execution_port) for item in values
    )
    return CrossHostRuntimeRegistries(
        readiness=readiness,
        execution=execution,
    )


__all__ = [
    "CrossHostPlanningComposition",
    "CrossHostRuntimePortBinding",
    "CrossHostRuntimeRegistries",
    "CrossHostVerificationEvidenceRouter",
    "ProposalDecisionContinuationAdapter",
    "build_autocad_wall_thickness_runtime_binding",
    "build_cross_host_planning_composition",
    "build_cross_host_runtime_registries",
]
