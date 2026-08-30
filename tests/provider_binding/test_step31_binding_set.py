from __future__ import annotations

from dataclasses import replace

import pytest
from design_provider_binding import (
    ProviderBindingAdapterRegistry,
    ProviderBindingError,
    ProviderResolver,
    compute_binding_set_hash,
    validate_provider_binding_set,
)
from conftest import (
    FakeBindingAdapter,
    digest,
    default_native_bindings,
    make_candidate,
    make_request,
    make_snapshot,
)


def _registry(*registrations):
    registry = ProviderBindingAdapterRegistry()
    for provider_server, adapter in registrations:
        registry.register(provider_server, adapter)
    return registry


def _resolve(execution_slice, snapshot, registry, admission_time="2026-08-30T10:00:00Z"):
    return ProviderResolver(registry).resolve(
        make_request(
            execution_slice,
            snapshot=snapshot,
            admission_time=admission_time,
        )
    )


def _default_result(execution_slice):
    snapshot = make_snapshot(execution_slice)
    adapter = FakeBindingAdapter()
    result = _resolve(
        execution_slice,
        snapshot,
        _registry(("provider.revit.a", adapter)),
    )
    return result, snapshot


def test_resolver_result_passes_public_binding_set_validator(execution_slice):
    binding_set, _ = _default_result(execution_slice)
    validate_provider_binding_set(binding_set, execution_slice)


@pytest.mark.parametrize(
    "mode",
    ("missing", "duplicate", "extraneous"),
)
def test_binding_set_requires_exactly_one_binding_per_execution_unit(execution_slice, mode):
    binding_set, _ = _default_result(execution_slice)
    first, second = binding_set.bindings
    if mode == "missing":
        bindings = (first,)
    elif mode == "duplicate":
        bindings = (first, first)
    else:
        bindings = (first, replace(second, execution_unit_id="EU-EXTRANEOUS"))
    malformed = replace(binding_set, bindings=bindings)
    with pytest.raises(ProviderBindingError) as exc:
        validate_provider_binding_set(malformed, execution_slice)
    assert exc.value.code == "PROVIDER_BINDING_SET_INVALID"


@pytest.mark.parametrize(
    "change",
    (
        {"execution_slice_id": "XS-WRONG"},
        {"execution_slice_hash": digest("wrong-slice")},
    ),
)
def test_binding_set_slice_identity_must_match_exact_execution_slice(execution_slice, change):
    binding_set, _ = _default_result(execution_slice)
    malformed = replace(binding_set, **change)
    with pytest.raises(ProviderBindingError) as exc:
        validate_provider_binding_set(malformed, execution_slice)
    assert exc.value.code == "PROVIDER_BINDING_SET_INVALID"


def test_each_binding_must_reference_exact_slice(execution_slice):
    binding_set, _ = _default_result(execution_slice)
    first, second = binding_set.bindings
    malformed_binding = replace(first, execution_slice_id="XS-WRONG")
    malformed = replace(binding_set, bindings=(malformed_binding, second))
    with pytest.raises(ProviderBindingError) as exc:
        validate_provider_binding_set(malformed, execution_slice)
    assert exc.value.code == "PROVIDER_BINDING_SET_INVALID"


def test_each_binding_unit_hash_must_match_exact_execution_unit(execution_slice):
    binding_set, _ = _default_result(execution_slice)
    first, second = binding_set.bindings
    malformed_binding = replace(first, execution_unit_hash=digest("wrong-unit-hash"))
    malformed = replace(binding_set, bindings=(malformed_binding, second))
    with pytest.raises(ProviderBindingError) as exc:
        validate_provider_binding_set(malformed, execution_slice)
    assert exc.value.code == "PROVIDER_BINDING_SET_INVALID"


def test_tampered_binding_semantic_hash_retains_binding_hash_error(execution_slice):
    binding_set, _ = _default_result(execution_slice)
    first, second = binding_set.bindings
    malformed_binding = replace(first, binding_hash=digest("tampered-binding"))
    malformed = replace(binding_set, bindings=(malformed_binding, second))
    with pytest.raises(ProviderBindingError) as exc:
        validate_provider_binding_set(malformed, execution_slice)
    assert exc.value.code == "PROVIDER_BINDING_HASH_MISMATCH"


