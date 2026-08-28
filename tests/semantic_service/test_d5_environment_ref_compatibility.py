from semantic_runtime import SemanticEnvironmentRef
from semantic_service import ProviderRef, SemanticEnvironmentStore
from tests.semantic_service.helpers import registry_with_ifc


def test_pinned_environment_values_construct_existing_d5_ref():
    registry = registry_with_ifc()
    environment = SemanticEnvironmentStore().pin(
        (ProviderRef("buildingSMART.ifc43", "4.3.2.0"),),
        registry,
    )
    ref = SemanticEnvironmentRef(environment.environment_id, environment.content_hash)
    assert ref.payload() == {
        "environment_id": environment.environment_id,
        "content_hash": environment.content_hash,
    }
