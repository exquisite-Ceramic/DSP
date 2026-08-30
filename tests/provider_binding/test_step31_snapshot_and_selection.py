from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import (
    digest,
    make_candidate,
    make_native_binding,
    make_request,
    make_snapshot,
)
from design_execution_planning import HostRuntimeRef
from design_provider_binding import EligibilityState, ProviderBindingError
from design_provider_binding.resolver import (
    _select_candidate,
    _validate_request_and_snapshot,
)


def _unit_native_targets(unit, native_by_id):
    return tuple(native_by_id[target] for target in unit.targets)


@pytest.mark.parametrize(
    "snapshot_update",
    (
        {"execution_slice_id": "XS-WRONG"},
        {"execution_slice_hash": digest("wrong-slice")},
        {"host_runtime_ref": HostRuntimeRef("REVIT", "RVT-02", "DOC-1")},
    ),
)
def test_slice_identity_hash_or_runtime_mismatch_fails_closed(execution_slice, snapshot_update):
    snapshot = make_snapshot(execution_slice, **snapshot_update)
    with pytest.raises(ProviderBindingError) as exc:
        _validate_request_and_snapshot(make_request(execution_slice, snapshot=snapshot))
    assert exc.value.code == "PROVIDER_SLICE_MISMATCH"


def test_native_row_host_or_document_mismatch_fails_as_slice_mismatch(execution_slice):
    rows = (
        make_native_binding(
            "WALL-001",
            native_id="NATIVE-WALL",
            native_kind="Wall",
            host_type="AUTOCAD",
        ),
        make_native_binding(
            "ANNOTATION-002",
            native_id="NATIVE-ANNOTATION",
            native_kind="Annotation",
        ),
    )
    snapshot = make_snapshot(execution_slice, native_target_bindings=rows)
    with pytest.raises(ProviderBindingError) as exc:
        _validate_request_and_snapshot(make_request(execution_slice, snapshot=snapshot))
    assert exc.value.code == "PROVIDER_SLICE_MISMATCH"


def test_host_binding_fingerprint_mismatch_is_conflict(execution_slice):
    valid = make_native_binding("WALL-001", native_id="NATIVE-WALL", native_kind="Wall")
    bad = replace(valid, host_binding_fingerprint=digest("wrong-host-binding"))
    annotation = make_native_binding(
        "ANNOTATION-002", native_id="NATIVE-ANNOTATION", native_kind="Annotation"
    )
    snapshot = make_snapshot(execution_slice, native_target_bindings=(bad, annotation))
    with pytest.raises(ProviderBindingError) as exc:
        _validate_request_and_snapshot(make_request(execution_slice, snapshot=snapshot))
    assert exc.value.code == "PROVIDER_NATIVE_BINDING_CONFLICT"


def test_missing_duplicate_and_extraneous_native_rows_fail_closed(execution_slice):
    wall = make_native_binding("WALL-001", native_id="NATIVE-WALL", native_kind="Wall")
    annotation = make_native_binding(
        "ANNOTATION-002", native_id="NATIVE-ANNOTATION", native_kind="Annotation"
    )

    missing = make_snapshot(execution_slice, native_target_bindings=(wall,))
    with pytest.raises(ProviderBindingError) as exc:
        _validate_request_and_snapshot(make_request(execution_slice, snapshot=missing))
    assert exc.value.code == "PROVIDER_NATIVE_BINDING_UNRESOLVED"

    duplicate = make_snapshot(execution_slice, native_target_bindings=(wall, annotation, wall))
    with pytest.raises(ProviderBindingError) as exc:
        _validate_request_and_snapshot(make_request(execution_slice, snapshot=duplicate))
    assert exc.value.code == "PROVIDER_NATIVE_BINDING_CONFLICT"

    extra = make_native_binding("EXTRA-003", native_id="NATIVE-EXTRA", native_kind="Wall")
    extraneous = make_snapshot(execution_slice, native_target_bindings=(wall, annotation, extra))
    with pytest.raises(ProviderBindingError) as exc:
        _validate_request_and_snapshot(make_request(execution_slice, snapshot=extraneous))
    assert exc.value.code == "PROVIDER_NATIVE_BINDING_EXTRANEOUS"


def test_candidate_fingerprint_schema_and_scope_are_verified(execution_slice):
    candidate = make_candidate()
    bad_fingerprint = replace(candidate, candidate_fingerprint=digest("wrong-candidate"))
    snapshot = make_snapshot(execution_slice, provider_candidates=(bad_fingerprint,))
    with pytest.raises(ProviderBindingError) as exc:
        _validate_request_and_snapshot(make_request(execution_slice, snapshot=snapshot))
    assert exc.value.code == "PROVIDER_CANDIDATE_INVALID"

    invalid_schema = make_candidate(provider_input_schema={"type": 42})
    snapshot = make_snapshot(execution_slice, provider_candidates=(invalid_schema,))
    with pytest.raises(ProviderBindingError) as exc:
        _validate_request_and_snapshot(make_request(execution_slice, snapshot=snapshot))
    assert exc.value.code == "PROVIDER_CANDIDATE_INVALID"

    unrelated = make_candidate(canonical_operation="rotate.v1")
    snapshot = make_snapshot(execution_slice, provider_candidates=(unrelated,))
    with pytest.raises(ProviderBindingError) as exc:
        _validate_request_and_snapshot(make_request(execution_slice, snapshot=snapshot))
    assert exc.value.code == "PROVIDER_CANDIDATE_INVALID"


