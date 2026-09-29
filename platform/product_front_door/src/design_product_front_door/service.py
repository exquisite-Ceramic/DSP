"""Product Front Door 的薄应用 service；业务真相继续由既有 owner 持有。"""

from __future__ import annotations

from design_changeset import canonical_hash
from design_product_runtime import (
    ProductTaskQueryService,
    ProductTaskQueryView,
    ProductTaskRequest,
)

from .contracts import ConfiguredRevitCandidate, SessionBinding, session_binding_hash_body


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

    def get(self, task_id: str) -> ProductTaskQueryView | None:
        """只委托 host-independent durable query；不得解析 session 或访问 Host。"""

        return self._query_service.get(task_id)

    def submit(self, request: ProductTaskRequest) -> ProductTaskQueryView:
        """验证 frozen session/candidate 与 fresh Revit evidence 后委托既有 product flow。"""

        if not isinstance(request, ProductTaskRequest):
            raise TypeError("request must be ProductTaskRequest")

        binding = self._resolve_binding(request)
        candidate = self._resolve_current_candidate(binding)
        self._validate_fresh_context(
            request=request,
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
        if view is None:
            raise ValueError(
                "FRONT_DOOR_TASK_QUERY_MISSING: submit completed without durable ProductTask query"
            )
        if view.task_id != request.task_id or view.request_hash != request.request_hash:
            raise ValueError(
                "FRONT_DOOR_TASK_QUERY_INTEGRITY_INVALID: query identity does not match submitted request"
            )
        return view

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
            raise ValueError(
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
                "FRONT_DOOR_BINDING_HASH_INVALID: binding_hash does not match authority body"
            )
        if (
            request.session_ref != binding.session_ref
            or request.project_id != binding.project_id
            or request.host_kind != binding.host_kind
        ):
            raise ValueError(
                "FRONT_DOOR_REQUEST_BINDING_MISMATCH: request authority does not match frozen session"
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
            raise ValueError(
                "FRONT_DOOR_CANDIDATE_INVALID: candidate source returned an invalid candidate"
            )
        if candidate.candidate_key != binding.candidate_key:
            raise ValueError(
                "FRONT_DOOR_CANDIDATE_INVALID: candidate source returned the wrong exact key"
            )
        if candidate.candidate_hash != binding.candidate_hash:
            raise ValueError(
                "FRONT_DOOR_CANDIDATE_DRIFT: current candidate hash differs from frozen binding"
            )
        if (
            candidate.project_id != binding.project_id
            or candidate.transport_locator != binding.transport_locator
            or candidate.document_id != binding.document_id
        ):
            raise ValueError(
                "FRONT_DOOR_BINDING_CANDIDATE_MISMATCH: frozen binding does not match candidate authority"
            )
        return candidate

    def _validate_fresh_context(
        self,
        *,
        request: ProductTaskRequest,
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
            command_id=f"front-door-submit:{request.task_id}",
            document_id=binding.document_id,
        )
        if observation is None:
            raise ValueError("FRONT_DOOR_CONTEXT_INVALID: context probe returned no observation")
        if (
            getattr(observation, "host_instance_id", None) != binding.host_instance_id
            or getattr(observation, "document_id", None) != binding.document_id
        ):
            raise ValueError(
                "FRONT_DOOR_CONTEXT_INVALID: fresh runtime/document does not match frozen binding"
            )

        selected_elements = getattr(observation, "selected_elements", None)
        if not isinstance(selected_elements, tuple) or len(selected_elements) != 1:
            raise ValueError(
                "FRONT_DOOR_SELECTION_INVALID: exactly one configured Wall must be selected"
            )
        selected = selected_elements[0]
        if (
            getattr(selected, "unique_id", None) != candidate.native_target_unique_id
            or getattr(selected, "native_kind", None) != "Wall"
        ):
            raise ValueError(
                "FRONT_DOOR_SELECTION_INVALID: selected Host target does not match configured Wall"
            )


__all__ = ["ProductFrontDoorService"]
