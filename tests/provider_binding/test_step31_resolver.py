from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_planning import (
    ExecutionSlice,
    ExecutionUnit,
    compute_execution_slice_hash,
    compute_execution_unit_hash,
)

from design_provider_binding import (
    ProviderBindingAdapterRegistry,
    ProviderBindingError,
    ProviderBindingMaterial,
    ProviderPreconditionBinding,
    ProviderResolver,
    compute_precondition_fingerprint,
    validate_provider_binding,
)
from conftest import (
    FakeBindingAdapter,
    digest,
    make_candidate,
    make_native_binding,
    make_request,
    make_snapshot,
)


def _provider_args(unit, native_rows):
    return {
        "native_ids": [item.native_id for item in native_rows],
        "operation": unit.canonical_operation,
        "canonical_arguments": dict(unit.arguments),
    }


def _multitarget_slice(base: ExecutionSlice) -> ExecutionSlice:
    template = base.execution_units[0]
    targets = ("WALL-001", "WALL-002")
    unit_hash = compute_execution_unit_hash(
        changeset_hash=base.changeset_hash,
        source_operation_hash=template.source_operation_hash,
        canonical_operation=template.canonical_operation,
        canonical_operation_version=template.canonical_operation_version,
        canonical_definition_fingerprint=template.canonical_definition_fingerprint,
        targets=targets,
        arguments=template.arguments,
        preconditions=template.preconditions,
        expected_effects=template.expected_effects,
    )
    unit = ExecutionUnit(
        f"EU-{unit_hash[:12]}",
        template.source_operation_id,
        template.source_operation_hash,
        template.canonical_operation,
        template.canonical_operation_version,
        template.canonical_definition_fingerprint,
        targets,
        template.arguments,
        template.preconditions,
        template.expected_effects,
        unit_hash,
    )
    slice_hash = compute_execution_slice_hash(
        changeset_hash=base.changeset_hash,
        scope_hash=base.approved_scope_ref.scope_hash,
        execution_slice_scope_rule_id=base.approved_scope_ref.execution_slice_scope_rule_id,
        host_runtime_ref=base.host_runtime_ref,
        execution_unit_hashes=(unit_hash,),
    )
    return ExecutionSlice(
        f"XS-{slice_hash[:12]}",
        base.changeset_id,
        base.changeset_hash,
        base.host_runtime_ref,
        base.approved_scope_ref,
        (unit,),
        slice_hash,
    )


def _registry(provider_server: str, adapter: FakeBindingAdapter):
    registry = ProviderBindingAdapterRegistry()
    registry.register(provider_server, adapter)
    return registry


def test_resolver_requires_adapter_registry():
    with pytest.raises(TypeError):
        ProviderResolver("not-a-registry")


def test_each_unit_produces_exactly_one_binding_with_frozen_upstream_identity(
    execution_slice,
    valid_request,
    fake_adapter,
):
    resolver = ProviderResolver(_registry("provider.revit.a", fake_adapter))
    binding_set = resolver.resolve(valid_request)

    assert len(binding_set.bindings) == len(execution_slice.execution_units) == 2
    by_unit = {binding.execution_unit_id: binding for binding in binding_set.bindings}
    assert set(by_unit) == {unit.execution_unit_id for unit in execution_slice.execution_units}

    for unit in execution_slice.execution_units:
        binding = by_unit[unit.execution_unit_id]
        assert binding.execution_unit_hash == unit.execution_unit_hash
        assert binding.execution_slice_id == execution_slice.execution_slice_id
        assert binding.execution_slice_hash == execution_slice.execution_slice_hash
        assert binding.canonical_operation == unit.canonical_operation
        assert binding.provider_server == "provider.revit.a"
        assert binding.provider_tool == "move"
        assert binding.provider_version == "1.0.0"
        assert binding.input_adapter_version == "1.0.0"
        assert binding.host_instance_id == execution_slice.host_runtime_ref.host_instance_id
        assert binding.document_ref == execution_slice.host_runtime_ref.document_ref
        assert binding.binding_expires_at == valid_request.provider_execution_snapshot.valid_until
        assert binding.binding_id == f"PB-{binding.binding_hash[:12]}"
        validate_provider_binding(binding)

    assert len(fake_adapter.calls) == 2
    for called_unit, called_runtime, selected, native_rows in fake_adapter.calls:
        assert called_runtime == execution_slice.host_runtime_ref
        assert selected.provider_server == "provider.revit.a"
        assert tuple(item.semantic_id for item in native_rows) == called_unit.targets


