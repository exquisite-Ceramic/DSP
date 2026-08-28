"""Deterministic Metro-to-IFC mapping over ACTIVE catalog records only."""

from __future__ import annotations

from semantic_service.providers import MappingCandidate, ProviderProvenance, SemanticClaim

from .catalog import MetroCatalog
from .model import MappingState


def find_mappings_for_claim(
    catalog: MetroCatalog,
    source_claim: SemanticClaim,
    provenance: ProviderProvenance,
    target_namespace: str | None = None,
) -> tuple[MappingCandidate, ...]:
    source = source_claim.canonical_term_id
    if source is None or not source.startswith("metro:"):
        return ()
    if target_namespace not in (None, "ifc"):
        return ()

    items: list[MappingCandidate] = []
    for record in catalog.mappings:
        if record.state is not MappingState.ACTIVE:
            continue
        if record.source_term_id != source:
            continue
        if not record.target_term_id.startswith("ifc:"):
            continue
        items.append(
            MappingCandidate(
                mapping_id=record.mapping_id,
                target_term_id=record.target_term_id,
                provenance=provenance,
                evidence=(),
            )
        )
    return tuple(sorted(items, key=lambda item: item.mapping_id))
