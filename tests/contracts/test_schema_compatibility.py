"""Conformance of Python contract output against the JSON Schemas in contracts/schemas.

Covers the v1.0 (spec v0.6) wire format: snake_case DTOs must validate
against their JSON Schema mirrors.
"""

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from host_contracts.command import HostCommand
from host_contracts.delta import HostDelta
from host_contracts.entity_ref import HostEntityRef
from host_contracts.envelope import RequestEnvelope, ResponseEnvelope
from host_contracts.error import ErrorShape
from host_contracts.result import HostCommandResult
from host_contracts.status import HostStatus

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "schemas"


@pytest.fixture(scope="module")
def schema_store() -> dict[str, dict]:
    store: dict[str, dict] = {}
    for path in SCHEMAS_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        store[schema["$id"]] = schema
    return store


def validate(schema: dict, instance: dict, store: dict[str, dict]) -> None:
    registry = Registry().with_resources(
        [(uri, Resource.from_contents(contents)) for uri, contents in store.items()]
    )
    validator = jsonschema.validators.validator_for(schema)(schema, registry=registry)
    validator.validate(instance)


def load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def test_all_schemas_are_valid_json_schema(schema_store):
    for schema in schema_store.values():
        jsonschema.validators.validator_for(schema).check_schema(schema)


def test_python_request_envelope_matches_schema(schema_store):
    env = RequestEnvelope(
        request_id="req-001",
        task_id="task-001",
        project_id="project-001",
        deadline_at="2026-08-26T14:00:00Z",
        idempotency_key="k1",
        payload={"command_id": "cmd-1"},
    ).to_dict()
    validate(load("envelope.schema.json"), env, schema_store)


def test_python_response_envelope_matches_schema(schema_store):
    resp = ResponseEnvelope(request_id="req-001", status="OK").to_dict()
    validate(load("response-envelope.schema.json"), resp, schema_store)


def test_python_command_matches_schema(schema_store):
    command = HostCommand(
        command_id="cmd-001",
        document_id="drawing-001",
        mode="EXECUTE",
        operation="move.v1",
        target_native_refs=[HostEntityRef(document_id="drawing-001", native_id="2AF")],
        arguments={"displacement": {"x": 500, "y": 0, "z": 0}},
        idempotency_key="k1",
    ).to_dict()
    validate(load("host-command.schema.json"), command, schema_store)


def test_python_result_matches_schema(schema_store):
    result = HostCommandResult(command_id="cmd-001", status="OK", revision_after=4).to_dict()
    validate(load("host-result.schema.json"), result, schema_store)


def test_python_delta_matches_schema(schema_store):
    delta = HostDelta(
        revision_before=100,
        revision_after=101,
        modified=[HostEntityRef(document_id="drawing-001", native_id="2AF")],
    ).to_dict()
    validate(load("host-delta.schema.json"), delta, schema_store)


def test_python_error_matches_schema(schema_store):
    error = ErrorShape(
        error_code="REVISION_CONFLICT",
        category="CONSISTENCY",
        retryable="AFTER_RECONSTRUCT",
    ).to_dict()
    validate(load("host-error.schema.json"), error, schema_store)


def test_python_status_matches_schema(schema_store):
    status = HostStatus(state="ready", document_id="d", revision=2).to_dict()
    validate(load("host-status.schema.json"), status, schema_store)


def test_command_envelope_payload_round_trips_against_command_schema(schema_store):
    command = HostCommand(
        command_id="cmd-001",
        document_id="drawing-001",
        mode="READ",
        operation="context.current_document",
    ).to_dict()
    env = RequestEnvelope(request_id="req-001", payload=command).to_dict()
    validate(load("envelope.schema.json"), env, schema_store)
    validate(load("host-command.schema.json"), env["payload"], schema_store)


def test_delta_entity_refs_use_command_definition(schema_store):
    # Cross-schema $ref: host-delta's entityRef definition lives in host-command.
    delta = HostDelta(
        revision_before=1,
        revision_after=2,
        added=[HostEntityRef(document_id="drawing-001", native_id="3B1", native_type="LINE")],
    ).to_dict()
    validate(load("host-delta.schema.json"), delta, schema_store)


def test_request_envelope_schema_allows_unknown_fields_for_forward_compatibility(schema_store):
    env = {
        "request_id": "req-001",
        "payload": {},
        "future_field": {"introduced_in": "1.1"},
    }
    validate(load("envelope.schema.json"), env, schema_store)


def test_host_command_schema_allows_unknown_fields_for_forward_compatibility(schema_store):
    command = {
        "command_id": "cmd-001",
        "document_id": "drawing-001",
        "mode": "READ",
        "operation": "context.current_document",
        "future_nested": {"introduced_in": "1.1"},
    }
    validate(load("host-command.schema.json"), command, schema_store)
