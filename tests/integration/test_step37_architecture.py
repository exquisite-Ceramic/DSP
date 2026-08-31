import importlib.util
import inspect
import sys
from pathlib import Path

from design_execution_coordination import (
    CoordinationStatus,
    ExecutionSagaCoordinator,
    HostFailed,
    HostFailurePhase,
)
from design_execution_reconciliation import (
    ExecutionReconciliationService,
    InMemoryExecutionSagaStore,
    SliceReconciliationStatus,
)

CORE = Path("platform/execution_coordination/src/design_execution_coordination")
STEP33 = Path("platform/execution_reconciliation/src/design_execution_reconciliation")
FIXTURE_BUILDERS = Path(__file__).parents[1] / "execution_coordination" / "conftest.py"


def _load_fixture_builders():
    module_name = "_step37_fixture_builders"
    spec = importlib.util.spec_from_file_location(module_name, FIXTURE_BUILDERS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Step37 fixture builders from {FIXTURE_BUILDERS}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_FIXTURE_BUILDERS_MODULE = _load_fixture_builders()
_build_authority_for_slice = _FIXTURE_BUILDERS_MODULE._build_authority_for_slice
_build_three_slice_transaction = _FIXTURE_BUILDERS_MODULE._build_three_slice_transaction


def _source(root):
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(root.glob("*.py"))
    )


def test_step37_core_has_no_native_host_vocabulary():
    text = _source(CORE)
    for forbidden in (
        "Autodesk.AutoCAD",
        "GetOffsetCurves",
        "LWPOLYLINE",
        "Autodesk.Revit",
        "TransactionGroup",
    ):
        assert forbidden not in text


def test_step33_does_not_depend_on_step37():
    assert "design_execution_coordination" not in _source(STEP33)


def test_failure_injection_is_test_only():
    text = _source(CORE)
    assert "debug_failure_mode" not in text
    assert "failure_injection" not in text


def test_coordinator_has_no_inverse_host_command_api():
    params = inspect.signature(ExecutionSagaCoordinator.execute).parameters
    assert not {
        name
        for name in params
        if any(word in name for word in ("command", "inverse", "rollback"))
    }


class _SpyReconciliation:
    def __init__(self, delegate):
        self.delegate = delegate
        self.fail_slice_before_commit_calls = 0

    def fail_slice_before_commit(self, *args, **kwargs):
        self.fail_slice_before_commit_calls += 1
        return self.delegate.fail_slice_before_commit(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class _AuthorityPort:
    def __init__(self, authority):
        self.authority = authority
        self.calls = []

    def admit(self, execution_slice):
        self.calls.append(execution_slice.execution_slice_hash)
        return self.authority


class _UnknownCommitHost:
    def __init__(self):
        self.calls = []

    def execute(self, execution_slice, authority):
        self.calls.append((execution_slice.execution_slice_hash, authority.grant_hash))
        return HostFailed(
            phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
            failure_ref="HOST-ACK-LOST-ARCH-GUARD",
            failed_at="2026-08-31T13:40:00Z",
        )


class _HostRegistry:
    def __init__(self, runtime_ref, host):
        self.runtime_ref = runtime_ref
        self.host = host
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        assert runtime_ref == self.runtime_ref
        return self.host


class _NoEvidencePort:
    def build_bundle(self, **kwargs):
        raise AssertionError("unknown commit must not request verification evidence")


class _Clock:
    def now(self):
        return "2026-08-31T13:39:00Z"


def test_unknown_commit_never_persists_false_precommit_failure():
    transaction = _build_three_slice_transaction()
    reconciliation = ExecutionReconciliationService(
        store=InMemoryExecutionSagaStore()
    )
    stored = reconciliation.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    first_hash = stored.definition.ordered_slice_hashes[0]
    first_slice = next(
        item
        for item in transaction.execution_plan.execution_slices
        if item.execution_slice_hash == first_hash
    )
    authority = _build_authority_for_slice(transaction, first_slice)
    spy = _SpyReconciliation(reconciliation)
    authority_port = _AuthorityPort(authority)
    host = _UnknownCommitHost()
    registry = _HostRegistry(first_slice.host_runtime_ref, host)
    coordinator = ExecutionSagaCoordinator(
        reconciliation=spy,
        authority_port=authority_port,
        host_registry=registry,
        evidence_port=_NoEvidencePort(),
        clock=_Clock(),
    )

    result = coordinator.execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert result.status is CoordinationStatus.RECOVERY_REQUIRED
    assert result.active_slice_hash == first_hash
    assert result.failure_ref == "HOST-ACK-LOST-ARCH-GUARD"
    assert spy.fail_slice_before_commit_calls == 0
    assert authority_port.calls == [first_hash]
    assert len(host.calls) == 1

    final = reconciliation.get_saga(stored.definition.saga_id)
    assert final is not None
    first_state = next(
        state for state in final.slice_states if state.execution_slice_hash == first_hash
    )
    assert first_state.status is SliceReconciliationStatus.ADMITTED
    assert first_state.actual_delta_hash is None
