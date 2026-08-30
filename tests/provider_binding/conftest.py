from __future__ import annotations

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
