from __future__ import annotations

from hashlib import sha256
import json

import pytest

from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from design_fact_contracts import FactKind, NormalizedDesignFactBatch
from enterprise_mapping_provider import ENTERPRISE_MAPPING_PROVIDER
from ifc43_semantic_provider import IFC43_PROVIDER
from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    AssuranceLevel,
    CoverageState,
    DirtyMap,
    FreshnessContract,
    FreshnessResolver,
    FreshnessState,
    FreshnessUnsatisfiedError,
    GeometryLevel,
    ReconstructionResult,
    SemanticAspect,
    SemanticDepth,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SnapshotKind,
    build_operation_contract,
)
from semantic_service import (
    ProviderRef,
    SemanticClaim,
    SemanticEnvironment,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
)

DOCUMENT_ID = "C:/models/station.dwg"
TARGET_SUBJECT = "native://autocad/autocad-session-1/C%3A%2Fmodels%2Fstation.dwg/A31"


def _snapshot(layer: str) -> dict[str, object]:
    return {
        "hostInstanceId": "autocad-session-1",
        "documentId": DOCUMENT_ID,
        "revision": 42,
        "entities": [{
            "nativeId": "A31",
            "nativeKind": "LWPOLYLINE",
            "layer": layer,
        }],
    }


def _semantic_stack() -> tuple[SemanticService, SemanticEnvironment]:
    registry = SemanticProviderRegistry()
    registry.register(IFC43_PROVIDER)
    registry.register(ENTERPRISE_MAPPING_PROVIDER)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (
            ProviderRef("buildingSMART.ifc43", "4.3.2.0"),
            ProviderRef("dsp.enterprise.mapping", "1.0.0"),
        ),
        registry,
    )
    return SemanticService(registry, store), environment


def _contract(
    assurance: AssuranceLevel = AssuranceLevel.RULE_DERIVED,
) -> FreshnessContract:
    return build_operation_contract(
        project_id="project-step21",
        document_ref=DOCUMENT_ID,
        canonical_operation="classify.v1",
        targets=(TARGET_SUBJECT,),
        arguments={},
        requirements=(
            AspectRequirement(
                SemanticAspect.CLASSIFICATION,
                geometry_level=GeometryLevel.NONE,
                minimum_coverage=CoverageState.RESOLVED,
                semantic_depth=SemanticDepth.CANONICAL,
                minimum_assurance=assurance,
            ),
        ),
    )


def test_a_wall_reaches_existing_d5_as_canonical_ifc_wall() -> None:
    facts = DesignFactAdapter().normalize_snapshot(_snapshot("A-WALL"))
    classification = next(
        fact for fact in facts.facts if fact.fact_kind is FactKind.CLASSIFICATION
    )
    assert classification.source_scheme == "autocad.layer"
    assert classification.source_code == "A-WALL"

    service, environment = _semantic_stack()
    claims = service.project_facts(facts, environment.environment_id)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.subject == TARGET_SUBJECT
    assert claim.predicate == "classification"
    assert claim.canonical_term_id == "ifc:IfcWall"
    assert claim.assurance == "RULE_DERIVED"

    dirty = DirtyMap()
    dirty.mark_dirty(DOCUMENT_ID, TARGET_SUBJECT, (SemanticAspect.CLASSIFICATION,))
    contract = _contract()
    snapshot = FreshnessResolver(dirty).resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda current, revision: _reconstruction_from_claims(
            current,
            revision,
            facts=facts,
            claims=claims,
            environment=environment,
        ),
    )

    assert snapshot.kind is SnapshotKind.PLANNING
    assert snapshot.semantic_environment_ref == SemanticEnvironmentRef(
        environment.environment_id,
        environment.content_hash,
    )
    assert snapshot.projection_ref.normalized_fact_batch_hash is not None
    assert snapshot.projection_ref.semantic_model_version == "step21-proof-v1"

    guarantee = snapshot.aspect_guarantees[0]
    assert guarantee.aspect is SemanticAspect.CLASSIFICATION
    assert guarantee.coverage_state is CoverageState.RESOLVED
    assert guarantee.semantic_depth is SemanticDepth.CANONICAL
    assert guarantee.assurance_level is AssuranceLevel.RULE_DERIVED
    assert guarantee.geometry_level is GeometryLevel.NONE
    assert dirty.state(
        DOCUMENT_ID, TARGET_SUBJECT, SemanticAspect.CLASSIFICATION
    ) is FreshnessState.FRESH
    assert dirty.state(
        DOCUMENT_ID, TARGET_SUBJECT, SemanticAspect.GEOMETRY
    ) is FreshnessState.UNKNOWN