def test_set_hash_is_exactly_over_full_binding_hashes(execution_slice):
    binding_set, _ = _default_result(execution_slice)
    expected = compute_binding_set_hash(
        execution_slice_hash=execution_slice.execution_slice_hash,
        binding_hashes=(binding.binding_hash for binding in binding_set.bindings),
    )
    assert binding_set.binding_set_hash == expected
    assert binding_set.binding_set_id == f"PBS-{expected[:12]}"
    validate_provider_binding_set(binding_set, execution_slice)


def test_snapshot_native_and_candidate_input_order_do_not_change_binding_identity(execution_slice):
    winner = make_candidate(provider_server="provider.winner", priority=1)
    unused = make_candidate(provider_server="provider.unused", priority=20)
    rows = default_native_bindings(execution_slice)
    forward_snapshot = make_snapshot(
        execution_slice,
        native_target_bindings=rows,
        provider_candidates=(winner, unused),
    )
    reverse_snapshot = make_snapshot(
        execution_slice,
        native_target_bindings=tuple(reversed(rows)),
        provider_candidates=(unused, winner),
    )
    forward = _resolve(
        execution_slice,
        forward_snapshot,
        _registry((winner.provider_server, FakeBindingAdapter())),
    )
    reverse = _resolve(
        execution_slice,
        reverse_snapshot,
        _registry((winner.provider_server, FakeBindingAdapter())),
    )
    assert forward_snapshot.snapshot_hash == reverse_snapshot.snapshot_hash
    assert tuple(item.binding_hash for item in forward.bindings) == tuple(
        item.binding_hash for item in reverse.bindings
    )
    assert forward.binding_set_hash == reverse.binding_set_hash


def test_adapter_registration_order_does_not_change_binding_identity(execution_slice):
    winner = make_candidate(provider_server="provider.a", priority=1)
    other = make_candidate(provider_server="provider.b", priority=10)
    snapshot = make_snapshot(execution_slice, provider_candidates=(other, winner))

    forward = _resolve(
        execution_slice,
        snapshot,
        _registry(
            (winner.provider_server, FakeBindingAdapter()),
            (other.provider_server, FakeBindingAdapter()),
        ),
    )
    reverse = _resolve(
        execution_slice,
        snapshot,
        _registry(
            (other.provider_server, FakeBindingAdapter()),
            (winner.provider_server, FakeBindingAdapter()),
        ),
    )
    assert forward.binding_set_hash == reverse.binding_set_hash
    assert tuple(item.binding_hash for item in forward.bindings) == tuple(
        item.binding_hash for item in reverse.bindings
    )


def test_admission_time_before_same_expiry_does_not_enter_binding_semantics(execution_slice):
    snapshot = make_snapshot(execution_slice, valid_until="2026-08-30T10:30:00Z")
    early = _resolve(
        execution_slice,
        snapshot,
        _registry(("provider.revit.a", FakeBindingAdapter())),
        admission_time="2026-08-30T09:00:00Z",
    )
    later = _resolve(
        execution_slice,
        snapshot,
        _registry(("provider.revit.a", FakeBindingAdapter())),
        admission_time="2026-08-30T10:29:59Z",
    )
    assert early.binding_set_hash == later.binding_set_hash
    assert tuple(item.binding_hash for item in early.bindings) == tuple(
        item.binding_hash for item in later.bindings
    )


def test_unused_candidate_change_updates_provenance_not_authorization_identity(execution_slice):
    winner = make_candidate(provider_server="provider.winner", priority=1)
    unused_a = make_candidate(provider_server="provider.unused.a", priority=20)
    unused_b = make_candidate(provider_server="provider.unused.b", priority=20)
    first_snapshot = make_snapshot(
        execution_slice,
        snapshot_id="PES-FIRST",
        provider_candidates=(winner, unused_a),
    )
    second_snapshot = make_snapshot(
        execution_slice,
        snapshot_id="PES-SECOND",
        provider_candidates=(unused_b, winner),
    )

    first = _resolve(
        execution_slice,
        first_snapshot,
        _registry((winner.provider_server, FakeBindingAdapter())),
    )
    second = _resolve(
        execution_slice,
        second_snapshot,
        _registry((winner.provider_server, FakeBindingAdapter())),
    )

    assert first_snapshot.snapshot_hash != second_snapshot.snapshot_hash
    assert first.provider_execution_snapshot_hash != second.provider_execution_snapshot_hash
    assert first.provider_execution_snapshot_id != second.provider_execution_snapshot_id
    assert tuple(item.binding_hash for item in first.bindings) == tuple(
        item.binding_hash for item in second.bindings
    )
    assert first.binding_set_hash == second.binding_set_hash


