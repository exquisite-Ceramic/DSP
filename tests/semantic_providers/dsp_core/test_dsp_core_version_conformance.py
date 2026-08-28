from dataclasses import replace

import pytest

from semantic_service import ProviderRegistrationConflictError, SemanticProviderRegistry

from dsp_core_semantic_provider import (
    DSP_CORE_PROVIDER,
    DSP_CORE_TERMS,
    DspCoreSemanticProvider,
    SemanticTermCatalog,
)


def test_same_provider_version_with_changed_machine_semantics_fails_closed():
    changed_terms = tuple(
        replace(term, unit="m") if term.term_id == "dsp:WallThickness" else term
        for term in DSP_CORE_TERMS
    )
    changed_provider = DspCoreSemanticProvider(SemanticTermCatalog(changed_terms))

    registry = SemanticProviderRegistry()
    registry.register(DSP_CORE_PROVIDER)

    with pytest.raises(ProviderRegistrationConflictError):
        registry.register(changed_provider)
