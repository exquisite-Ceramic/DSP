"""Product Front Door 的薄应用 service；业务真相继续由既有 owner 持有。"""

from __future__ import annotations

from design_changeset import canonical_hash
from design_orchestrator import PendingInteractionKind, WorkflowResumeCommand
from design_product_runtime import (
    ProductTaskQueryService,
    ProductTaskQueryState,
    ProductTaskQueryView,
    ProductTaskRequest,
    ProductTaskRequestV2,
)

from .contracts import (
    ConfiguredRevitCandidate,
    SessionBinding,
    SessionBindingV2,
    session_binding_hash_body,
)


class ProductFrontDoorService:
    """协调 server-side Product Front Door seams，不复制任何业务 owner state。"""

    def __init__(
        self,
        *,
        session_binding_reader: object,
        candidate_source: object,
        context_probe: object,
        transport_factory: object,
        query_service: ProductTaskQueryService,
        composition_pool: object,
        reviewed_configuration_validator: object | None = None,
        accepted_input_store: object | None = None,
    ) -> None:
        """保存已注入 seams；构造阶段不得解析 session、打开 Host 或创建 composition。"""

        if query_service is None:
            raise ValueError("query_service must not be None")
        self._session_binding_reader = session_binding_reader
        self._candidate_source = candidate_source
        self._context_probe = context_probe
        self._transport_factory = transport_factory
        self._query_service = query_service
        self._composition_pool = composition_pool
        self._reviewed_configuration_validator = reviewed_configuration_validator
        self._accepted_input_store = accepted_input_store

    def get(self, task_id: str) -> ProductTaskQueryView | None:
        """只委托 host-independent durable query；不得解析 session 或访问 Host。"""

        return self._query_service.get(task_id)

    def submit(
        self,
        request: ProductTaskRequest | ProductTaskRequestV2,
    ) -> ProductTaskQueryView:
        """按 request version 分流；V2 先完成 server accepted-input takeover。"""

        if isinstance(request, ProductTaskRequestV2):
            return self._submit_v2(request)
        if not isinstance(request, ProductTaskRequest):
            raise TypeError("request must be ProductTaskRequest or ProductTaskRequestV2")

        binding = self._resolve_binding(request)
        candidate = self._resolve_current_candidate(binding)
        self._validate_fresh_context(
            command_id=f"front-door-submit:{request.task_id}",
            binding=binding,
            candidate=candidate,
        )

        get_or_create = getattr(self._composition_pool, "get_or_create", None)
        if not callable(get_or_create):
            raise TypeError("composition_pool must provide get_or_create")
        composition = get_or_create(binding=binding, candidate=candidate)
        flow = getattr(composition, "flow", None)
        submit = getattr(flow, "submit", None)
        if not callable(submit):
            raise TypeError("composition must expose flow.submit")
        submit(request)

        view = self._query_service.get(request.task_id)
        self._require_query_identity(view, request, action="submit")
        return view

    def resume_operation_proposal(
        self,
        *,
        task_id: str,
        pause_id: str,
        resume_kind: str,
    ) -> ProductTaskQueryView:
        """只恢复当前 exact Operation Proposal pause，并在触发 runtime 前重验 Host authority。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("FRONT_DOOR_RESUME_INVALID: task_id must be non-blank")
        if not isinstance(pause_id, str) or not pause_id.strip():
            raise ValueError("FRONT_DOOR_RESUME_INVALID: pause_id must be non-blank")
        if not isinstance(resume_kind, str) or not resume_kind.strip():
            raise ValueError("FRONT_DOOR_RESUME_INVALID: resume_kind must be non-blank")

        # request 与 checkpoint/query 必须先从 authoritative durable owners 读取；
        # 在 human-pause authority 未确认前，不得解析 session、访问 Host 或取得 composition。
        request = self._query_service.get_request(task_id)
        current = self._query_service.get(task_id)
        if request is None or current is None:
            raise ValueError(
                "FRONT_DOOR_RESUME_TASK_NOT_FOUND: "
                "exact ProductTask request/checkpoint is unavailable"
            )
        self._require_query_identity(current, request, action="resume")

        if current.state != ProductTaskQueryState.WORKFLOW or current.flow is None:
            raise ValueError(
                "FRONT_DOOR_RESUME_NOT_PENDING: task is not at a workflow human pause"
            )
        checkpoint = current.flow.checkpoint
        pending = checkpoint.pending_interaction
        if pending is None or pending.kind != PendingInteractionKind.OPERATION_PROPOSAL:
            raise ValueError(
                "FRONT_DOOR_RESUME_NOT_PENDING: current pause is not an Operation Proposal"
            )
        if pending.pause_id != pause_id:
            raise ValueError(
                "FRONT_DOOR_RESUME_PAUSE_MISMATCH: pause_id does not match current durable pause"
            )
        if resume_kind not in pending.allowed_resume_kinds:
            raise ValueError(
                "FRONT_DOOR_RESUME_KIND_INVALID: resume_kind is not allowed by current pause"
            )

        binding = self._resolve_binding(request)
        candidate = self._resolve_current_candidate(binding)
        self._validate_fresh_context(
            command_id=f"front-door-resume:{task_id}:{pause_id}",
            binding=binding,
            candidate=candidate,
        )

        get_or_create = getattr(self._composition_pool, "get_or_create", None)
        if not callable(get_or_create):
            raise TypeError("composition_pool must provide get_or_create")
        composition = get_or_create(binding=binding, candidate=candidate)
        flow = getattr(composition, "flow", None)
        resume = getattr(flow, "resume", None)
        if not callable(resume):
            raise TypeError("composition must expose flow.resume")
        resume(
            task_id,
            WorkflowResumeCommand(
                resume_kind=resume_kind,
                payload={},
                pause_id=pause_id,
            ),
        )

        view = self._query_service.get(task_id)
        self._require_query_identity(view, request, action="resume")
        return view



    def _submit_v2(self, request: ProductTaskRequestV2) -> ProductTaskQueryView:
        """验证 exact local V2 binding/reviewed config 后原子接管 immutable input。

        Task 3 只把 V2 task 推进到 durable accepted/start-eligible；cross-Host workflow
        composition 与显式 V2 query contract 分别由后续 Task 负责，因此这里不访问 Host、
        readiness、Gateway 或现有单 Revit composition。
        """

        resolve_session = getattr(self._session_binding_reader, "resolve_session_v2", None)
        if not callable(resolve_session):
            raise TypeError("session_binding_reader must provide resolve_session_v2")
        binding = resolve_session(request.session_ref)
        if binding is None:
            raise ValueError(
                "FRONT_DOOR_SESSION_NOT_FOUND: exact frozen V2 session does not exist"
            )
        if not isinstance(binding, SessionBindingV2):
            raise ValueError(
                "FRONT_DOOR_BINDING_V2_INVALID: session reader returned an invalid binding"
            )
        if (
            request.session_ref != binding.session_ref
            or request.project_id != binding.project_id
            or request.initiating_host_kind != binding.initiating_host_kind
            or request.session_binding_hash != binding.binding_hash
        ):
            raise ValueError(
                "FRONT_DOOR_REQUEST_BINDING_MISMATCH: "
                "V2 request authority does not match frozen session"
            )

        validator = getattr(self._reviewed_configuration_validator, "validate", None)
        if not callable(validator):
            raise TypeError(
                "reviewed_configuration_validator must provide validate for V2 submit"
            )
        validator(binding)

        create_v2 = getattr(self._accepted_input_store, "create_v2", None)
        if not callable(create_v2):
            raise TypeError("accepted_input_store must provide create_v2 for V2 submit")
        create_v2(
            request,
            session_binding_hash=binding.binding_hash,
            session_binding_payload=self._session_binding_v2_payload(binding),
        )

        # 该 view 只投影已持久化 accepted-input owner；它不是 Task 14 的最终 V2 wire
        # contract，也不会伪造尚未创建的 workflow checkpoint。
        return ProductTaskQueryView(
            task_id=request.task_id,
            request_hash=request.request_hash,
            state=ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW,
            flow=None,
        )

    @staticmethod
    def _session_binding_v2_payload(binding: SessionBindingV2) -> dict[str, object]:
        """把完整 V2 binding 投影为 ProductTask owner 可独立恢复的 JSON body。"""

        return {
            "session_ref": binding.session_ref,
            "project_id": binding.project_id,
            "semantic_target_id": binding.semantic_target_id,
            "semantic_environment_id": binding.semantic_environment_id,
            "semantic_environment_hash": binding.semantic_environment_hash,
            "topology_environment_id": binding.topology_environment_id,
            "topology_revision": binding.topology_revision,
            "topology_snapshot_hash": binding.topology_snapshot_hash,
            "initiating_host_kind": binding.initiating_host_kind,
            "members": [
                {
                    "host_kind": member.host_kind,
                    "role": member.role,
                    "configured_reference_id": member.configured_reference_id,
                    "configured_reference_hash": member.configured_reference_hash,
                    "transport_locator": member.transport_locator,
                    "host_instance_id": member.host_instance_id,
                    "document_id": member.document_id,
                    "native_target_id": member.native_target_id,
                    "host_binding_fingerprint": member.host_binding_fingerprint,
                }
                for member in binding.members
            ],
            "binding_hash": binding.binding_hash,
        }

    @staticmethod
    def _require_query_identity(
        view: ProductTaskQueryView | None,
        request: ProductTaskRequest,
        *,
        action: str,
    ) -> None:
        """所有 Host-bound action 完成后只接受与 immutable request 一致的 durable query。"""

        if view is None:
            raise ValueError(
                "FRONT_DOOR_TASK_QUERY_MISSING: "
                f"{action} completed without durable ProductTask query"
            )
        if view.task_id != request.task_id or view.request_hash != request.request_hash:
            raise ValueError(
                "FRONT_DOOR_TASK_QUERY_INTEGRITY_INVALID: "
                "query identity does not match authoritative request"
            )

    def _resolve_binding(self, request: ProductTaskRequest) -> SessionBinding:
        """按 exact session 读取并重新验证 binding hash 与 request authority 关系。"""

        resolve_session = getattr(self._session_binding_reader, "resolve_session", None)
        if not callable(resolve_session):
            raise TypeError("session_binding_reader must provide resolve_session")
        binding = resolve_session(request.session_ref)
        if binding is None:
            raise ValueError(
                "FRONT_DOOR_SESSION_NOT_FOUND: exact frozen session does not exist"
            )
        if not isinstance(binding, SessionBinding):
            # 保留既有 Front Door authority-value 错误契约；adapter 返回错类型时，
            # 仍按无效 authority value 处理。
            raise ValueError(  # noqa: TRY004
                "FRONT_DOOR_BINDING_INVALID: session reader returned an invalid binding"
            )

        expected_hash = canonical_hash(
            session_binding_hash_body(
                session_ref=binding.session_ref,
                project_id=binding.project_id,
                host_kind=binding.host_kind,
                candidate_key=binding.candidate_key,
                candidate_hash=binding.candidate_hash,
                transport_locator=binding.transport_locator,
                host_instance_id=binding.host_instance_id,
                document_id=binding.document_id,
            )
        )
        if binding.binding_hash != expected_hash:
            raise ValueError(
                "FRONT_DOOR_BINDING_HASH_INVALID: "
                "binding_hash does not match authority body"
            )
        if (
            request.session_ref != binding.session_ref
            or request.project_id != binding.project_id
            or request.host_kind != binding.host_kind
        ):
            raise ValueError(
                "FRONT_DOOR_REQUEST_BINDING_MISMATCH: "
                "request authority does not match frozen session"
            )
        return binding

    def _resolve_current_candidate(
        self,
        binding: SessionBinding,
    ) -> ConfiguredRevitCandidate:
        """重新读取 exact candidate，并拒绝 same-key 配置漂移或 binding/candidate 交叉不一致。"""

        get_candidate = getattr(self._candidate_source, "get", None)
        if not callable(get_candidate):
            raise TypeError("candidate_source must provide get")
        candidate = get_candidate(binding.candidate_key)
        if candidate is None:
            raise ValueError(
                "FRONT_DOOR_CANDIDATE_NOT_FOUND: frozen candidate key no longer exists"
            )
        if not isinstance(candidate, ConfiguredRevitCandidate):
            # 保留既有 Front Door authority-value 错误契约；candidate source 错类型时，
            # 不改变公开异常族。
            raise ValueError(  # noqa: TRY004
                "FRONT_DOOR_CANDIDATE_INVALID: "
                "candidate source returned an invalid candidate"
            )
        if candidate.candidate_key != binding.candidate_key:
            raise ValueError(
                "FRONT_DOOR_CANDIDATE_INVALID: "
                "candidate source returned the wrong exact key"
            )
        if candidate.candidate_hash != binding.candidate_hash:
            raise ValueError(
                "FRONT_DOOR_CANDIDATE_DRIFT: "
                "current candidate hash differs from frozen binding"
            )
        if (
            candidate.project_id != binding.project_id
            or candidate.transport_locator != binding.transport_locator
            or candidate.document_id != binding.document_id
        ):
            raise ValueError(
                "FRONT_DOOR_BINDING_CANDIDATE_MISMATCH: "
                "frozen binding does not match candidate authority"
            )
        return candidate

    def _validate_fresh_context(
        self,
        *,
        command_id: str,
        binding: SessionBinding,
        candidate: ConfiguredRevitCandidate,
    ) -> None:
        """fresh probe 必须仍指向 frozen runtime/document 与 configured selected Wall。"""

        if not callable(self._transport_factory):
            raise TypeError("transport_factory must be callable")
        transport = self._transport_factory(binding.transport_locator)
        if not callable(self._context_probe):
            raise TypeError("context_probe must be a callable probe factory")
        probe = self._context_probe(transport)
        discover = getattr(probe, "discover", None)
        if not callable(discover):
            raise TypeError("context_probe must return an object with discover")
        observation = discover(
            command_id=command_id,
            document_id=binding.document_id,
        )
        if observation is None:
            raise ValueError(
                "FRONT_DOOR_CONTEXT_INVALID: context probe returned no observation"
            )
        if (
            getattr(observation, "host_instance_id", None) != binding.host_instance_id
            or getattr(observation, "document_id", None) != binding.document_id
        ):
            raise ValueError(
                "FRONT_DOOR_CONTEXT_INVALID: "
                "fresh runtime/document does not match frozen binding"
            )

        selected_elements = getattr(observation, "selected_elements", None)
        if not isinstance(selected_elements, tuple) or len(selected_elements) != 1:
            raise ValueError(
                "FRONT_DOOR_SELECTION_INVALID: "
                "exactly one configured Wall must be selected"
            )
        selected = selected_elements[0]
        if (
            getattr(selected, "unique_id", None) != candidate.native_target_unique_id
            or getattr(selected, "native_kind", None) != "Wall"
        ):
            raise ValueError(
                "FRONT_DOOR_SELECTION_INVALID: "
                "selected Host target does not match configured Wall"
            )


__all__ = ["ProductFrontDoorService"]
