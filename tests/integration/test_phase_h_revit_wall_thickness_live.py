"""Controlled live Revit acceptance gate for Phase H wall-thickness closure."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from revit_sidecar.design_fact_adapter import DesignFactAdapter
from revit_sidecar.execution_result_adapter import RevitExecutionResultAdapter
from revit_sidecar.model_adapter import RevitHostAdapter
from revit_sidecar.named_pipe import NamedPipeTransport


REPO_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED_LIVE_ENV = (
    "DSP_REVIT_VERSION",
    "DSP_REVIT_TFM",
    "DSP_REVIT_API_DIR",
    "DSP_REVIT_PIPE",
    "DSP_REVIT_FIXTURE",
)
_REVISION_PROBE_SENTINEL = 2_147_483_647


def _live_skip_reason() -> str | None:
    if os.environ.get("DSP_REVIT_LIVE") != "1":
        return "set DSP_REVIT_LIVE=1 to run the real Revit acceptance gate"
    missing = tuple(name for name in _REQUIRED_LIVE_ENV if not os.environ.get(name))
    if missing:
        return "missing live Revit environment: " + ", ".join(missing)
    return None


_LIVE_SKIP_REASON = _live_skip_reason()
pytestmark = pytest.mark.skipif(
    _LIVE_SKIP_REASON is not None,
    reason=_LIVE_SKIP_REASON or "live Revit gate disabled",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_fixture_manifest(fixture_path: Path) -> dict[str, str]:
    if not fixture_path.is_file():
        pytest.fail(f"DSP_REVIT_FIXTURE does not exist: {fixture_path}")

    manifest_path = fixture_path.with_suffix(".phase-h.json")
    if not manifest_path.is_file():
        pytest.fail(
            "controlled fixture manifest is missing: "
            f"{manifest_path}; see docs/runbooks/revit-wall-thickness-gap-closure.md"
        )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        pytest.fail("fixture manifest must be a JSON object")

    required = (
        "rvt_sha256",
        "isolated_wall_unique_id",
        "shared_type_wall_unique_id",
        "insert_wall_unique_id",
        "join_wall_unique_id",
    )
    normalized: dict[str, str] = {}
    for field in required:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            pytest.fail(f"fixture manifest field {field!r} must be a non-empty string")
        normalized[field] = value.strip()

    actual_hash = _sha256_file(fixture_path)
    if normalized["rvt_sha256"].lower() != actual_hash:
        pytest.fail(
            "DSP_REVIT_FIXTURE bytes differ from the reviewed manifest hash: "
            f"expected {normalized['rvt_sha256']}, got {actual_hash}"
        )

    scenario_ids = (
        normalized["isolated_wall_unique_id"],
        normalized["shared_type_wall_unique_id"],
        normalized["insert_wall_unique_id"],
        normalized["join_wall_unique_id"],
    )
    if len(set(scenario_ids)) != len(scenario_ids):
        pytest.fail("fixture scenario wall UniqueIds must be distinct")

    return normalized


def _command(
    *,
    wall_unique_id: str,
    expected_revision: int,
    thickness_mm: float,
    idempotency_key: str,
    command_id: str,
):
    return RevitHostAdapter.build_set_wall_thickness_command(
        command_id=command_id,
        document_id="DOC-REVIT",
        wall_unique_id=wall_unique_id,
        expected_revision=expected_revision,
        thickness_mm=thickness_mm,
        idempotency_key=idempotency_key,
    )


def _assert_before_commit(
    response: dict[str, Any],
    *,
    code: str,
    revision: int,
) -> None:
    assert response["status"] == "ERROR"
    assert response["error"]["code"] == code
    assert response["error"]["commit_state"] == "BEFORE_COMMIT"
    assert response["revision_after"] == revision
    assert response["replayed"] is False
    assert "payload" not in response
    assert "verification" not in response


def _probe_revision(
    transport: NamedPipeTransport,
    *,
    wall_unique_id: str,
    run_id: str,
    probe_name: str,
) -> int:
    response = transport.request(
        _command(
            wall_unique_id=wall_unique_id,
            expected_revision=_REVISION_PROBE_SENTINEL,
            thickness_mm=300.0,
            idempotency_key=f"phase-h-live-probe-{run_id}-{probe_name}",
            command_id=f"CMD-PH-LIVE-PROBE-{run_id}-{probe_name}",
        )
    )
    assert response["status"] == "ERROR"
    assert response["error"]["code"] == "REVISION_CONFLICT"
    assert response["error"]["commit_state"] == "BEFORE_COMMIT"
    current_revision = response["revision_after"]
    assert isinstance(current_revision, int)
    assert 0 <= current_revision < _REVISION_PROBE_SENTINEL
    assert response["replayed"] is False
    return current_revision


def _load_reconciliation_fixture_module() -> ModuleType:
    module_path = Path(__file__).with_name(
        "test_phase_h_revit_wall_thickness_reconciliation.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_phase_h_revit_reconciliation_fixture",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load reconciliation fixture module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_enterprise_terms(batch) -> dict[str, tuple[Any, str | None]]:
    import yaml

    catalog_path = (
        REPO_ROOT
        / "providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/data/"
        "enterprise_mappings_v1.yaml"
    )
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    rules = catalog["rules"]

    resolved: dict[str, tuple[Any, str | None]] = {}
    for fact in batch.facts:
        if fact.source_scheme is None or fact.source_code is None:
            continue
        matches: list[str] = []
        for rule in rules:
            if rule["source_scheme"] != fact.source_scheme:
                continue
            match = rule["match"]
            pattern = match["pattern"]
            candidate = fact.source_code
            if not match["case_sensitive"]:
                pattern = pattern.casefold()
                candidate = candidate.casefold()
            if match["type"] == "EXACT" and candidate == pattern:
                matches.append(rule["target_term_id"])
            elif match["type"] == "PREFIX" and candidate.startswith(pattern):
                matches.append(rule["target_term_id"])
        if matches:
            assert len(set(matches)) == 1
            resolved[matches[0]] = (fact.value, fact.unit)
    return resolved


def test_phase_h_live_revit_wall_thickness_acceptance() -> None:
    if os.name != "nt":
        pytest.fail("DSP_REVIT_LIVE=1 requires the real Windows Revit acceptance machine")

    fixture_path = Path(os.environ["DSP_REVIT_FIXTURE"]).resolve()
    manifest = _load_fixture_manifest(fixture_path)
    transport = NamedPipeTransport(pipe_name=os.environ["DSP_REVIT_PIPE"])
    run_id = uuid.uuid4().hex

    isolated = manifest["isolated_wall_unique_id"]
    current_revision = _probe_revision(
        transport,
        wall_unique_id=isolated,
        run_id=run_id,
        probe_name="baseline",
    )

    negative_cases = (
        (
            "shared",
            manifest["shared_type_wall_unique_id"],
            "SHARED_WALL_TYPE_OUTSIDE_SCOPE",
        ),
        (
            "insert",
            manifest["insert_wall_unique_id"],
            "WALL_INSERTS_OUTSIDE_MVP",
        ),
        (
            "join",
            manifest["join_wall_unique_id"],
            "WALL_JOIN_OUTSIDE_MVP",
        ),
    )
    observed_failures: dict[str, str] = {}
    for scenario, wall_unique_id, expected_code in negative_cases:
        response = transport.request(
            _command(
                wall_unique_id=wall_unique_id,
                expected_revision=current_revision,
                thickness_mm=300.0,
                idempotency_key=f"phase-h-live-{run_id}-{scenario}",
                command_id=f"CMD-PH-LIVE-{run_id}-{scenario}",
            )
        )
        _assert_before_commit(
            response,
            code=expected_code,
            revision=current_revision,
        )
        observed_failures[scenario] = expected_code
        assert (
            _probe_revision(
                transport,
                wall_unique_id=isolated,
                run_id=run_id,
                probe_name=f"after-{scenario}",
            )
            == current_revision
        )

    stale = transport.request(
        _command(
            wall_unique_id=isolated,
            expected_revision=current_revision + 1,
            thickness_mm=300.0,
            idempotency_key=f"phase-h-live-{run_id}-stale",
            command_id=f"CMD-PH-LIVE-{run_id}-stale",
        )
    )
    _assert_before_commit(
        stale,
        code="REVISION_CONFLICT",
        revision=current_revision,
    )
    observed_failures["stale_revision"] = "REVISION_CONFLICT"
    assert (
        _probe_revision(
            transport,
            wall_unique_id=isolated,
            run_id=run_id,
            probe_name="after-stale",
        )
        == current_revision
    )

    positive_key = f"phase-h-live-{run_id}-positive"
    positive_command = _command(
        wall_unique_id=isolated,
        expected_revision=current_revision,
        thickness_mm=300.0,
        idempotency_key=positive_key,
        command_id=f"CMD-PH-LIVE-{run_id}-positive",
    )
    success = transport.request(positive_command)

    assert success["status"] == "OK"
    assert success["replayed"] is False
    committed_revision = success["revision_after"]
    assert isinstance(committed_revision, int)
    assert committed_revision > current_revision

    payload = success["payload"]
    verification = success["verification"]
    assert payload["wall_unique_id"] == isolated
    assert payload["requested_width_mm"] == pytest.approx(300.0, abs=1e-6)
    assert payload["width_after_mm"] == pytest.approx(300.0, abs=1e-6)
    assert payload["transaction_attempt_count"] == 1
    assert not math.isclose(
        payload["width_before_internal"],
        payload["width_after_internal"],
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert verification["identity_invariant_proven"] is True
    assert verification["location_invariant_proven"] is True
    assert verification["relationship_invariant_proven"] is True
    assert verification["document_change_observed"] is True
    assert verification["revision_before"] == current_revision
    assert verification["revision_after"] == committed_revision

    batch = DesignFactAdapter().normalize_snapshot(
        {
            "document_id": "DOC-REVIT",
            "host_instance_id": "HOST-REVIT-A",
            "source_revision": committed_revision,
            "native_id": payload["wall_unique_id"],
            "native_kind": "Wall",
            "builtin_category": "OST_Walls",
            "wall_thickness_mm": payload["width_after_mm"],
        }
    )
    mapped_terms = _resolve_enterprise_terms(batch)
    assert "ifc:IfcWall" in mapped_terms
    wall_thickness_value, wall_thickness_unit = mapped_terms["dsp:WallThickness"]
    assert wall_thickness_value == pytest.approx(300.0, abs=1e-6)
    assert wall_thickness_unit == "mm"

    fixture_module = _load_reconciliation_fixture_module()
    transaction, _, authority = fixture_module._fixture()
    host_commit = RevitExecutionResultAdapter.adapt(
        admitted_authority=authority,
        document_ref="DOC-REVIT",
        approved_semantic_wall_id="WALL-001",
        host_result=success,
        occurred_at="2026-09-01T21:01:00Z",
    )
    delta = host_commit.actual_delta
    assert delta.revision_before == current_revision
    assert delta.revision_after == committed_revision
    assert len(delta.changes) == 1
    change = delta.changes[0]
    assert change.semantic_id == "WALL-001"
    assert change.canonical_kind == "ifc:IfcWall"
    assert tuple(aspect.value for aspect in change.changed_aspects) == ("PROPERTIES",)

    service = fixture_module._service()
    saga, scope_result = fixture_module._drive_to_scope(
        service,
        transaction,
        authority,
        delta,
    )
    assert (
        scope_result.status
        is fixture_module.reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    )
    semantic_verification = service.verify_semantics(
        saga.definition.saga_id,
        transaction.execution_slice.execution_slice_hash,
        fixture_module._verification_request(
            transaction,
            authority,
            delta,
            saga,
            width_mm=payload["width_after_mm"],
        ),
    )
    final = service.record_verification_result(
        saga.definition.saga_id,
        semantic_verification,
        expected_revision=saga.saga_revision,
        reconciled_at="2026-09-01T21:03:00Z",
    )
    assert (
        semantic_verification.status
        is fixture_module.reconciliation.VerificationStatus.PASSED
    )
    assert final.status is fixture_module.reconciliation.ExecutionSagaStatus.SUCCEEDED

    replay = transport.request(positive_command)
    assert replay["status"] == "OK"
    assert replay["replayed"] is True
    assert replay["revision_after"] == committed_revision
    assert replay["payload"] == success["payload"]
    assert replay["verification"] == success["verification"]
    assert (
        _probe_revision(
            transport,
            wall_unique_id=isolated,
            run_id=run_id,
            probe_name="after-replay",
        )
        == committed_revision
    )

    conflict = transport.request(
        _command(
            wall_unique_id=isolated,
            expected_revision=current_revision,
            thickness_mm=301.0,
            idempotency_key=positive_key,
            command_id=f"CMD-PH-LIVE-{run_id}-conflict",
        )
    )
    _assert_before_commit(
        conflict,
        code="IDEMPOTENCY_KEY_CONFLICT",
        revision=committed_revision,
    )
    observed_failures["idempotency_conflict"] = "IDEMPOTENCY_KEY_CONFLICT"
    assert (
        _probe_revision(
            transport,
            wall_unique_id=isolated,
            run_id=run_id,
            probe_name="after-conflict",
        )
        == committed_revision
    )

    print(
        json.dumps(
            {
                "fixture": str(fixture_path),
                "fixture_sha256": manifest["rvt_sha256"],
                "revit_version": os.environ["DSP_REVIT_VERSION"],
                "revit_tfm": os.environ["DSP_REVIT_TFM"],
                "revit_api_dir": os.environ["DSP_REVIT_API_DIR"],
                "pipe": os.environ["DSP_REVIT_PIPE"],
                "revision_before": current_revision,
                "revision_after": committed_revision,
                "width_after_mm": payload["width_after_mm"],
                "transaction_attempt_count": payload["transaction_attempt_count"],
                "before_commit_failures": observed_failures,
                "scope_status": scope_result.status.value,
                "verification_status": semantic_verification.status.value,
                "saga_status": final.status.value,
                "replay": replay["replayed"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
