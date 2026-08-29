from __future__ import annotations

from hashlib import sha256
import json

import pytest

from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from design_fact_contracts import FactKind, NormalizedDesignFactBatch
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

pytest.importorskip("semantic_service")
from semantic_service import (
    ProviderRef,
    SemanticClaim,
    SemanticEnvironment,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
)

enterprise_mapping_provider = pytest.importorskip("enterprise_mapping_provider")
ifc43_semantic_provider = pytest.importorskip("ifc43_semantic_provider")
ENTERPRISE_MAPPING_PROVIDER = enterprise_mapping_provider.ENTERPRISE_MAPPING_PROVIDER
IFC43_PROVIDER = ifc43_semantic_provider.IFC43_PROVIDER

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


def _digest(payload: object) -> str:
    return sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _claim_payload(claim: SemanticClaim) -> dict[str, object]:
    return {
        "subject": claim.subject,
        "predicate": claim.predicate,
        "canonical_term_id": claim.canonical_term_id,
        "value": claim.value,
        "unit": claim.unit,
        "assurance": claim.assurance,
        "provenance": list(claim.provenance),
        "evidence": list(claim.evidence),
        "provider_id": claim.provider_id,
        "provider_version": claim.provider_version,
    }


def _projection_ref(
    facts: NormalizedDesignFactBatch,
    claims: tuple[SemanticClaim, ...],
    environment: SemanticEnvironment,
) -> SemanticProjectionRef:
    providers = [
        {
            "provider_id": item.provider_id,
            "version": item.version,
            "content_hash": item.content_hash,
        }
        for item in environment.providers
    ]
    projection_hash = _digest({
        "environment_id": environment.environment_id,
        "environment_hash": environment.content_hash,
        "claims": [_claim_payload(claim) for claim in claims],
    })
    return SemanticProjectionRef(
        projection_id=f"step21:{projection_hash}",
        projection_hash=projection_hash,
        semantic_model_version="step21-proof-v1",
        provider_set_hash=_digest(providers),
        mapping_profile_set_hash=_digest({"providers": providers}),
        normalized_fact_batch_hash=_digest(facts.to_dict()),
    )


def _reconstruction_from_claims(
    contract: FreshnessContract,
    revision: str,
    *,
    facts: NormalizedDesignFactBatch,
    claims: tuple[SemanticClaim, ...],
    environment: SemanticEnvironment,
) -> ReconstructionResult:
    requested = set(contract.coverage.root_entities)
    strongest: dict[str, AssuranceLevel] = {}

    for claim in claims:
        if claim.subject not in requested:
            continue
        if claim.predicate != "classification" or claim.canonical_term_id is None:
            continue
        try:
            assurance = AssuranceLevel[claim.assurance]
        except KeyError as exc:
            raise ValueError(
                f"unknown canonical claim assurance: {claim.assurance!r}"
            ) from exc
        strongest[claim.subject] = max(
            assurance,
            strongest.get(claim.subject, AssuranceLevel.UNKNOWN),
        )

    guarantees: tuple[AspectGuarantee, ...] = ()
    if requested and requested.issubset(strongest):
        guarantees = (
            AspectGuarantee(
                SemanticAspect.CLASSIFICATION,
                geometry_level=GeometryLevel.NONE,
                coverage_state=CoverageState.RESOLVED,
                semantic_depth=SemanticDepth.CANONICAL,
                assurance_level=min(strongest[item] for item in requested),
            ),
        )

    return ReconstructionResult(
        document_ref=contract.coverage.document_ref,
        host_revision=revision,
        coverage=contract.coverage,
        guarantees=guarantees,
        projection_ref=_projection_ref(facts, claims, environment),
        semantic_environment_ref=SemanticEnvironmentRef(
            environment.environment_id,
            environment.content_hash,
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


@pytest.mark.parametrize("layer", ["A-WALLISH", "X-A-WALL"])
def test_near_match_layer_does_not_satisfy_d5_classification(layer: str) -> None:
    facts = DesignFactAdapter().normalize_snapshot(_snapshot(layer))
    service, environment = _semantic_stack()
    claims = service.project_facts(facts, environment.environment_id)
    assert claims == ()

    dirty = DirtyMap()
    dirty.mark_dirty(DOCUMENT_ID, TARGET_SUBJECT, (SemanticAspect.CLASSIFICATION,))
    contract = _contract()
    with pytest.raises(
        FreshnessUnsatisfiedError,
        match=r"CLASSIFICATION\.freshness",
    ):
        FreshnessResolver(dirty).resolve(
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
    assert dirty.state(
        DOCUMENT_ID, TARGET_SUBJECT, SemanticAspect.CLASSIFICATION
    ) is FreshnessState.DIRTY


def test_rule_derived_claim_cannot_satisfy_standard_mapped_requirement() -> None:
    facts = DesignFactAdapter().normalize_snapshot(_snapshot("A-WALL"))
    service, environment = _semantic_stack()
    claims = service.project_facts(facts, environment.environment_id)
    assert len(claims) == 1
    assert claims[0].assurance == "RULE_DERIVED"

    dirty = DirtyMap()
    dirty.mark_dirty(DOCUMENT_ID, TARGET_SUBJECT, (SemanticAspect.CLASSIFICATION,))
    contract = _contract(AssuranceLevel.STANDARD_MAPPED)
    with pytest.raises(
        FreshnessUnsatisfiedError,
        match=r"CLASSIFICATION\.assurance",
    ):
        FreshnessResolver(dirty).resolve(
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
    assert dirty.state(
        DOCUMENT_ID, TARGET_SUBJECT, SemanticAspect.CLASSIFICATION
    ) is FreshnessState.DIRTY
