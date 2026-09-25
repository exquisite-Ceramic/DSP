"""Revit 墙厚产品 vertical 的 request-aware semantic composition boundary。"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from design_orchestrator.workflow_contracts import StableRef
from revit_sidecar import RevitContextObservation
from semantic_runtime import (
    AspectGuarantee,
    AssuranceLevel,
    CoverageState,
    FreshnessContract,
    HostBinding,
    IdentityRegistry,
    ReconstructionResult,
    SemanticAspect,
    SemanticDepth,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
)

from .contracts import ProductTaskRequest


class ProductTaskRequestReadPort(Protocol):
    """按 exact task id 读取 immutable ProductTask request 的最小边界。"""

    def get(self, task_id: str) -> ProductTaskRequest | None: ...


class RevitContextObservationPort(Protocol):
    """读取当前 Revit Host context evidence 的最小边界。"""

    def read(
        self,
        *,
        command_id: str,
        document_id: str,
        host_instance_id: str,
    ) -> RevitContextObservation: ...


class RevitSnapshotReadPort(Protocol):
    """读取 exact Revit Wall revision 的窄接口；严格校验仍由 Host adapter 持有。"""

    def read(
        self,
        *,
        command_id: str,
        document_id: str,
        host_instance_id: str,
        wall_unique_id: str,
        expected_revision: int,
    ) -> object: ...


class DesignFactNormalizationPort(Protocol):
    """把 Host-native snapshot 转成 normalized design facts 的窄接口。"""

    def normalize_snapshot(self, payload: Mapping[str, object]) -> object: ...


class SemanticProjectionPort(Protocol):
    """通过已 pin SemanticEnvironment 执行真实 facts projection。"""

    def project_facts(self, facts: object, environment_id: str) -> tuple[object, ...]: ...


class SemanticEnvironmentView(Protocol):
    """Product composition 只消费 SemanticEnvironment 的 immutable public identity。"""

    environment_id: str
    content_hash: str
    providers: tuple[object, ...]


class RevitSemanticBoundaryError(ValueError):
    """产品 request 与 authoritative Revit/semantic evidence 无法安全关联。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _CapturedContext:
    """一次 exact re-read 的瞬时结果；只在当前调用栈内使用，不作为持久 authority。"""

    request: ProductTaskRequest
    observation: RevitContextObservation
    binding: HostBinding
    digest: str


