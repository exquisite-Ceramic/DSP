from __future__ import annotations

from dataclasses import replace

import pytest
from design_approval_scope import CanonicalAspect
from design_changeset import ChangePrecondition, PreconditionKind, canonical_hash
from design_execution_planning import (
    ApprovedExecutionScopeRef,
    ExecutionSlice,
    ExecutionUnit,
    HostRuntimeRef,
    compute_execution_slice_hash,
    compute_execution_unit_hash,
)
from design_provider_binding import (
    EligibilityState,
    NativeConstraint,
    NativeConstraintOperator,
    NativeTargetBindingEvidence,
    ProviderBindingMaterial,
    ProviderBindingRequest,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshot,
    compute_candidate_fingerprint,
    compute_host_binding_fingerprint,
    compute_provider_snapshot_hash,
)

DEFAULT_PROVIDER_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "native_ids": {"type": "array", "items": {"type": "string"}},
        "operation": {"type": "string"},
        "canonical_arguments": {"type": "object"},
    },
    "required": ["native_ids", "operation", "canonical_arguments"],
    "additionalProperties": False,
}


def digest(label: str) -> str:
    return canonical_hash({"step31_fixture": label})


@pytest.fixture
def digest_fn():
    return digest


def build_execution_slice() -> ExecutionSlice:
    changeset_hash = digest("changeset")
    definition_hash = digest("move-definition")
    preconditions = (
        ChangePrecondition(
            PreconditionKind.OPERATION_FRESHNESS,
            "move.v1",
            digest("freshness"),
        ),
        ChangePrecondition(
            PreconditionKind.COVERAGE,
            "move.v1",
            digest("coverage"),
        ),
    )

    def unit(source: str, target: str) -> ExecutionUnit:
        source_hash = digest(source)
        arguments = {"displacement": [100.0, 0.0, 0.0]}
        unit_hash = compute_execution_unit_hash(
            changeset_hash=changeset_hash,
            source_operation_hash=source_hash,
            canonical_operation="move.v1",
            canonical_operation_version="1.0.0",
            canonical_definition_fingerprint=definition_hash,
            targets=(target,),
            arguments=arguments,
            preconditions=preconditions,
            expected_effects=(CanonicalAspect.PLACEMENT,),
        )
        return ExecutionUnit(
            f"EU-{unit_hash[:12]}",
            f"COP-{source_hash[:12]}",
            source_hash,
            "move.v1",
            "1.0.0",
            definition_hash,
            (target,),
            arguments,
            preconditions,
            (CanonicalAspect.PLACEMENT,),
            unit_hash,
        )

    units = (
        unit("operation-wall", "WALL-001"),
        unit("operation-annotation", "ANNOTATION-002"),
    )
    host_ref = HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    scope_ref = ApprovedExecutionScopeRef(
        "SCOPE-31",
        digest("scope"),
        "SLICE-SCOPE-31",
    )
    slice_hash = compute_execution_slice_hash(
        changeset_hash=changeset_hash,
        scope_hash=scope_ref.scope_hash,
        execution_slice_scope_rule_id=scope_ref.execution_slice_scope_rule_id,
        host_runtime_ref=host_ref,
        execution_unit_hashes=(item.execution_unit_hash for item in units),
    )
    return ExecutionSlice(
        f"XS-{slice_hash[:12]}",
        "CS-31",
        changeset_hash,
        host_ref,
        scope_ref,
        units,
        slice_hash,
    )


@pytest.fixture
def execution_slice():
    return build_execution_slice()


class FakeBindingAdapter:
    def __init__(
        self,
        *,
        adapter_version: str = "1.0.0",
        material_factory=None,
        error: Exception | None = None,
    ) -> None:
        self.adapter_version = adapter_version
        self.material_factory = material_factory
        self.error = error
        self.calls = []

    def bind(
        self,
        execution_unit,
        host_runtime_ref,
        selected_candidate,
        native_target_bindings,
    ):
        self.calls.append(
            (
                execution_unit,
                host_runtime_ref,
                selected_candidate,
                native_target_bindings,
            )
        )
        if self.error is not None:
            raise self.error
        if self.material_factory is not None:
            return self.material_factory(execution_unit, native_target_bindings)
        return ProviderBindingMaterial(
            native_targets=native_target_bindings,
            provider_arguments={
                "native_ids": [item.native_id for item in native_target_bindings],
                "operation": execution_unit.canonical_operation,
                "canonical_arguments": dict(execution_unit.arguments),
            },
            provider_preconditions=(),
            native_binding_metadata={"variant": "default"},
        )


