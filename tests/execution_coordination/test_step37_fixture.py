def test_step37_fixture_has_three_slices_and_multiple_runtime_identities(
    step37_three_slice_transaction,
):
    plan = step37_three_slice_transaction.execution_plan
    assert len(plan.execution_slices) == 3
    runtime_refs = tuple(slice_.host_runtime_ref for slice_ in plan.execution_slices)
    assert len(set(runtime_refs)) == 3
    assert {ref.host_instance_id for ref in runtime_refs} == {
        "HOST-STEP37-A",
        "HOST-STEP37-B",
        "HOST-STEP37-C",
    }