def _required_text(value: object, field_name: str) -> str:
    """规范化 composition-owned identity，并拒绝空白值。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


def _optional_text(value: object) -> str | None:
    """把 provider/claim 的可选文本规范成稳定 JSON 值。"""

    if value is None:
        return None
    return _required_text(value, "optional text")


def _json_safe(value: object) -> object:
    """把 semantic claim value 约束到 canonical JSON 可哈希形状。"""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("semantic claim value must be finite")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("semantic claim object keys must be strings")
            normalized[key] = _json_safe(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    raise ValueError(f"semantic claim value is not JSON-compatible: {type(value).__name__}")


def _canonical_hash(payload: object) -> str:
    """对 application composition lineage 计算稳定 canonical SHA-256。"""

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _context_hash(
    *,
    request: ProductTaskRequest,
    observation: RevitContextObservation,
    semantic_id: str,
    native_id: str,
    native_kind: str,
) -> str:
    """对 request lineage + exact Host observation + semantic binding 计算规范哈希。"""

    return _canonical_hash(
        {
            "task_id": request.task_id,
            "request_hash": request.request_hash,
            "project_id": request.project_id,
            "session_ref": request.session_ref,
            "document_id": observation.document_id,
            "document_title": observation.document_title,
            "host_instance_id": observation.host_instance_id,
            "revision": observation.revision,
            "semantic_id": semantic_id,
            "native_id": native_id,
            "native_kind": native_kind,
        }
    )


def _claim_payload(claim: object) -> dict[str, object]:
    """只序列化 SemanticService public claim fields，不引入 provider-specific DTO。"""

    return {
        "subject": _required_text(getattr(claim, "subject", None), "claim.subject"),
        "predicate": _optional_text(getattr(claim, "predicate", None)),
        "canonical_term_id": _optional_text(getattr(claim, "canonical_term_id", None)),
        "value": _json_safe(getattr(claim, "value", None)),
        "unit": _optional_text(getattr(claim, "unit", None)),
        "assurance": _required_text(getattr(claim, "assurance", None), "claim.assurance"),
        "provenance": list(getattr(claim, "provenance", ())),
        "evidence": list(getattr(claim, "evidence", ())),
        "provider_id": _optional_text(getattr(claim, "provider_id", None)),
        "provider_version": _optional_text(getattr(claim, "provider_version", None)),
    }


def _strongest_claim_assurance(claims: tuple[object, ...]) -> AssuranceLevel | None:
    """把 provider claim assurance 映射到 D5 progressive assurance，未知值 fail closed。"""

    if not claims:
        return None
    levels: list[AssuranceLevel] = []
    for claim in claims:
        assurance = _required_text(
            getattr(claim, "assurance", None),
            "claim.assurance",
        ).upper()
        try:
            levels.append(AssuranceLevel[assurance])
        except KeyError as exc:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_SEMANTIC_ASSURANCE_UNKNOWN",
                f"semantic projection returned unsupported assurance {assurance!r}",
            ) from exc
    return max(levels)


def _claim_uses_fact(claim: object, fact_ids: set[str]) -> bool:
    """用 design-fact evidence 证明 claim 来自本次 exact snapshot，而非旁路状态。"""

    evidence = {
        item
        for item in getattr(claim, "evidence", ())
        if isinstance(item, str)
    }
    return any(f"design-fact:{fact_id}" in evidence for fact_id in fact_ids)


def _fact_ids_for_kind(facts: object, kind: str) -> set[str]:
    """从真实 NormalizedDesignFactBatch 中提取指定 fact kind 的稳定 ids。"""

    result: set[str] = set()
    for fact in getattr(facts, "facts", ()):
        fact_kind = getattr(getattr(fact, "fact_kind", None), "value", None)
        fact_id = getattr(fact, "fact_id", None)
        if fact_kind == kind and isinstance(fact_id, str) and fact_id:
            result.add(fact_id)
    return result


class RevitWallThicknessSemanticBoundary:
    """把 immutable ProductTask request 与 authoritative Revit/semantic evidence 组合起来。

    context capture/recovery 与 semantic reconstruction 都只做 application composition；canonical
    classification、property mapping 与 freshness 判断继续由真实 SemanticService / D5 owner 持有。
    """

    _REF_PREFIX = "revit-context:"

    def __init__(
        self,
        *,
        request_store: ProductTaskRequestReadPort,
        context_reader: RevitContextObservationPort,
        identity_registry: IdentityRegistry,
        session_ref: str,
        document_id: str,
        host_instance_id: str,
        snapshot_reader: RevitSnapshotReadPort | None = None,
        design_fact_adapter: DesignFactNormalizationPort | None = None,
        semantic_service: SemanticProjectionPort | None = None,
        semantic_environment: SemanticEnvironmentView | None = None,
    ) -> None:
        """显式注入 environment-owned identity 与 owner ports；reconstruction 依赖可延后配置。"""

        if request_store is None or not callable(getattr(request_store, "get", None)):
            raise TypeError("request_store must provide get")
        if context_reader is None or not callable(getattr(context_reader, "read", None)):
            raise TypeError("context_reader must provide read")
        if not isinstance(identity_registry, IdentityRegistry):
            raise TypeError("identity_registry must be an IdentityRegistry")
        if snapshot_reader is not None and not callable(getattr(snapshot_reader, "read", None)):
            raise TypeError("snapshot_reader must provide read")
        if design_fact_adapter is not None and not callable(
            getattr(design_fact_adapter, "normalize_snapshot", None)
        ):
            raise TypeError("design_fact_adapter must provide normalize_snapshot")
        if semantic_service is not None and not callable(
            getattr(semantic_service, "project_facts", None)
        ):
            raise TypeError("semantic_service must provide project_facts")
        if semantic_environment is not None:
            _required_text(
                getattr(semantic_environment, "environment_id", None),
                "semantic_environment.environment_id",
            )
            _required_text(
                getattr(semantic_environment, "content_hash", None),
                "semantic_environment.content_hash",
            )

        self._request_store = request_store
        self._context_reader = context_reader
        self._identity_registry = identity_registry
        self._session_ref = _required_text(session_ref, "session_ref")
        self._document_id = _required_text(document_id, "document_id")
        self._host_instance_id = _required_text(host_instance_id, "host_instance_id")
        self._snapshot_reader = snapshot_reader
        self._design_fact_adapter = design_fact_adapter
        self._semantic_service = semantic_service
        self._semantic_environment = semantic_environment

    def _capture(self, task_id: str) -> _CapturedContext:
        """从 durable request + fresh Host READ + existing identity binding 重建一次 exact context。"""

        normalized_task_id = _required_text(task_id, "task_id")
        request = self._request_store.get(normalized_task_id)
        if request is None:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_REQUEST_UNAVAILABLE",
                "exact ProductTask request is unavailable",
            )
        if not isinstance(request, ProductTaskRequest) or request.task_id != normalized_task_id:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_REQUEST_MISMATCH",
                "request store did not return the exact ProductTask request",
            )
        if request.session_ref != self._session_ref:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_SESSION_MISMATCH",
                "ProductTask session_ref does not match the configured Revit session",
            )

        command_suffix = sha256(
            f"{request.task_id}\n{request.request_hash}".encode()
        ).hexdigest()[:24]
        observation = self._context_reader.read(
            command_id=f"PRODUCT-CONTEXT-{command_suffix}",
            document_id=self._document_id,
            host_instance_id=self._host_instance_id,
        )
        if not isinstance(observation, RevitContextObservation):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_INVALID",
                "context reader must return RevitContextObservation",
            )
        if (
            observation.document_id != self._document_id
            or observation.host_instance_id != self._host_instance_id
        ):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_MISMATCH",
                "Revit context observation does not match configured document/runtime identity",
            )
        if len(observation.selected_elements) != 1:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_SELECTION_INVALID",
                "Revit product selection must contain exactly one element",
            )

        selected = observation.selected_elements[0]
        if selected.native_kind != "Wall":
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_TARGET_NOT_WALL",
                "selected Revit native entity must be Wall",
            )

        binding = self._identity_registry.by_host(
            "revit",
            observation.document_id,
            selected.unique_id,
        )
        if binding is None:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_IDENTITY_UNRESOLVED",
                "selected Revit entity has no existing semantic identity binding",
            )
        if (
            binding.host_type != "revit"
            or binding.document_id != observation.document_id
            or binding.native_id != selected.unique_id
            or binding.native_kind != "Wall"
        ):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_IDENTITY_MISMATCH",
                "resolved semantic identity binding does not match exact Revit Wall evidence",
            )

        digest = _context_hash(
            request=request,
            observation=observation,
            semantic_id=binding.semantic_id,
            native_id=binding.native_id,
            native_kind=binding.native_kind,
        )
        return _CapturedContext(
            request=request,
            observation=observation,
            binding=binding,
            digest=digest,
        )

    def _reconstruction_dependencies(self):
        """只有 reconstruction 路径要求额外 collaborators；context-only 调用保持向后兼容。"""

        dependencies = (
            self._snapshot_reader,
            self._design_fact_adapter,
            self._semantic_service,
            self._semantic_environment,
        )
        if any(item is None for item in dependencies):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_RECONSTRUCTION_UNCONFIGURED",
                "semantic reconstruction dependencies are not fully configured",
            )
        return dependencies

    def _exact_revit_binding(self, semantic_id: str) -> HostBinding:
        """按 contract semantic root 解析唯一 exact Revit Wall binding，禁止 latest/reverse fallback。"""

        bindings = tuple(
            item
            for item in self._identity_registry.host_bindings(semantic_id)
            if item.host_type == "revit"
            and item.document_id == self._document_id
            and item.native_kind == "Wall"
        )
        if len(bindings) != 1:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_RECONSTRUCTION_BINDING_INVALID",
                "semantic root requires exactly one Revit Wall identity binding",
            )
        return bindings[0]

    def resolve_host_context(self, task_id: str) -> StableRef:
        """按 exact task request 捕获当前 Revit selection 并返回 content-addressed context ref。"""

        captured = self._capture(task_id)
        return StableRef(
            f"{self._REF_PREFIX}{captured.request.task_id}",
            captured.digest,
        )

    def load_context_inputs(self, context_ref: StableRef):
        """fresh re-read 后仅在 context ref 完全匹配时重建 freshness 输入。"""

        if not isinstance(context_ref, StableRef):
            raise TypeError("context_ref must be StableRef")
        if not context_ref.ref_id.startswith(self._REF_PREFIX):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_REF_INVALID",
                "context ref is not owned by the Revit product semantic boundary",
            )
        task_id = context_ref.ref_id[len(self._REF_PREFIX) :]
        if not task_id.strip():
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_REF_INVALID",
                "context ref does not contain an exact task id",
            )

        captured = self._capture(task_id)
        rebuilt_ref = StableRef(
            f"{self._REF_PREFIX}{captured.request.task_id}",
            captured.digest,
        )
        if rebuilt_ref != context_ref:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_HASH_MISMATCH",
                "Revit context hash mismatch after authoritative Host re-read",
            )

        # 避免 product_runtime 在 import-time 绑定完整 orchestrator composition；这里只构造其窄输入 DTO。
        from design_orchestrator.canonical_owner_ports import ContextFreshnessInputs

        return ContextFreshnessInputs(
            task_id=captured.request.task_id,
            project_id=captured.request.project_id,
            document_ref=captured.observation.document_id,
            root_entities=(captured.binding.semantic_id,),
        )

    def reconstruct(
        self,
        contract: object,
        expected_host_revision: str,
    ) -> ReconstructionResult:
        """从 exact HostBinding + strict snapshot READ 重建真实 provider-backed semantic evidence。"""

        if not isinstance(contract, FreshnessContract):
            raise TypeError("contract must be FreshnessContract")
        if contract.coverage.document_ref != self._document_id:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_RECONSTRUCTION_DOCUMENT_MISMATCH",
                "freshness contract document does not match configured Revit document",
            )
        if len(contract.coverage.root_entities) != 1:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_RECONSTRUCTION_COVERAGE_INVALID",
                "wall-thickness reconstruction requires exactly one semantic root",
            )

        revision_text = _required_text(expected_host_revision, "expected_host_revision")
        if not revision_text.isdecimal():
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_RECONSTRUCTION_REVISION_INVALID",
                "expected Host revision must be a canonical non-negative integer",
            )
        revision = int(revision_text)
        if str(revision) != revision_text:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_RECONSTRUCTION_REVISION_INVALID",
                "expected Host revision must use canonical decimal form",
            )

        snapshot_reader, design_fact_adapter, semantic_service, semantic_environment = (
            self._reconstruction_dependencies()
        )
        binding = self._exact_revit_binding(contract.coverage.root_entities[0])
        command_suffix = sha256(
            f"{contract.hash}\n{revision_text}\n{binding.native_id}".encode()
        ).hexdigest()[:24]
        evidence = snapshot_reader.read(
            command_id=f"PRODUCT-SEMANTIC-{command_suffix}",
            document_id=self._document_id,
            host_instance_id=self._host_instance_id,
            wall_unique_id=binding.native_id,
            expected_revision=revision,
        )

        if (
            getattr(evidence, "document_id", None) != self._document_id
            or getattr(evidence, "host_instance_id", None) != self._host_instance_id
            or getattr(evidence, "wall_unique_id", None) != binding.native_id
            or getattr(evidence, "native_kind", None) != "Wall"
            or getattr(evidence, "revision_before", None) != revision
            or getattr(evidence, "revision_after", None) != revision
        ):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_RECONSTRUCTION_EVIDENCE_MISMATCH",
                "snapshot evidence does not match exact Revit binding/revision lineage",
            )

        facts = design_fact_adapter.normalize_snapshot(
            {
                "document_id": self._document_id,
                "host_instance_id": self._host_instance_id,
                "source_revision": revision,
                "native_id": binding.native_id,
                "native_kind": getattr(evidence, "native_kind", None),
                "builtin_category": getattr(evidence, "builtin_category", None),
                "wall_thickness_mm": getattr(evidence, "wall_thickness_mm", None),
            }
        )
        if not callable(getattr(facts, "to_dict", None)) or not hasattr(facts, "facts"):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_DESIGN_FACTS_INVALID",
                "design fact adapter returned an unsupported batch",
            )

        environment_id = _required_text(
            getattr(semantic_environment, "environment_id", None),
            "semantic_environment.environment_id",
        )
        environment_hash = _required_text(
            getattr(semantic_environment, "content_hash", None),
            "semantic_environment.content_hash",
        )
        claims = semantic_service.project_facts(facts, environment_id)
        if not isinstance(claims, tuple):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_SEMANTIC_PROJECTION_INVALID",
                "SemanticService project_facts must return a tuple",
            )

        classification_fact_ids = _fact_ids_for_kind(facts, "CLASSIFICATION")
        property_fact_ids = _fact_ids_for_kind(facts, "PROPERTY")
        classification_claims = tuple(
            claim
            for claim in claims
            if getattr(claim, "predicate", None) == "classification"
            and isinstance(getattr(claim, "canonical_term_id", None), str)
            and _claim_uses_fact(claim, classification_fact_ids)
        )
        property_claims = tuple(
            claim
            for claim in claims
            if getattr(claim, "predicate", None) == "property"
            and isinstance(getattr(claim, "canonical_term_id", None), str)
            and _claim_uses_fact(claim, property_fact_ids)
        )

        guarantees: list[AspectGuarantee] = [AspectGuarantee(SemanticAspect.IDENTITY)]
        classification_assurance = _strongest_claim_assurance(classification_claims)
        if classification_assurance is not None:
            guarantees.append(
                AspectGuarantee(
                    SemanticAspect.CLASSIFICATION,
                    coverage_state=CoverageState.RESOLVED,
                    semantic_depth=SemanticDepth.CANONICAL,
                    assurance_level=classification_assurance,
                )
            )
        property_assurance = _strongest_claim_assurance(property_claims)
        if property_assurance is not None:
            guarantees.append(
                AspectGuarantee(
                    SemanticAspect.PROPERTIES,
                    coverage_state=CoverageState.RESOLVED,
                    semantic_depth=SemanticDepth.CANONICAL,
                    assurance_level=property_assurance,
                )
            )

        normalized_fact_batch_hash = _canonical_hash(facts.to_dict())
        claim_payloads = tuple(
            sorted(
                (_claim_payload(claim) for claim in claims),
                key=_canonical_hash,
            )
        )
        mapping_material = tuple(
            sorted(
                (
                    {
                        "mapping_id": evidence_item.removeprefix("mapping:"),
                        "provider_id": payload["provider_id"],
                        "provider_version": payload["provider_version"],
                    }
                    for payload in claim_payloads
                    for evidence_item in payload["evidence"]
                    if isinstance(evidence_item, str) and evidence_item.startswith("mapping:")
                ),
                key=_canonical_hash,
            )
        )
        mapping_profile_set_hash = _canonical_hash(mapping_material)

        semantic_model_versions = {
            compatibility.strip()
            for provider in getattr(semantic_environment, "providers", ())
            for compatibility in getattr(provider, "compatibility", ())
            if isinstance(compatibility, str)
            and compatibility.strip().startswith("dsp.semantic.projection-facts.")
        }
        if len(semantic_model_versions) != 1:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_SEMANTIC_MODEL_AMBIGUOUS",
                "pinned semantic environment must expose one facts projection compatibility",
            )
        semantic_model_version = next(iter(semantic_model_versions))
        projection_hash = _canonical_hash(
            {
                "environment_id": environment_id,
                "environment_hash": environment_hash,
                "normalized_fact_batch_hash": normalized_fact_batch_hash,
                "mapping_profile_set_hash": mapping_profile_set_hash,
                "claims": list(claim_payloads),
            }
        )
        projection_ref = SemanticProjectionRef(
            projection_id=f"semantic-projection:{projection_hash}",
            projection_hash=projection_hash,
            semantic_model_version=semantic_model_version,
            provider_set_hash=environment_hash,
            mapping_profile_set_hash=mapping_profile_set_hash,
            normalized_fact_batch_hash=normalized_fact_batch_hash,
        )

        return ReconstructionResult(
            document_ref=self._document_id,
            host_revision=revision_text,
            coverage=contract.coverage,
            guarantees=tuple(guarantees),
            projection_ref=projection_ref,
            semantic_environment_ref=SemanticEnvironmentRef(
                environment_id=environment_id,
                content_hash=environment_hash,
            ),
        )


__all__ = [
    "ProductTaskRequestReadPort",
    "RevitContextObservationPort",
    "RevitSemanticBoundaryError",
    "RevitWallThicknessSemanticBoundary",
]