@pytest.fixture
def fake_adapter():
    return FakeBindingAdapter()


def make_native_binding(
    semantic_id: str,
    *,
    native_id: str,
    native_kind: str = "Wall",
    host_type: str = "REVIT",
    document_ref: str = "DOC-1",
) -> NativeTargetBindingEvidence:
    provisional = NativeTargetBindingEvidence(
        semantic_id,
        host_type,
        document_ref,
        native_id,
        native_kind,
        digest("temporary-host-binding"),
    )
    return replace(
        provisional,
        host_binding_fingerprint=compute_host_binding_fingerprint(provisional),
    )


def make_candidate(
    *,
    provider_server: str = "provider.revit.a",
    provider_tool: str = "move",
    provider_version: str = "1.0.0",
    canonical_operation: str = "move.v1",
    compatible_operation_versions: tuple[str, ...] = ("1.0.0",),
    priority: int = 10,
    native_kinds: tuple[str, ...] = ("Wall", "Annotation"),
    state: EligibilityState = EligibilityState.SATISFIED,
    trust_state: EligibilityState | None = None,
    compatibility_state: EligibilityState | None = None,
    health_state: EligibilityState | None = None,
    license_state: EligibilityState | None = None,
    certification_state: EligibilityState | None = None,
    input_adapter_version: str = "1.0.0",
    provider_input_schema=None,
) -> ProviderExecutionCandidate:
    provisional = ProviderExecutionCandidate(
        provider_server,
        provider_tool,
        provider_version,
        canonical_operation,
        compatible_operation_versions,
        input_adapter_version,
        (NativeConstraint("native_kind", NativeConstraintOperator.IN, native_kinds),),
        provider_input_schema or DEFAULT_PROVIDER_INPUT_SCHEMA,
        {"read_back": "required"},
        {"mode": "compensating_changeset"},
        trust_state or state,
        compatibility_state or state,
        health_state or state,
        license_state or state,
        certification_state or state,
        priority,
        digest("temporary-candidate"),
    )
    return replace(
        provisional,
        candidate_fingerprint=compute_candidate_fingerprint(provisional),
    )


def default_native_bindings(execution_slice: ExecutionSlice):
    return (
        make_native_binding("WALL-001", native_id="NATIVE-WALL", native_kind="Wall"),
        make_native_binding(
            "ANNOTATION-002",
            native_id="NATIVE-ANNOTATION",
            native_kind="Annotation",
        ),
    )


def make_snapshot(
    execution_slice: ExecutionSlice,
    *,
    native_target_bindings=None,
    provider_candidates=None,
    snapshot_id: str = "PES-31",
    valid_until: str = "2026-08-30T10:30:00Z",
    host_runtime_ref=None,
    execution_slice_id: str | None = None,
    execution_slice_hash: str | None = None,
) -> ProviderExecutionSnapshot:
    provisional = ProviderExecutionSnapshot(
        snapshot_id,
        execution_slice_id or execution_slice.execution_slice_id,
        execution_slice_hash or execution_slice.execution_slice_hash,
        host_runtime_ref or execution_slice.host_runtime_ref,
        tuple(native_target_bindings or default_native_bindings(execution_slice)),
        tuple(provider_candidates or (make_candidate(),)),
        valid_until,
        digest("temporary-snapshot"),
    )
    return replace(
        provisional,
        snapshot_hash=compute_provider_snapshot_hash(provisional),
    )


def make_request(
    execution_slice: ExecutionSlice,
    *,
    snapshot: ProviderExecutionSnapshot | None = None,
    admission_time: str = "2026-08-30T10:00:00Z",
) -> ProviderBindingRequest:
    return ProviderBindingRequest(
        execution_slice,
        snapshot or make_snapshot(execution_slice),
        admission_time,
    )


@pytest.fixture
def valid_snapshot(execution_slice):
    return make_snapshot(execution_slice)


@pytest.fixture
def valid_request(execution_slice, valid_snapshot):
    return make_request(execution_slice, snapshot=valid_snapshot)
