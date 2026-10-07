"""ProductTask request 与 workflow checkpoint 的 host-independent exact query composition。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from design_execution_coordination import project_execution_recovery
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    ExecutionSagaStoreV2,
    SliceReconciliationStatusV2,
    StoredExecutionSagaV2,
)
from design_orchestrator import PendingInteractionKind, WorkflowCheckpointView
from design_orchestrator.proposal_decision import (
    HumanDecisionState,
    ProposalContinuationState,
    ProposalDecisionRecord,
)

from .accepted_input import AcceptedProductTaskInputV2
from .contracts import (
    ProductMaterializationQueryViewV2,
    ProductProposalStateV2,
    ProductTaskQueryState,
    ProductTaskQueryView,
    ProductTaskQueryViewV2,
    ProductTaskRequest,
    ProductTaskRequestError,
    ProductTaskV2Status,
)
from .wall_thickness_flow import ProductTaskRequestStore, project_wall_thickness_product_flow


class ProductTaskQueryError(RuntimeError):
    """ProductTask query 发现跨 owner lineage 损坏时使用的稳定错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProductTaskCheckpointReadPort(Protocol):
    """query 只依赖 framework-neutral checkpoint 读取，不需要可执行 workflow runtime。"""

    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None:
        """按 exact task_id 读取当前 durable checkpoint。"""

        ...


