"""Revit 墙厚 vertical 的 snapshot-bound OperationResolver 输入组合。"""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from design_orchestrator.default_workflow_services import OperationResolutionInputs
from design_orchestrator.operation_resolver import (
    CapabilityProfile,
    ClassificationGuarantee,
    ResolutionContext,
    SemanticEligibilityContext,
    SemanticEligibilityEntity,
)
from design_orchestrator.workflow_contracts import StableRef
from semantic_runtime import (
    AssuranceLevel,
    ContractType,
    CoverageState,
    FreshnessContract,
    IdentityRegistry,
    SemanticAspect,
    SemanticDepth,
    SnapshotKind,
)

from .revit_semantics import (
    DesignFactNormalizationPort,
    ProductTaskRequestReadPort,
    RevitContextObservationPort,
    RevitSemanticBoundaryError,
    RevitSnapshotReadPort,
    SemanticEnvironmentView,
    SemanticProjectionPort,
    _claim_uses_fact,
    _fact_ids_for_kind,
)
from .revit_semantics import (
    RevitWallThicknessSemanticBoundary as _BaseRevitWallThicknessSemanticBoundary,
)


class SemanticSnapshotReadPort(Protocol):
    """按 exact id 读取 Semantic Runtime authoritative snapshot。"""

    def get_snapshot(self, snapshot_id: str) -> object: ...