def test_snapshot_id_alone_is_provenance_not_authorization_material(execution_slice):
    first_snapshot = make_snapshot(execution_slice, snapshot_id="PES-FIRST")
    second_snapshot = make_snapshot(execution_slice, snapshot_id="PES-SECOND")
    first = _resolve(
        execution_slice,
        first_snapshot,
        _registry(("provider.revit.a", FakeBindingAdapter())),
    )
    second = _resolve(
        execution_slice,
        second_snapshot,
        _registry(("provider.revit.a", FakeBindingAdapter())),
    )
    assert first_snapshot.snapshot_hash == second_snapshot.snapshot_hash
    assert first.provider_execution_snapshot_id != second.provider_execution_snapshot_id
    assert first.binding_set_hash == second.binding_set_hash


def test_provider_switch_changes_step31_identity_without_changing_step30_identity(execution_slice):
    provider_a_first = (
        make_candidate(provider_server="provider.a", priority=1),
        make_candidate(provider_server="provider.b", priority=20),
    )
    provider_b_first = (
        make_candidate(provider_server="provider.a", priority=20),
        make_candidate(provider_server="provider.b", priority=1),
    )
    snapshot_a = make_snapshot(execution_slice, provider_candidates=provider_a_first)
    snapshot_b = make_snapshot(execution_slice, provider_candidates=provider_b_first)

    registry_a = _registry(
        ("provider.a", FakeBindingAdapter()),
        ("provider.b", FakeBindingAdapter()),
    )
    registry_b = _registry(
        ("provider.b", FakeBindingAdapter()),
        ("provider.a", FakeBindingAdapter()),
    )
    result_a = _resolve(execution_slice, snapshot_a, registry_a)
    result_b = _resolve(execution_slice, snapshot_b, registry_b)

    assert execution_slice.execution_slice_hash == result_a.execution_slice_hash
    assert execution_slice.execution_slice_hash == result_b.execution_slice_hash
    assert tuple(unit.execution_unit_hash for unit in execution_slice.execution_units) == tuple(
        binding.execution_unit_hash for binding in result_a.bindings
    )
    assert tuple(unit.execution_unit_hash for unit in execution_slice.execution_units) == tuple(
        binding.execution_unit_hash for binding in result_b.bindings
    )
    assert {binding.provider_server for binding in result_a.bindings} == {"provider.a"}
    assert {binding.provider_server for binding in result_b.bindings} == {"provider.b"}
    assert result_a.binding_set_hash != result_b.binding_set_hash
    assert tuple(binding.binding_hash for binding in result_a.bindings) != tuple(
        binding.binding_hash for binding in result_b.bindings
    )


def test_binding_expiry_change_changes_binding_and_set_hashes(execution_slice):
    first_snapshot = make_snapshot(execution_slice, valid_until="2026-08-30T10:30:00Z")
    second_snapshot = make_snapshot(execution_slice, valid_until="2026-08-30T10:31:00Z")
    first = _resolve(
        execution_slice,
        first_snapshot,
        _registry(("provider.revit.a", FakeBindingAdapter())),
    )
    second = _resolve(
        execution_slice,
        second_snapshot,
        _registry(("provider.revit.a", FakeBindingAdapter())),
    )
    assert {binding.binding_expires_at for binding in first.bindings} == {
        "2026-08-30T10:30:00Z"
    }
    assert {binding.binding_expires_at for binding in second.bindings} == {
        "2026-08-30T10:31:00Z"
    }
    assert tuple(binding.binding_hash for binding in first.bindings) != tuple(
        binding.binding_hash for binding in second.bindings
    )
    assert first.binding_set_hash != second.binding_set_hash
