from dataclasses import replace

import pytest

from semantic_service import (
    AuthorityMode,
    ManifestValidationError,
    NamespaceAuthority,
    ProviderRef,
    ProviderType,
    SemanticCapability,
    SemanticProviderManifest,
)


def _manifest(**changes):
    base = SemanticProviderManifest(
        provider_id="buildingSMART.ifc43",
        provider_type=ProviderType.STANDARD,
        version="4.3.2.0",
        content_hash="ifc-content-v1",
        namespaces=("ifc",),
        capabilities=frozenset({
            SemanticCapability.VOCABULARY,
            SemanticCapability.VALIDATION,
            SemanticCapability.PROJECTION,
        }),
        authority=(NamespaceAuthority("ifc", AuthorityMode.AUTHORITATIVE),),
        compatibility=("semantic-service.v1",),
        requires=(),
    )
    return replace(base, **changes)


def test_manifest_hash_is_order_independent_for_set_like_fields():
    first = _manifest(
        namespaces=("ifc", "ifc-ext"),
        compatibility=("z", "a"),
    )
    second = _manifest(
        namespaces=("ifc-ext", "ifc"),
        compatibility=("a", "z"),
    )
    assert first.manifest_hash == second.manifest_hash


def test_machine_semantic_change_changes_manifest_hash():
    baseline = _manifest()
    changed = _manifest(capabilities=frozenset({SemanticCapability.VOCABULARY}))
    assert baseline.manifest_hash != changed.manifest_hash


def test_self_dependency_is_rejected():
    with pytest.raises(ManifestValidationError, match="self-dependency"):
        _manifest(requires=(ProviderRef("buildingSMART.ifc43", "4.3.2.0"),))


def test_namespace_token_with_colon_is_rejected():
    with pytest.raises(ManifestValidationError, match="namespace"):
        _manifest(namespaces=("ifc:bad",))


@pytest.mark.parametrize("field_name", ("provider_id", "version", "content_hash"))
def test_non_string_required_manifest_fields_raise_typed_validation_error(field_name):
    with pytest.raises(ManifestValidationError, match=field_name):
        _manifest(**{field_name: None})
