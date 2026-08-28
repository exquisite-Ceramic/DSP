"""Adapter-only test doubles for Semantic MCP tests."""

from __future__ import annotations


class FakeSemanticService:
    """Configurable seven-method SemanticService test double with exact call logs."""

    def __init__(self) -> None:
        self.resolve_result = None
        self.describe_result = None
        self.schema_result = None
        self.validation_result = ()
        self.mapping_result = ()
        self.manifest_result = None
        self.environment_result = None

        self.resolve_error: Exception | None = None
        self.describe_error: Exception | None = None
        self.schema_error: Exception | None = None
        self.validation_error: Exception | None = None
        self.mapping_error: Exception | None = None
        self.manifest_error: Exception | None = None
        self.environment_error: Exception | None = None

        self.resolve_calls: list[tuple[str, str]] = []
        self.describe_calls: list[tuple[str, str, str | None]] = []
        self.schema_calls: list[tuple[str, str]] = []
        self.validate_calls: list[tuple[object, str]] = []
        self.mapping_calls: list[tuple[object, str, str | None]] = []
        self.manifest_calls: list[tuple[str, str]] = []
        self.environment_calls: list[str] = []

    @staticmethod
    def _raise(error: Exception | None) -> None:
        if error is not None:
            raise error

    def resolve_term(self, term_id: str, environment_id: str):
        self.resolve_calls.append((term_id, environment_id))
        self._raise(self.resolve_error)
        return self.resolve_result

    def describe_term(
        self,
        term_id: str,
        environment_id: str,
        locale: str | None = None,
    ):
        self.describe_calls.append((term_id, environment_id, locale))
        self._raise(self.describe_error)
        return self.describe_result

    def get_term_schema(self, term_id: str, environment_id: str):
        self.schema_calls.append((term_id, environment_id))
        self._raise(self.schema_error)
        return self.schema_result

    def validate_claim(self, claim, environment_id: str):
        self.validate_calls.append((claim, environment_id))
        self._raise(self.validation_error)
        return self.validation_result

    def find_mappings(
        self,
        source_claim,
        environment_id: str,
        target_namespace: str | None = None,
    ):
        self.mapping_calls.append((source_claim, environment_id, target_namespace))
        self._raise(self.mapping_error)
        return self.mapping_result

    def get_provider_manifest(self, provider_id: str, version: str):
        self.manifest_calls.append((provider_id, version))
        self._raise(self.manifest_error)
        return self.manifest_result

    def get_environment(self, environment_id: str):
        self.environment_calls.append(environment_id)
        self._raise(self.environment_error)
        return self.environment_result