def test_snapshot_hash_and_expiry_are_verified(execution_slice, valid_snapshot):
    bad_hash = replace(valid_snapshot, snapshot_hash=digest("wrong-snapshot"))
    with pytest.raises(ProviderBindingError) as exc:
        _validate_request_and_snapshot(make_request(execution_slice, snapshot=bad_hash))
    assert exc.value.code == "PROVIDER_SNAPSHOT_HASH_MISMATCH"

    for admission_time in ("2026-08-30T10:30:00Z", "2026-08-30T10:31:00Z"):
        with pytest.raises(ProviderBindingError) as exc:
            _validate_request_and_snapshot(
                make_request(
                    execution_slice,
                    snapshot=valid_snapshot,
                    admission_time=admission_time,
                )
            )
        assert exc.value.code == "PROVIDER_SNAPSHOT_EXPIRED"


def test_valid_snapshot_returns_exact_native_map_and_candidates(valid_request, execution_slice):
    native_by_id, candidates = _validate_request_and_snapshot(valid_request)
    expected_targets = {
        target for unit in execution_slice.execution_units for target in unit.targets
    }
    assert set(native_by_id) == expected_targets
    assert len(candidates) == 1


@pytest.mark.parametrize(
    "candidate",
    (
        make_candidate(canonical_operation="rotate.v1"),
        make_candidate(compatible_operation_versions=("2.0.0",)),
        make_candidate(native_kinds=("Door",)),
    ),
)
def test_operation_version_or_native_constraint_mismatch_filters_candidate(
    execution_slice, valid_request, candidate
):
    native_by_id, _ = _validate_request_and_snapshot(valid_request)
    unit = execution_slice.execution_units[0]
    with pytest.raises(ProviderBindingError) as exc:
        _select_candidate(unit, _unit_native_targets(unit, native_by_id), (candidate,))
    assert exc.value.code == "PROVIDER_CANDIDATE_UNAVAILABLE"


@pytest.mark.parametrize(
    "field",
    (
        "trust_state",
        "compatibility_state",
        "health_state",
        "license_state",
        "certification_state",
    ),
)
@pytest.mark.parametrize("state", (EligibilityState.UNSATISFIED, EligibilityState.UNKNOWN))
def test_non_satisfied_eligibility_dimension_filters_candidate(
    execution_slice, valid_request, field, state
):
    native_by_id, _ = _validate_request_and_snapshot(valid_request)
    unit = execution_slice.execution_units[0]
    candidate = make_candidate(**{field: state})
    with pytest.raises(ProviderBindingError) as exc:
        _select_candidate(unit, _unit_native_targets(unit, native_by_id), (candidate,))
    assert exc.value.code == "PROVIDER_CANDIDATE_UNAVAILABLE"


def test_lower_policy_priority_wins_and_input_order_does_not_matter(
    execution_slice, valid_request
):
    native_by_id, _ = _validate_request_and_snapshot(valid_request)
    unit = execution_slice.execution_units[0]
    high = make_candidate(provider_server="provider.high", priority=20)
    low = make_candidate(provider_server="provider.low", priority=5)
    targets = _unit_native_targets(unit, native_by_id)
    assert _select_candidate(unit, targets, (high, low)).provider_server == "provider.low"
    assert _select_candidate(unit, targets, (low, high)).provider_server == "provider.low"


def test_equal_priority_uses_stable_provider_identity_order(execution_slice, valid_request):
    native_by_id, _ = _validate_request_and_snapshot(valid_request)
    unit = execution_slice.execution_units[0]
    targets = _unit_native_targets(unit, native_by_id)
    later = make_candidate(provider_server="provider.b", provider_tool="z", priority=10)
    earlier = make_candidate(provider_server="provider.a", provider_tool="z", priority=10)
    assert _select_candidate(unit, targets, (later, earlier)).provider_server == "provider.a"


def test_repeated_winning_rank_identity_is_ambiguous_even_if_fingerprint_matches(
    execution_slice, valid_request
):
    native_by_id, _ = _validate_request_and_snapshot(valid_request)
    unit = execution_slice.execution_units[0]
    targets = _unit_native_targets(unit, native_by_id)
    winner = make_candidate(priority=1)
    duplicate = replace(winner)
    with pytest.raises(ProviderBindingError) as exc:
        _select_candidate(unit, targets, (winner, duplicate))
    assert exc.value.code == "PROVIDER_CANDIDATE_AMBIGUOUS"

    conflicting = replace(winner, candidate_fingerprint=digest("different-fingerprint"))
    with pytest.raises(ProviderBindingError) as exc:
        _select_candidate(unit, targets, (winner, conflicting))
    assert exc.value.code == "PROVIDER_CANDIDATE_AMBIGUOUS"
