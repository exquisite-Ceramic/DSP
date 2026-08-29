from __future__ import annotations

from design_fact_contracts import NormalizedDesignFactBatch
from semantic_service import (
    AuthorityMode,
    FACT_PROJECTION_COMPATIBILITY,
    NamespaceAuthority,
    ProviderRef,
    ProviderType,
    SemanticCapability,
    SemanticClaim,
    SemanticProviderManifest,
)

from .catalog import build_catalog
from .errors import EnterpriseCatalogBuildError
from .golden import ENTERPRISE_MAPPING_V1_GOLDEN_CONTENT_HASH
from .model import EnterpriseMappingCatalog
from .source import load_raw_machine_source


ENTERPRISE_MAPPING_CATALOG = build_catalog(load_raw_machine_source())
if ENTERPRISE_MAPPING_CATALOG.content_hash != ENTERPRISE_MAPPING_V1_GOLDEN_CONTENT_HASH:
    raise EnterpriseCatalogBuildError(
        "enterprise mapping content hash differs from reviewed golden hash"
    )


class EnterpriseMappingProvider:
    def __init__(self, catalog: EnterpriseMappingCatalog = ENTERPRISE_MAPPING_CATALOG) -> None:
        self._catalog = catalog
        self._manifest = SemanticProviderManifest(
            provider_id="dsp.enterprise.mapping",
            provider_type=ProviderType.ENTERPRISE,
            version="1.0.0",
            content_hash=catalog.content_hash,
            namespaces=("ifc",),
            capabilities=frozenset({SemanticCapability.PROJECTION}),
            authority=(NamespaceAuthority("ifc", AuthorityMode.EXTENSION),),
            compatibility=(FACT_PROJECTION_COMPATIBILITY,),
            requires=(ProviderRef("buildingSMART.ifc43", "4.3.2.0"),),
        )

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def project_facts(
        self,
        facts: NormalizedDesignFactBatch,
    ) -> tuple[SemanticClaim, ...]:
        # Task 2 freezes catalog/manifest identity. Task 3 adds fact projection behavior.
        return ()


ENTERPRISE_MAPPING_PROVIDER = EnterpriseMappingProvider()