def test_selected_provider_identity_and_contracts_come_from_candidate(execution_slice):
    candidate = make_candidate(
        provider_server="provider.authoritative",
        provider_tool="native.translate",
        provider_version="4.2.0",
        input_adapter_version="3.1.0",
    )
    snapshot = make_snapshot(execution_slice, provider_candidates=(candidate,))
    adapter = FakeBindingAdapter(adapter_version="3.1.0")
    binding_set = ProviderResolver(
        _registry("provider.authoritative", adapter)
    ).resolve(make_request(execution_slice, snapshot=snapshot))
    for binding in binding_set.bindings:
        assert binding.provider_server == candidate.provider_server
        assert binding.provider_tool == candidate.provider_tool
        assert binding.provider_version == candidate.provider_version
        assert binding.input_adapter_version == candidate.input_adapter_version
        assert dict(binding.verification_contract) == dict(candidate.verification_contract)
        assert dict(binding.rollback_contract) == dict(candidate.rollback_contract)


@pytest.mark.parametrize("mode", ("missing", "extra", "substituted", "duplicate"))
def test_adapter_native_target_mismatch_fails_closed(execution_slice, mode):
    slice_ = _multitarget_slice(execution_slice)
    rows = (
        make_native_binding("WALL-001", native_id="NATIVE-WALL-1", native_kind="Wall"),
        make_native_binding("WALL-002", native_id="NATIVE-WALL-2", native_kind="Wall"),
    )
    candidate = make_candidate(native_kinds=("Wall",))
    snapshot = make_snapshot(
        slice_,
        native_target_bindings=rows,
        provider_candidates=(candidate,),
    )

    def material_factory(unit, native_rows):
        if mode == "missing":
            returned = native_rows[:1]
        elif mode == "extra":
            returned = (*native_rows, make_native_binding("EXTRA-003", native_id="EXTRA", native_kind="Wall"))
        elif mode == "substituted":
            returned = (
                native_rows[0],
                make_native_binding("OTHER-002", native_id="NATIVE-WALL-2", native_kind="Wall"),
            )
        else:
            returned = (native_rows[0], native_rows[0])
        return ProviderBindingMaterial(
            returned,
            _provider_args(unit, returned),
            (),
            {"variant": "default"},
        )

    adapter = FakeBindingAdapter(material_factory=material_factory)
    resolver = ProviderResolver(_registry(candidate.provider_server, adapter))
    with pytest.raises(ProviderBindingError) as exc:
        resolver.resolve(make_request(slice_, snapshot=snapshot))
    assert exc.value.code == "PROVIDER_NATIVE_TARGET_MISMATCH"


def test_adapter_may_emit_valid_optional_provider_precondition(execution_slice, valid_snapshot):
    unit = execution_slice.execution_units[0]
    source_fp = compute_precondition_fingerprint(unit.preconditions[0])

    def material_factory(called_unit, native_rows):
        return ProviderBindingMaterial(
            native_rows,
            _provider_args(called_unit, native_rows),
            (ProviderPreconditionBinding(source_fp, {"revision": "R-31"}),),
            {"variant": "default"},
        )

    adapter = FakeBindingAdapter(material_factory=material_factory)
    result = ProviderResolver(_registry("provider.revit.a", adapter)).resolve(
        make_request(execution_slice, snapshot=valid_snapshot)
    )
    assert any(binding.provider_preconditions for binding in result.bindings)