class ProductTaskQueryService:
    """按冻结读序组合既有 owner truth，不创建、恢复或推进 workflow。"""

    def __init__(
        self,
        *,
        request_store: ProductTaskRequestStore,
        checkpoint_reader: ProductTaskCheckpointReadPort,
        saga_store: ExecutionSagaStoreV2,
        proposal_decision_reader: object | None = None,
        dispatch_intent_reader: object | None = None,
        evidence_reader: object | None = None,
    ) -> None:
        """绑定只读 owner seams；query 自身不持有任何 durable state。"""

        if request_store is None:
            raise ValueError("request_store must not be None")
        if checkpoint_reader is None:
            raise ValueError("checkpoint_reader must not be None")
        if saga_store is None:
            raise ValueError("saga_store must not be None")
        self._request_store = request_store
        self._checkpoint_reader = checkpoint_reader
        self._saga_store = saga_store
        self._proposal_decision_reader = proposal_decision_reader
        self._dispatch_intent_reader = dispatch_intent_reader
        self._evidence_reader = evidence_reader

    def get_request(self, task_id: str) -> ProductTaskRequest | None:
        """只按 exact task_id 读取 immutable request owner，不读取 checkpoint 或 Saga。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ProductTaskQueryError(
                "PRODUCT_TASK_QUERY_INVALID",
                "task_id must be a non-blank string",
            )
        normalized_task_id = task_id.strip()
        request = self._request_store.get(normalized_task_id)
        if request is None:
            return None
        self._require_exact_request(request, normalized_task_id)
        return request

    def get_accepted_input_v2(
        self,
        task_id: str,
    ) -> AcceptedProductTaskInputV2 | None:
        """按 exact task 读取 V2 accepted input；V1/missing task 返回 None。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ProductTaskQueryError(
                "PRODUCT_TASK_QUERY_INVALID",
                "task_id must be a non-blank string",
            )
        normalized_task_id = task_id.strip()
        get_v2 = getattr(self._request_store, "get_v2", None)
        if not callable(get_v2):
            return None
        try:
            accepted = get_v2(normalized_task_id)
        except ProductTaskRequestError as exc:
            if exc.code == "PRODUCT_TASK_REQUEST_VERSION_MISMATCH":
                return None
            raise
        if accepted is None:
            return None
        if (
            not isinstance(accepted, AcceptedProductTaskInputV2)
            or accepted.request.task_id != normalized_task_id
        ):
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "request store returned V2 accepted input for a different task",
            )
        return accepted

    def get_workflow_checkpoint(
        self,
        task_id: str,
    ) -> WorkflowCheckpointView | None:
        """按 exact task 读取 durable workflow navigation，供内部 resume authority 使用。

        该 seam 只转交 Orchestrator checkpoint read owner；不会把 checkpoint 字段复制进
        ProductTaskQueryViewV2，也不会创建、恢复或推进 workflow。
        """

        if not isinstance(task_id, str) or not task_id.strip():
            raise ProductTaskQueryError(
                "PRODUCT_TASK_QUERY_INVALID",
                "task_id must be a non-blank string",
            )
        return self._checkpoint_reader.get_checkpoint(task_id.strip())

    def get(
        self,
        task_id: str,
    ) -> ProductTaskQueryView | ProductTaskQueryViewV2 | None:
        """执行 request→checkpoint→必要时 request 稳定化重读的冻结查询顺序。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ProductTaskQueryError(
                "PRODUCT_TASK_QUERY_INVALID",
                "task_id must be a non-blank string",
            )
        normalized_task_id = task_id.strip()

        accepted_v2 = self.get_accepted_input_v2(normalized_task_id)
        if accepted_v2 is not None:
            return self._get_v2(accepted_v2)

        request = self._request_store.get(normalized_task_id)
        checkpoint = self._checkpoint_reader.get_checkpoint(normalized_task_id)

        if request is None and checkpoint is None:
            return None

        if request is not None and checkpoint is None:
            self._require_exact_request(request, normalized_task_id)
            return ProductTaskQueryView(
                task_id=request.task_id,
                request_hash=request.request_hash,
                state=ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW,
                flow=None,
            )

        if checkpoint is None:
            # 前两个分支已经覆盖 checkpoint=None；保留防御性不可达保护。
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "checkpoint state changed unexpectedly during query",
            )

        if request is None:
            # request/checkpoint 分属独立 durable owner。checkpoint 读取期间 request 可能刚提交，
            # 因此必须在判定 corruption 前做一次 exact task stabilization re-read。
            request = self._request_store.get(normalized_task_id)
            if request is None:
                raise ProductTaskQueryError(
                    "PRODUCT_TASK_LINEAGE_INVALID",
                    "workflow checkpoint exists without authoritative ProductTask request",
                )

        self._require_exact_request(request, normalized_task_id)
        if checkpoint.task_id != normalized_task_id:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "workflow checkpoint task_id does not match authoritative request",
            )

        flow = project_wall_thickness_product_flow(checkpoint, self._saga_store)
        return ProductTaskQueryView(
            task_id=request.task_id,
            request_hash=request.request_hash,
            state=ProductTaskQueryState.WORKFLOW,
            flow=flow,
        )


    def _get_v2(
        self,
        accepted: AcceptedProductTaskInputV2,
    ) -> ProductTaskQueryViewV2:
        """按 accepted→checkpoint/decision→Saga/dispatch→evidence 的冻结顺序投影。"""

        request = accepted.request
        checkpoint = self._checkpoint_reader.get_checkpoint(request.task_id)
        if checkpoint is None:
            return ProductTaskQueryViewV2(
                version="V2",
                task_id=request.task_id,
                request_hash=request.request_hash,
                state=ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW,
                status=ProductTaskV2Status.WAITING,
                proposal_state=None,
                saga_id=None,
                convergence_result_hash=None,
                materializations=(),
            )
        if checkpoint.task_id != request.task_id:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "workflow checkpoint task_id does not match authoritative V2 request",
            )

        proposal_state = self._proposal_state(request.task_id, checkpoint)
        if proposal_state in {
            ProductProposalStateV2.STALE_GATE_A,
            ProductProposalStateV2.STALE_GATE_B,
        }:
            return ProductTaskQueryViewV2(
                version="V2",
                task_id=request.task_id,
                request_hash=request.request_hash,
                state=ProductTaskQueryState.WORKFLOW,
                status=ProductTaskV2Status.STALE,
                proposal_state=proposal_state,
                saga_id=checkpoint.saga_id,
                convergence_result_hash=None,
                materializations=(),
            )
        if (
            proposal_state is ProductProposalStateV2.REJECTED
            or checkpoint.phase.value == "CANCELLED"
        ):
            return ProductTaskQueryViewV2(
                version="V2",
                task_id=request.task_id,
                request_hash=request.request_hash,
                state=ProductTaskQueryState.WORKFLOW,
                status=ProductTaskV2Status.CANCELLED,
                proposal_state=proposal_state,
                saga_id=checkpoint.saga_id,
                convergence_result_hash=None,
                materializations=(),
            )

        if checkpoint.saga_id is None:
            status = (
                ProductTaskV2Status.FAILED
                if checkpoint.phase.value == "FAILED"
                else ProductTaskV2Status.WAITING
            )
            return ProductTaskQueryViewV2(
                version="V2",
                task_id=request.task_id,
                request_hash=request.request_hash,
                state=ProductTaskQueryState.WORKFLOW,
                status=status,
                proposal_state=proposal_state,
                saga_id=None,
                convergence_result_hash=None,
                materializations=(),
            )

        saga = self._saga_store.get_saga(checkpoint.saga_id)
        if saga is None or not isinstance(saga, StoredExecutionSagaV2):
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "checkpoint Saga locator is unresolved",
            )
        if saga.definition.saga_id != checkpoint.saga_id:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "Saga owner returned a different durable identity",
            )

        materializations, has_recovery = self._project_materializations(
            accepted,
            saga,
        )
        status = self._aggregate_v2_status(
            checkpoint_phase=checkpoint.phase.value,
            saga=saga,
            has_recovery=has_recovery,
        )
        return ProductTaskQueryViewV2(
            version="V2",
            task_id=request.task_id,
            request_hash=request.request_hash,
            state=ProductTaskQueryState.WORKFLOW,
            status=status,
            proposal_state=proposal_state,
            saga_id=saga.definition.saga_id,
            convergence_result_hash=saga.convergence_result_hash,
            materializations=materializations,
        )

    def _proposal_state(
        self,
        task_id: str,
        checkpoint: WorkflowCheckpointView,
    ) -> ProductProposalStateV2 | None:
        """从 proposal owner 投影 human/stale history；pending checkpoint 只表示尚未决定。"""

        record = None
        if self._proposal_decision_reader is not None:
            getter = getattr(
                self._proposal_decision_reader,
                "get_for_task",
                None,
            )
            if not callable(getter):
                raise TypeError(
                    "proposal_decision_reader must provide get_for_task"
                )
            record = getter(task_id)
            if record is not None and not isinstance(
                record,
                ProposalDecisionRecord,
            ):
                raise ProductTaskQueryError(
                    "PRODUCT_TASK_LINEAGE_INVALID",
                    "proposal decision reader returned an invalid record",
                )

        if record is not None:
            if record.task_id != task_id:
                raise ProductTaskQueryError(
                    "PRODUCT_TASK_LINEAGE_INVALID",
                    "proposal decision belongs to a different ProductTask",
                )
            if (
                record.continuation
                is ProposalContinuationState.STALE_GATE_A
            ):
                return ProductProposalStateV2.STALE_GATE_A
            if (
                record.continuation
                is ProposalContinuationState.STALE_GATE_B
            ):
                return ProductProposalStateV2.STALE_GATE_B
            if record.human_decision is HumanDecisionState.ACCEPTED:
                return ProductProposalStateV2.ACCEPTED
            if record.human_decision is HumanDecisionState.REJECTED:
                return ProductProposalStateV2.REJECTED

        pending = checkpoint.pending_interaction
        if (
            pending is not None
            and pending.kind is PendingInteractionKind.OPERATION_PROPOSAL
        ):
            return ProductProposalStateV2.AWAITING
        return None

    @staticmethod
    def _binding_members(
        accepted: AcceptedProductTaskInputV2,
    ) -> tuple[Mapping[str, object], ...]:
        """读取 server-owned binding body；不回到 client SQLite/config。"""

        payload = accepted.session_binding_payload
        raw_members = payload.get("members")
        if not isinstance(raw_members, list) or len(raw_members) != 2:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "accepted V2 binding must contain exactly two Host members",
            )
        members = tuple(
            item for item in raw_members if isinstance(item, Mapping)
        )
        if len(members) != 2:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "accepted V2 binding contains invalid Host member bodies",
            )
        return members

    def _dispatch_for_slice(self, saga_id: str, slice_hash: str):
        """按 exact Saga/Slice 读取 durable dispatch；绝不 probe Host。"""

        if self._dispatch_intent_reader is None:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_QUERY_NOT_CONFIGURED",
                "V2 Saga query requires a durable dispatch reader",
            )
        getter = getattr(
            self._dispatch_intent_reader,
            "get_for_saga_slice",
            None,
        )
        if not callable(getter):
            raise TypeError(
                "dispatch_intent_reader must provide get_for_saga_slice"
            )
        return getter(saga_id, slice_hash)

    def _member_for_state(self, members, state, dispatch):
        """通过 durable runtime identity 把 Slice 对应到 accepted binding member。"""

        host_instance_id = state.admitted_host_instance_id
        document_ref = None
        if dispatch is not None:
            if (
                host_instance_id is not None
                and dispatch.host_instance_id != host_instance_id
            ):
                raise ProductTaskQueryError(
                    "PRODUCT_TASK_LINEAGE_INVALID",
                    "dispatch Host identity conflicts with admitted Saga state",
                )
            host_instance_id = dispatch.host_instance_id
            document_ref = dispatch.document_ref
        if host_instance_id is None:
            return None

        matches = tuple(
            item
            for item in members
            if item.get("host_instance_id") == host_instance_id
            and (
                document_ref is None
                or item.get("document_id") == document_ref
            )
        )
        if len(matches) != 1:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "Saga/dispatch runtime does not resolve to one accepted binding member",
            )
        return matches[0]

    @staticmethod
    def _canonical_revision(value: object, field_name: str) -> int | None:
        """把 owner text revision 严格投影为非负整数。"""

        if value is None:
            return None
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        if (
            isinstance(value, str)
            and value
            and value.isdigit()
            and (value == "0" or not value.startswith("0"))
        ):
            return int(value)
        raise ProductTaskQueryError(
            "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
            f"{field_name} is not a canonical non-negative revision",
        )

    def _require_evidence_reader(self):
        """V2 published evidence hash 必须能解析到 reconciliation owner body。"""

        if self._evidence_reader is None:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_QUERY_NOT_CONFIGURED",
                "V2 evidence projection requires reconciliation evidence reader",
            )
        return self._evidence_reader

    def _project_materializations(
        self,
        accepted: AcceptedProductTaskInputV2,
        saga: StoredExecutionSagaV2,
    ) -> tuple[tuple[ProductMaterializationQueryViewV2, ...], bool]:
        """按 immutable Saga Slice 顺序投影两侧 Host facts 与 evidence lineage。"""

        members = self._binding_members(accepted)
        semantic_target_id = accepted.session_binding_payload.get(
            "semantic_target_id"
        )
        if not isinstance(semantic_target_id, str) or not semantic_target_id:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "accepted binding semantic target is unavailable",
            )

        projected: list[ProductMaterializationQueryViewV2] = []
        has_recovery = False
        for state in saga.slice_states:
            dispatch = self._dispatch_for_slice(
                saga.definition.saga_id,
                state.execution_slice_hash,
            )
            try:
                recovery = project_execution_recovery(
                    saga,
                    state.execution_slice_hash,
                    dispatch,
                )
            except (TypeError, ValueError) as exc:
                raise ProductTaskQueryError(
                    "PRODUCT_TASK_LINEAGE_INVALID",
                    "Saga/dispatch recovery lineage is inconsistent",
                ) from exc
            disposition = (
                None
                if recovery.disposition is None
                else recovery.disposition.value
            )
            has_recovery = has_recovery or disposition is not None
            member = self._member_for_state(members, state, dispatch)

            delta = None
            verification = None
            bundle = None
            if state.actual_delta_hash is not None:
                reader = self._require_evidence_reader()
                delta = reader.get_actual_delta(state.actual_delta_hash)
                if delta is None:
                    raise ProductTaskQueryError(
                        "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                        "Saga published ActualDelta hash without durable body",
                    )
                if (
                    delta.actual_delta_hash != state.actual_delta_hash
                    or delta.execution_slice_hash
                    != state.execution_slice_hash
                    or delta.changeset_hash != saga.definition.changeset_hash
                    or delta.approved_scope_hash
                    != saga.definition.approved_scope_hash
                    or (
                        state.binding_set_hash is not None
                        and delta.binding_set_hash != state.binding_set_hash
                    )
                    or (
                        state.grant_hash is not None
                        and delta.grant_hash != state.grant_hash
                    )
                ):
                    raise ProductTaskQueryError(
                        "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                        "ActualDelta body does not join exact Saga Slice lineage",
                    )

            if state.verification_hash is not None:
                reader = self._require_evidence_reader()
                verification = reader.get_verification_result(
                    state.verification_hash
                )
                if verification is None:
                    raise ProductTaskQueryError(
                        "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                        "Saga published verification hash without durable body",
                    )
                if (
                    verification.verification_hash
                    != state.verification_hash
                    or verification.execution_slice_hash
                    != state.execution_slice_hash
                    or verification.actual_delta_hash
                    != state.actual_delta_hash
                    or verification.changeset_hash
                    != saga.definition.changeset_hash
                ):
                    raise ProductTaskQueryError(
                        "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                        "verification body does not join exact Saga Slice lineage",
                    )
                bundle = reader.get_verification_bundle(
                    verification.evidence_bundle_hash
                )
                if bundle is None:
                    raise ProductTaskQueryError(
                        "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                        "verification result references a missing durable bundle",
                    )
                if (
                    bundle.evidence_bundle_hash
                    != verification.evidence_bundle_hash
                    or bundle.execution_slice_hash
                    != state.execution_slice_hash
                    or bundle.actual_delta_hash != state.actual_delta_hash
                    or bundle.changeset_hash
                    != saga.definition.changeset_hash
                ):
                    raise ProductTaskQueryError(
                        "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                        "verification bundle does not join exact Slice evidence",
                    )

            if (
                state.status is SliceReconciliationStatusV2.SUCCEEDED
                and (delta is None or verification is None or bundle is None)
            ):
                raise ProductTaskQueryError(
                    "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                    "succeeded V2 Slice lacks mandatory durable evidence bodies",
                )

            expected_revision = self._canonical_revision(
                None if dispatch is None else dispatch.expected_host_revision,
                "dispatch expected_host_revision",
            )
            if expected_revision is None and delta is not None:
                expected_revision = delta.revision_before
            committed_revision = None if delta is None else delta.revision_after
            observed_revision = (
                None
                if bundle is None
                else self._canonical_revision(
                    bundle.base_host_revision,
                    "verification bundle base_host_revision",
                )
            )
            if (
                committed_revision is not None
                and observed_revision is not None
                and committed_revision != observed_revision
            ):
                raise ProductTaskQueryError(
                    "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                    "verification READ revision differs from committed revision",
                )

            verified_thickness = None
            if bundle is not None:
                subjects = tuple(
                    item
                    for item in bundle.subject_evidence
                    if item.semantic_id == semantic_target_id
                )
                if len(subjects) != 1:
                    raise ProductTaskQueryError(
                        "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                        "verification bundle does not contain one target subject",
                    )
                thickness = subjects[0].properties.get("dsp:WallThickness")
                if not isinstance(thickness, Mapping):
                    raise ProductTaskQueryError(
                        "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                        "verification bundle lacks measured wall thickness",
                    )
                value = thickness.get("value")
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or thickness.get("unit") != "mm"
                    or float(value) <= 0
                ):
                    raise ProductTaskQueryError(
                        "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID",
                        "verified wall thickness is not a positive mm value",
                    )
                verified_thickness = float(value)

            projected.append(
                ProductMaterializationQueryViewV2(
                    host_kind=(
                        None if member is None else member.get("host_kind")
                    ),
                    host_instance_id=(
                        None
                        if member is None
                        else member.get("host_instance_id")
                    ),
                    document_id=(
                        None if member is None else member.get("document_id")
                    ),
                    native_target_id=(
                        None
                        if member is None
                        else member.get("native_target_id")
                    ),
                    semantic_target_id=semantic_target_id,
                    materialization_id=state.materialization_id,
                    execution_slice_hash=state.execution_slice_hash,
                    status=state.status.value,
                    expected_revision=expected_revision,
                    committed_revision=committed_revision,
                    observed_revision=observed_revision,
                    verified_thickness_mm=verified_thickness,
                    actual_delta_hash=state.actual_delta_hash,
                    verification_hash=state.verification_hash,
                    evidence_bundle_hash=(
                        None
                        if verification is None
                        else verification.evidence_bundle_hash
                    ),
                    convergence_result_hash=saga.convergence_result_hash,
                    recovery_disposition=disposition,
                    evidence_unavailable_reason=(
                        "VERIFICATION_NOT_PUBLISHED"
                        if delta is not None and state.verification_hash is None
                        else None
                    ),
                )
            )
        return tuple(projected), has_recovery

    @staticmethod
    def _aggregate_v2_status(
        *,
        checkpoint_phase: str,
        saga: StoredExecutionSagaV2,
        has_recovery: bool,
    ) -> ProductTaskV2Status:
        """unresolved dispatch 优先于 Saga convenience status；成功只来自 terminal Saga。"""

        if has_recovery:
            return ProductTaskV2Status.RECOVERY_REQUIRED
        terminal = {
            ExecutionSagaStatusV2.SUCCEEDED: ProductTaskV2Status.SUCCEEDED,
            ExecutionSagaStatusV2.FAILED: ProductTaskV2Status.FAILED,
            ExecutionSagaStatusV2.PARTIALLY_COMMITTED: (
                ProductTaskV2Status.PARTIALLY_COMMITTED
            ),
            ExecutionSagaStatusV2.DIVERGED: ProductTaskV2Status.DIVERGED,
        }.get(saga.status)
        if terminal is not None:
            return terminal
        if any(
            state.actual_delta_hash is not None
            for state in saga.slice_states
        ):
            return ProductTaskV2Status.RECOVERY_REQUIRED
        if checkpoint_phase == "FAILED":
            return ProductTaskV2Status.FAILED
        return ProductTaskV2Status.WAITING

    @staticmethod
    def _require_exact_request(request: ProductTaskRequest, task_id: str) -> None:
        """防御异常 adapter 返回错误 task body，禁止 query 靠调用 locator 猜测修正。"""

        if not isinstance(request, ProductTaskRequest) or request.task_id != task_id:
            raise ProductTaskQueryError(
                "PRODUCT_TASK_LINEAGE_INVALID",
                "request store returned a ProductTask request for a different task",
            )


__all__ = [
    "ProductTaskCheckpointReadPort",
    "ProductTaskQueryError",
    "ProductTaskQueryService",
]
