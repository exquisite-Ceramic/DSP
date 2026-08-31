from __future__ import annotations

from urllib.parse import quote

from design_fact_contracts import FactKind, NormalizedDesignFact, NormalizedDesignFactBatch
from semantic_service import SemanticClaim

from .errors import EnterpriseProjectionError
from .model import EnterpriseMappingCatalog, EnterpriseMappingRule, MatchType


def native_subject_locator(fact: NormalizedDesignFact) -> str:
    """Build a native subject address without claiming canonical semantic identity."""
    return "native://{}/{}/{}/{}".format(
        quote(fact.host_ref.host_type, safe=""),
        quote(fact.host_ref.host_instance_id, safe=""),
        quote(fact.host_ref.document_id, safe=""),
        quote(fact.subject_native_ref.native_id, safe=""),
    )


def _matches_code(rule: EnterpriseMappingRule, source_code: str) -> bool:
    candidate = source_code if rule.case_sensitive else source_code.casefold()
    pattern = rule.pattern if rule.case_sensitive else rule.pattern.casefold()
    if rule.match_type is MatchType.EXACT:
        return candidate == pattern
    if rule.match_type is MatchType.PREFIX:
        return candidate.startswith(pattern)
    raise EnterpriseProjectionError(f"unsupported match type at runtime: {rule.match_type}")


def project_facts_for_catalog(
    catalog: EnterpriseMappingCatalog,
    facts: NormalizedDesignFactBatch,
    *,
    provider_id: str,
    provider_version: str,
) -> tuple[SemanticClaim, ...]:
    derivations: list[tuple[str, str, str, SemanticClaim]] = []

    for fact in facts.facts:
        if fact.fact_kind not in {FactKind.CLASSIFICATION, FactKind.PROPERTY}:
            continue
        if fact.source_scheme is None or fact.source_code is None:
            continue

        subject = native_subject_locator(fact)
        matching = tuple(
            rule
            for rule in catalog.rules
            if rule.source_scheme == fact.source_scheme
            and _matches_code(rule, fact.source_code)
        )
        if not matching:
            continue

        semantic_outputs = {
            (rule.target_term_id, rule.assurance)
            for rule in matching
        }
        if len(semantic_outputs) > 1:
            mapping_ids = ", ".join(sorted(rule.mapping_id for rule in matching))
            raise EnterpriseProjectionError(
                "conflicting enterprise mappings for one source fact: "
                f"{fact.fact_id}: {mapping_ids}"
            )

        if fact.fact_kind is FactKind.CLASSIFICATION:
            predicate = "classification"
            value = None
            unit = None
        else:
            predicate = "property"
            value = fact.value
            unit = fact.unit

        for rule in matching:
            claim = SemanticClaim(
                subject=subject,
                predicate=predicate,
                canonical_term_id=rule.target_term_id,
                value=value,
                unit=unit,
                assurance=rule.assurance,
                provenance=fact.provenance,
                evidence=(
                    f"design-fact:{fact.fact_id}",
                    f"mapping:{rule.mapping_id}",
                ),
                provider_id=provider_id,
                provider_version=provider_version,
            )
            derivations.append((subject, rule.mapping_id, fact.fact_id, claim))

    derivations.sort(key=lambda item: item[:3])
    return tuple(item[3] for item in derivations)