@pytest.mark.parametrize("mode", ("unknown", "duplicate"))
def test_provider_precondition_source_reference_must_be_real_and_unique(
    execution_slice,
    valid_snapshot,
    mode,
):
    valid_fp = compute_precondition_fingerprint(execution_slice.execution_units[0].preconditions[0])

    def material_factory(unit, native_rows):
        source_fp = digest("unknown-precondition") if mode == "unknown" else valid_fp
        row = ProviderPreconditionBinding(source_fp, {"revision": "R-31"})
        preconditions = (row, row) if mode == "duplicate" else (row,)
        return ProviderBindingMaterial(
            native_rows,
            _provider_args(unit, native_rows),
            preconditions,
            {"variant": "default"},
        )

    adapter = FakeBindingAdapter(material_factory=material_factory)
    with pytest.raises(ProviderBindingError) as exc:
        ProviderResolver(_registry("provider.revit.a", adapter)).resolve(
            make_request(execution_slice, snapshot=valid_snapshot)
        )
    assert exc.value.code == "PROVIDER_BINDING_ADAPTATION_FAILED"


def test_provider_arguments_must_satisfy_selected_schema(execution_slice, valid_snapshot):
    adapter = FakeBindingAdapter(
        material_factory=lambda unit, native_rows: ProviderBindingMaterial(
            native_rows,
            {},
            (),
            {"variant": "default"},
        )
    )
    with pytest.raises(ProviderBindingError) as exc:
        ProviderResolver(_registry("provider.revit.a", adapter)).resolve(
            make_request(execution_slice, snapshot=valid_snapshot)
        )
    assert exc.value.code == "PROVIDER_INPUT_SCHEMA_INVALID"


@pytest.mark.parametrize(
    "adapter",
    (
        FakeBindingAdapter(material_factory=lambda unit, native_rows: {"not": "material"}),
        FakeBindingAdapter(error=RuntimeError("adapter failure")),
    ),
)
def test_adapter_wrong_return_type_or_exception_fails_as_adaptation(
    execution_slice,
    valid_snapshot,
    adapter,
):
    with pytest.raises(ProviderBindingError) as exc:
        ProviderResolver(_registry("provider.revit.a", adapter)).resolve(
            make_request(execution_slice, snapshot=valid_snapshot)
        )
    assert exc.value.code == "PROVIDER_BINDING_ADAPTATION_FAILED"
    assert len(adapter.calls) == 1


def test_selected_adapter_failure_never_falls_back_to_lower_ranked_provider(execution_slice):
    winner = make_candidate(provider_server="provider.winner", priority=1)
    loser = make_candidate(provider_server="provider.loser", priority=2)
    snapshot = make_snapshot(execution_slice, provider_candidates=(loser, winner))
    winner_adapter = FakeBindingAdapter(error=RuntimeError("winner failed"))
    loser_adapter = FakeBindingAdapter()
    registry = ProviderBindingAdapterRegistry()
    registry.register(winner.provider_server, winner_adapter)
    registry.register(loser.provider_server, loser_adapter)

    with pytest.raises(ProviderBindingError) as exc:
        ProviderResolver(registry).resolve(make_request(execution_slice, snapshot=snapshot))
    assert exc.value.code == "PROVIDER_BINDING_ADAPTATION_FAILED"
    assert len(winner_adapter.calls) == 1
    assert len(loser_adapter.calls) == 0


@pytest.mark.parametrize("version_mismatch", (False, True))
def test_missing_or_version_mismatched_winner_adapter_never_falls_back(
    execution_slice,
    version_mismatch,
):
    winner = make_candidate(
        provider_server="provider.winner",
        priority=1,
        input_adapter_version="2.0.0" if version_mismatch else "1.0.0",
    )
    loser = make_candidate(provider_server="provider.loser", priority=2)
    snapshot = make_snapshot(execution_slice, provider_candidates=(winner, loser))
    loser_adapter = FakeBindingAdapter()
    registry = ProviderBindingAdapterRegistry()
    registry.register(loser.provider_server, loser_adapter)
    if version_mismatch:
        registry.register(winner.provider_server, FakeBindingAdapter(adapter_version="1.0.0"))

    with pytest.raises(ProviderBindingError) as exc:
        ProviderResolver(registry).resolve(make_request(execution_slice, snapshot=snapshot))
    assert exc.value.code == "PROVIDER_ADAPTER_UNAVAILABLE"
    assert len(loser_adapter.calls) == 0