def _required_text(value: object, field_name: str) -> str:
    """拒绝 composition identity 中的空白或非字符串值。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


class RevitWallThicknessSemanticBoundary(_BaseRevitWallThicknessSemanticBoundary):
    """在既有 real reconstruction boundary 上补 snapshot-bound eligibility read model。

    本类不复制 OperationResolver eligibility 规则。它只把 exact ContextSnapshot、同 revision
    的真实 semantic projection 与 environment-owned provider profiles 组合成既有
    ``OperationResolutionInputs``。
    """

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
        snapshot_registry: SemanticSnapshotReadPort | None = None,
        capability_profiles: tuple[CapabilityProfile, ...] = (),
    ) -> None:
        super().__init__(
            request_store=request_store,
            context_reader=context_reader,
            identity_registry=identity_registry,
            session_ref=session_ref,
            document_id=document_id,
            host_instance_id=host_instance_id,
            snapshot_reader=snapshot_reader,
            design_fact_adapter=design_fact_adapter,
            semantic_service=semantic_service,
            semantic_environment=semantic_environment,
        )
        if snapshot_registry is not None and not callable(
            getattr(snapshot_registry, "get_snapshot", None)
        ):
            raise TypeError("snapshot_registry must provide get_snapshot")
        profiles = tuple(capability_profiles)
        for profile in profiles:
            _required_text(getattr(profile, "provider_server", None), "profile.provider_server")
        self._snapshot_registry = snapshot_registry
        self._capability_profiles = profiles

    def _operation_resolution_dependencies(self):
        """Step 4 只有被调用时才要求 snapshot/profile dependencies。"""

        if self._snapshot_registry is None:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_OPERATION_RESOLUTION_UNCONFIGURED",
                "semantic snapshot registry is not configured",
            )
        if not self._capability_profiles:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CAPABILITY_PROFILES_UNAVAILABLE",
                "operation resolution requires environment-owned capability profiles",
            )
        snapshot_reader, design_fact_adapter, semantic_service, semantic_environment = (
            self._reconstruction_dependencies()
        )
        return (
            self._snapshot_registry,
            self._capability_profiles,
            snapshot_reader,
            design_fact_adapter,
            semantic_service,
            semantic_environment,
        )

    @staticmethod
    def _machine_classification_supported(snapshot: object) -> bool:
        """把 authoritative snapshot guarantee 投影为 Step24 machine-decision flag。"""

        matches = tuple(
            guarantee
            for guarantee in getattr(snapshot, "aspect_guarantees", ())
            if getattr(guarantee, "aspect", None) is SemanticAspect.CLASSIFICATION
        )
        if len(matches) != 1:
            return False
        guarantee = matches[0]
        return (
            getattr(guarantee, "coverage_state", None) is not None
            and guarantee.coverage_state >= CoverageState.RESOLVED
            and getattr(guarantee, "semantic_depth", None) is not None
            and guarantee.semantic_depth >= SemanticDepth.CANONICAL
            and getattr(guarantee, "assurance_level", None) is not None
            and guarantee.assurance_level >= AssuranceLevel.RULE_DERIVED
        )

    def _classification_terms_for_snapshot(
        self,
        *,
        snapshot: object,
        snapshot_reader: RevitSnapshotReadPort,
        design_fact_adapter: DesignFactNormalizationPort,
        semantic_service: SemanticProjectionPort,
        semantic_environment: SemanticEnvironmentView,
    ) -> tuple[str, ...]:
        """对 exact snapshot revision 再读 Host facts，并只保留本批 facts 支撑的 canonical claims。"""

        roots = tuple(getattr(getattr(snapshot, "coverage", None), "root_entities", ()))
        if len(roots) != 1:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_OPERATION_RESOLUTION_COVERAGE_INVALID",
                "wall-thickness eligibility requires exactly one semantic root",
            )
        binding = self._exact_revit_binding(roots[0])
        revision_text = _required_text(
            getattr(snapshot, "base_host_revision", None),
            "snapshot.base_host_revision",
        )
        if not revision_text.isdecimal() or str(int(revision_text)) != revision_text:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_OPERATION_RESOLUTION_REVISION_INVALID",
                "ContextSnapshot revision must use canonical non-negative decimal form",
            )
        revision = int(revision_text)
        command_suffix = sha256(
            f"{getattr(snapshot, 'hash', '')}\n{binding.native_id}".encode()
        ).hexdigest()[:24]
        evidence = snapshot_reader.read(
            command_id=f"PRODUCT-ELIGIBILITY-{command_suffix}",
            document_id=self._document_id,
            host_instance_id=self._host_instance_id,
            wall_unique_id=binding.native_id,
            expected_revision=revision,
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
        environment_id = _required_text(
            getattr(semantic_environment, "environment_id", None),
            "semantic_environment.environment_id",
        )
        claims = semantic_service.project_facts(facts, environment_id)
        if not isinstance(claims, tuple):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_SEMANTIC_PROJECTION_INVALID",
                "SemanticService project_facts must return a tuple",
            )
        fact_ids = _fact_ids_for_kind(facts, "CLASSIFICATION")
        return tuple(
            sorted(
                {
                    term.strip()
                    for claim in claims
                    if getattr(claim, "predicate", None) == "classification"
                    and _claim_uses_fact(claim, fact_ids)
                    and isinstance((term := getattr(claim, "canonical_term_id", None)), str)
                    and term.strip()
                }
            )
        )

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs:
        """从 exact ContextSnapshot + real semantic projection 构造 resolver-only read model。"""

        if not isinstance(snapshot_ref, StableRef):
            raise TypeError("snapshot_ref must be StableRef")
        if snapshot_ref.content_hash is None:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_SNAPSHOT_HASH_REQUIRED",
                "ContextSnapshot StableRef requires content_hash",
            )
        (
            snapshot_registry,
            profiles,
            snapshot_reader,
            design_fact_adapter,
            semantic_service,
            semantic_environment,
        ) = self._operation_resolution_dependencies()
        snapshot = snapshot_registry.get_snapshot(snapshot_ref.ref_id)
        if (
            getattr(snapshot, "snapshot_id", None) != snapshot_ref.ref_id
            or getattr(snapshot, "hash", None) != snapshot_ref.content_hash
        ):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_SNAPSHOT_HASH_MISMATCH",
                "ContextSnapshot ref does not match authoritative owner content",
            )
        if getattr(snapshot, "kind", None) is not SnapshotKind.CONTEXT:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_SNAPSHOT_KIND_INVALID",
                "operation resolution requires a ContextSnapshot",
            )
        if getattr(snapshot, "document_ref", None) != self._document_id:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_SNAPSHOT_DOCUMENT_MISMATCH",
                "ContextSnapshot document does not match configured Revit document",
            )

        environment_id = _required_text(
            getattr(semantic_environment, "environment_id", None),
            "semantic_environment.environment_id",
        )
        environment_hash = _required_text(
            getattr(semantic_environment, "content_hash", None),
            "semantic_environment.content_hash",
        )
        snapshot_environment = getattr(snapshot, "semantic_environment_ref", None)
        if (
            getattr(snapshot_environment, "environment_id", None) != environment_id
            or getattr(snapshot_environment, "content_hash", None) != environment_hash
        ):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_SNAPSHOT_ENVIRONMENT_MISMATCH",
                "configured semantic environment does not match ContextSnapshot lineage",
            )

        replay_contract = FreshnessContract(
            project_id=_required_text(getattr(snapshot, "project_id", None), "snapshot.project_id"),
            contract_type=ContractType.CONTEXT,
            coverage=getattr(snapshot, "coverage", None),
            requirements=(),
        )
        replay = super().reconstruct(
            replay_contract,
            _required_text(
                getattr(snapshot, "base_host_revision", None),
                "snapshot.base_host_revision",
            ),
        )
        if (
            replay.projection_ref != getattr(snapshot, "projection_ref", None)
            or replay.semantic_environment_ref != snapshot_environment
        ):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_SNAPSHOT_PROJECTION_MISMATCH",
                "current exact-revision projection does not match ContextSnapshot lineage",
            )

        classifications = self._classification_terms_for_snapshot(
            snapshot=snapshot,
            snapshot_reader=snapshot_reader,
            design_fact_adapter=design_fact_adapter,
            semantic_service=semantic_service,
            semantic_environment=semantic_environment,
        )
        roots = tuple(snapshot.coverage.root_entities)
        machine_supported = self._machine_classification_supported(snapshot)
        entity = SemanticEligibilityEntity(
            semantic_id=roots[0],
            canonical_classifications=classifications,
            classification_guarantee=ClassificationGuarantee(machine_supported),
        )
        semantic_context = SemanticEligibilityContext(
            context_snapshot_id=snapshot.snapshot_id,
            context_snapshot_hash=snapshot.hash,
            document_ref=snapshot.document_ref,
            semantic_environment_ref=environment_id,
            entities=(entity,),
        )
        provider_servers = frozenset(
            _required_text(profile.provider_server, "profile.provider_server")
            for profile in profiles
        )
        return OperationResolutionInputs(
            profiles=profiles,
            context=ResolutionContext(
                host_provider_servers=provider_servers,
                semantic_context=semantic_context,
            ),
        )


__all__ = ["RevitWallThicknessSemanticBoundary", "SemanticSnapshotReadPort"]
