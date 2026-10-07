"""V2 reconciliation evidence body 的 content-addressed owner contract 与 codec。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any, Protocol

from design_approval_scope import CanonicalAspect
from host_contracts import HostEntityRef
from semantic_runtime import (
    AspectGuarantee,
    AssuranceLevel,
    Coverage,
    CoverageState,
    GeometryLevel,
    SemanticAspect,
    SemanticDepth,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotKind,
)

from .contracts import (
    ActualChange,
    ActualChangeKind,
    ActualDelta,
    ReconciliationError,
    SemanticVerificationResult,
    ValidationTaskResult,
    VerificationContractEvidence,
    VerificationEvidenceBundle,
    VerificationStatus,
    VerificationSubjectEvidence,
)
from .hashing import (
    compute_semantic_verification_hash,
    compute_validation_task_result_hash,
    validate_actual_delta_integrity,
    validate_verification_evidence_bundle_integrity,
)

_CODEC_VERSION = 1
_ACTUAL_DELTA = "actual_delta"
_VERIFICATION_BUNDLE = "verification_bundle"
_VERIFICATION_RESULT = "verification_result"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """只接受 JSON object 形态。"""

    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _array(value: object, field_name: str) -> Sequence[object]:
    """只接受 JSON array 形态；字符串不能被误当成序列。"""

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _required(value: Mapping[str, object], key: str) -> object:
    """读取持久化 body 的必需字段。"""

    if key not in value:
        raise ValueError(f"missing reconciliation evidence field: {key}")
    return value[key]


def _plain_json(value: Any) -> Any:
    """把只读 Mapping/tuple/Enum 转成显式 JSON-compatible 值。"""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("reconciliation evidence mapping keys must be strings")
            result[key] = _plain_json(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(
        "reconciliation evidence contains a non-JSON-compatible value: "
        f"{type(value).__name__}"
    )


def _environment_payload(value: SemanticEnvironmentRef) -> dict[str, object]:
    """编码 pinned semantic environment。"""

    return {
        "environment_id": value.environment_id,
        "content_hash": value.content_hash,
    }


def _decode_environment(value: object) -> SemanticEnvironmentRef:
    """恢复 pinned semantic environment。"""

    payload = _mapping(value, "semantic_environment_ref")
    return SemanticEnvironmentRef(
        environment_id=_required(payload, "environment_id"),
        content_hash=_required(payload, "content_hash"),
    )


def _projection_payload(value: SemanticProjectionRef) -> dict[str, object]:
    """编码 semantic projection ref。"""

    return {
        "projection_id": value.projection_id,
        "projection_hash": value.projection_hash,
        "semantic_model_version": value.semantic_model_version,
        "provider_set_hash": value.provider_set_hash,
        "mapping_profile_set_hash": value.mapping_profile_set_hash,
        "normalized_fact_batch_hash": value.normalized_fact_batch_hash,
    }


def _decode_projection(value: object) -> SemanticProjectionRef:
    """恢复 semantic projection ref。"""

    payload = _mapping(value, "projection_ref")
    return SemanticProjectionRef(
        projection_id=_required(payload, "projection_id"),
        projection_hash=_required(payload, "projection_hash"),
        semantic_model_version=_required(payload, "semantic_model_version"),
        provider_set_hash=_required(payload, "provider_set_hash"),
        mapping_profile_set_hash=_required(payload, "mapping_profile_set_hash"),
        normalized_fact_batch_hash=payload.get("normalized_fact_batch_hash"),
    )


def _coverage_payload(value: Coverage) -> dict[str, object]:
    """编码 snapshot coverage。"""

    return {
        "document_ref": value.document_ref,
        "root_entities": list(value.root_entities),
        "neighborhood_depth": value.neighborhood_depth,
        "neighborhood_relations": list(value.neighborhood_relations),
    }


def _decode_coverage(value: object) -> Coverage:
    """恢复 snapshot coverage。"""

    payload = _mapping(value, "coverage")
    return Coverage(
        document_ref=_required(payload, "document_ref"),
        root_entities=tuple(
            _array(_required(payload, "root_entities"), "root_entities")
        ),
        neighborhood_depth=_required(payload, "neighborhood_depth"),
        neighborhood_relations=tuple(
            _array(
                _required(payload, "neighborhood_relations"),
                "neighborhood_relations",
            )
        ),
    )


def _guarantee_payload(value: AspectGuarantee) -> dict[str, object]:
    """编码 snapshot aspect guarantee。"""

    return {
        "aspect": value.aspect.value,
        "geometry_level": value.geometry_level.name,
        "coverage_ref": value.coverage_ref,
        "coverage_state": (
            value.coverage_state.name if value.coverage_state is not None else None
        ),
        "semantic_depth": (
            value.semantic_depth.name if value.semantic_depth is not None else None
        ),
        "assurance_level": value.assurance_level.name,
    }


def _decode_guarantee(value: object) -> AspectGuarantee:
    """恢复 snapshot aspect guarantee。"""

    payload = _mapping(value, "aspect_guarantee")
    coverage_state = payload.get("coverage_state")
    semantic_depth = payload.get("semantic_depth")
    return AspectGuarantee(
        aspect=SemanticAspect(_required(payload, "aspect")),
        geometry_level=GeometryLevel[_required(payload, "geometry_level")],
        coverage_ref=payload.get("coverage_ref"),
        coverage_state=(
            None if coverage_state is None else CoverageState[coverage_state]
        ),
        semantic_depth=(
            None if semantic_depth is None else SemanticDepth[semantic_depth]
        ),
        assurance_level=AssuranceLevel[_required(payload, "assurance_level")],
    )


def _snapshot_payload(value: SemanticSnapshot) -> dict[str, object]:
    """编码完整 post/baseline semantic snapshot body。"""

    return {
        "snapshot_id": value.snapshot_id,
        "kind": value.kind.value,
        "project_id": value.project_id,
        "freshness_contract_id": value.freshness_contract_id,
        "freshness_contract_hash": value.freshness_contract_hash,
        "document_ref": value.document_ref,
        "base_host_revision": value.base_host_revision,
        "coverage": _coverage_payload(value.coverage),
        "projection_ref": _projection_payload(value.projection_ref),
        "semantic_environment_ref": _environment_payload(
            value.semantic_environment_ref
        ),
        "aspect_guarantees": [
            _guarantee_payload(item) for item in value.aspect_guarantees
        ],
        "hash": value.hash,
    }


def _decode_snapshot(value: object) -> SemanticSnapshot:
    """恢复 semantic snapshot；bundle integrity hash 会再次验证其承诺。"""

    payload = _mapping(value, "semantic_snapshot")
    return SemanticSnapshot(
        snapshot_id=_required(payload, "snapshot_id"),
        kind=SnapshotKind(_required(payload, "kind")),
        project_id=_required(payload, "project_id"),
        freshness_contract_id=_required(payload, "freshness_contract_id"),
        freshness_contract_hash=_required(payload, "freshness_contract_hash"),
        document_ref=_required(payload, "document_ref"),
        base_host_revision=_required(payload, "base_host_revision"),
        coverage=_decode_coverage(_required(payload, "coverage")),
        projection_ref=_decode_projection(_required(payload, "projection_ref")),
        semantic_environment_ref=_decode_environment(
            _required(payload, "semantic_environment_ref")
        ),
        aspect_guarantees=tuple(
            _decode_guarantee(item)
            for item in _array(
                _required(payload, "aspect_guarantees"),
                "aspect_guarantees",
            )
        ),
        hash=_required(payload, "hash"),
    )


def _change_payload(value: ActualChange) -> dict[str, object]:
    """编码 provider-neutral ActualChange。"""

    host_ref = value.host_entity_ref
    return {
        "change_kind": value.change_kind.value,
        "actual_change_hash": value.actual_change_hash,
        "semantic_id": value.semantic_id,
        "canonical_kind": value.canonical_kind,
        "changed_aspects": [item.value for item in value.changed_aspects],
        "canonical_operation": value.canonical_operation,
        "source_execution_unit_hash": value.source_execution_unit_hash,
        "source_semantic_id": value.source_semantic_id,
        "source_canonical_kind": value.source_canonical_kind,
        "derivation_rule": value.derivation_rule,
        "host_entity_ref": None if host_ref is None else host_ref.to_dict(),
    }


def _decode_change(value: object) -> ActualChange:
    """恢复 ActualChange，并重新运行领域构造器校验。"""

    payload = _mapping(value, "actual_change")
    host_payload = payload.get("host_entity_ref")
    host_ref = (
        None
        if host_payload is None
        else HostEntityRef.from_dict(dict(_mapping(host_payload, "host_entity_ref")))
    )
    return ActualChange(
        change_kind=ActualChangeKind(_required(payload, "change_kind")),
        actual_change_hash=_required(payload, "actual_change_hash"),
        semantic_id=payload.get("semantic_id"),
        canonical_kind=payload.get("canonical_kind"),
        changed_aspects=tuple(
            CanonicalAspect(item)
            for item in _array(
                _required(payload, "changed_aspects"),
                "changed_aspects",
            )
        ),
        canonical_operation=payload.get("canonical_operation"),
        source_execution_unit_hash=payload.get("source_execution_unit_hash"),
        source_semantic_id=payload.get("source_semantic_id"),
        source_canonical_kind=payload.get("source_canonical_kind"),
        derivation_rule=payload.get("derivation_rule"),
        host_entity_ref=host_ref,
    )


def _actual_delta_payload(value: ActualDelta) -> dict[str, object]:
    """编码完整 ActualDelta body。"""

    return {
        "actual_delta_id": value.actual_delta_id,
        "grant_hash": value.grant_hash,
        "binding_set_hash": value.binding_set_hash,
        "execution_slice_hash": value.execution_slice_hash,
        "changeset_hash": value.changeset_hash,
        "approved_scope_hash": value.approved_scope_hash,
        "host_instance_id": value.host_instance_id,
        "document_ref": value.document_ref,
        "revision_before": value.revision_before,
        "revision_after": value.revision_after,
        "changes": [_change_payload(item) for item in value.changes],
        "actual_delta_hash": value.actual_delta_hash,
    }


def _decode_actual_delta(value: object) -> ActualDelta:
    """恢复 ActualDelta，并验证 content hash。"""

    payload = _mapping(value, "actual_delta")
    delta = ActualDelta(
        actual_delta_id=_required(payload, "actual_delta_id"),
        grant_hash=_required(payload, "grant_hash"),
        binding_set_hash=_required(payload, "binding_set_hash"),
        execution_slice_hash=_required(payload, "execution_slice_hash"),
        changeset_hash=_required(payload, "changeset_hash"),
        approved_scope_hash=_required(payload, "approved_scope_hash"),
        host_instance_id=_required(payload, "host_instance_id"),
        document_ref=_required(payload, "document_ref"),
        revision_before=_required(payload, "revision_before"),
        revision_after=_required(payload, "revision_after"),
        changes=tuple(
            _decode_change(item)
            for item in _array(_required(payload, "changes"), "changes")
        ),
        actual_delta_hash=_required(payload, "actual_delta_hash"),
    )
    validate_actual_delta_integrity(delta)
    return delta


def _contract_payload(value: VerificationContractEvidence) -> dict[str, object]:
    """编码验证契约 evidence。"""

    return {
        "contract_ref": value.contract_ref,
        "contract_body": _plain_json(value.contract_body),
    }


def _decode_contract(value: object) -> VerificationContractEvidence:
    """恢复验证契约 evidence。"""

    payload = _mapping(value, "contract_evidence")
    body = _mapping(_required(payload, "contract_body"), "contract_body")
    return VerificationContractEvidence(
        contract_ref=_required(payload, "contract_ref"),
        contract_body=dict(body),
    )


def _subject_payload(value: VerificationSubjectEvidence) -> dict[str, object]:
    """编码一个 snapshot-bound semantic subject evidence。"""

    return {
        "semantic_id": value.semantic_id,
        "canonical_kind": value.canonical_kind,
        "properties": _plain_json(value.properties),
        "placement": _plain_json(value.placement),
        "geometry_evidence": _plain_json(value.geometry_evidence),
        "relationships": _plain_json(value.relationships),
        "constraints": _plain_json(value.constraints),
        "classification": list(value.classification),
        "evidence_aspects": [item.value for item in value.evidence_aspects],
        "snapshot_id": value.snapshot_id,
        "snapshot_hash": value.snapshot_hash,
        "projection_ref": _projection_payload(value.projection_ref),
    }


def _decode_subject(value: object) -> VerificationSubjectEvidence:
    """恢复 snapshot-bound semantic subject evidence。"""

    payload = _mapping(value, "subject_evidence")
    placement = payload.get("placement")
    geometry = payload.get("geometry_evidence")
    return VerificationSubjectEvidence(
        semantic_id=_required(payload, "semantic_id"),
        canonical_kind=_required(payload, "canonical_kind"),
        properties=dict(
            _mapping(_required(payload, "properties"), "subject.properties")
        ),
        placement=(
            None if placement is None else dict(_mapping(placement, "placement"))
        ),
        geometry_evidence=(
            None
            if geometry is None
            else dict(_mapping(geometry, "geometry_evidence"))
        ),
        relationships=tuple(
            dict(_mapping(item, "relationship"))
            for item in _array(
                _required(payload, "relationships"),
                "relationships",
            )
        ),
        constraints=tuple(
            dict(_mapping(item, "constraint"))
            for item in _array(_required(payload, "constraints"), "constraints")
        ),
        classification=tuple(
            _array(_required(payload, "classification"), "classification")
        ),
        evidence_aspects=tuple(
            CanonicalAspect(item)
            for item in _array(
                _required(payload, "evidence_aspects"),
                "evidence_aspects",
            )
        ),
        snapshot_id=_required(payload, "snapshot_id"),
        snapshot_hash=_required(payload, "snapshot_hash"),
        projection_ref=_decode_projection(_required(payload, "projection_ref")),
    )


def _bundle_payload(value: VerificationEvidenceBundle) -> dict[str, object]:
    """编码完整 VerificationEvidenceBundle。"""

    return {
        "evidence_bundle_id": value.evidence_bundle_id,
        "changeset_hash": value.changeset_hash,
        "execution_slice_hash": value.execution_slice_hash,
        "actual_delta_hash": value.actual_delta_hash,
        "semantic_environment_ref": _environment_payload(
            value.semantic_environment_ref
        ),
        "post_execution_snapshot_ref": _snapshot_payload(
            value.post_execution_snapshot_ref
        ),
        "post_execution_projection_ref": _projection_payload(
            value.post_execution_projection_ref
        ),
        "base_host_revision": value.base_host_revision,
        "baseline_snapshot_ref": (
            None
            if value.baseline_snapshot_ref is None
            else _snapshot_payload(value.baseline_snapshot_ref)
        ),
        "baseline_projection_ref": (
            None
            if value.baseline_projection_ref is None
            else _projection_payload(value.baseline_projection_ref)
        ),
        "contract_evidence": [
            _contract_payload(item) for item in value.contract_evidence
        ],
        "subject_evidence": [
            _subject_payload(item) for item in value.subject_evidence
        ],
        "baseline_subject_evidence": [
            _subject_payload(item) for item in value.baseline_subject_evidence
        ],
        "evidence_bundle_hash": value.evidence_bundle_hash,
    }


def _decode_bundle(value: object) -> VerificationEvidenceBundle:
    """恢复 VerificationEvidenceBundle，并验证其 committed hash。"""

    payload = _mapping(value, "verification_bundle")
    baseline_snapshot = payload.get("baseline_snapshot_ref")
    baseline_projection = payload.get("baseline_projection_ref")
    bundle = VerificationEvidenceBundle(
        evidence_bundle_id=_required(payload, "evidence_bundle_id"),
        changeset_hash=_required(payload, "changeset_hash"),
        execution_slice_hash=_required(payload, "execution_slice_hash"),
        actual_delta_hash=_required(payload, "actual_delta_hash"),
        semantic_environment_ref=_decode_environment(
            _required(payload, "semantic_environment_ref")
        ),
        post_execution_snapshot_ref=_decode_snapshot(
            _required(payload, "post_execution_snapshot_ref")
        ),
        post_execution_projection_ref=_decode_projection(
            _required(payload, "post_execution_projection_ref")
        ),
        base_host_revision=_required(payload, "base_host_revision"),
        baseline_snapshot_ref=(
            None
            if baseline_snapshot is None
            else _decode_snapshot(baseline_snapshot)
        ),
        baseline_projection_ref=(
            None
            if baseline_projection is None
            else _decode_projection(baseline_projection)
        ),
        contract_evidence=tuple(
            _decode_contract(item)
            for item in _array(
                _required(payload, "contract_evidence"),
                "contract_evidence",
            )
        ),
        subject_evidence=tuple(
            _decode_subject(item)
            for item in _array(
                _required(payload, "subject_evidence"),
                "subject_evidence",
            )
        ),
        baseline_subject_evidence=tuple(
            _decode_subject(item)
            for item in _array(
                _required(payload, "baseline_subject_evidence"),
                "baseline_subject_evidence",
            )
        ),
        evidence_bundle_hash=_required(payload, "evidence_bundle_hash"),
    )
    validate_verification_evidence_bundle_integrity(bundle)
    return bundle


def _task_result_payload(value: ValidationTaskResult) -> dict[str, object]:
    """编码一个 validation task result。"""

    return {
        "validation_task_id": value.validation_task_id,
        "status": value.status.value,
        "observations": list(value.observations),
        "failure_codes": list(value.failure_codes),
        "task_result_hash": value.task_result_hash,
    }


def _decode_task_result(value: object) -> ValidationTaskResult:
    """恢复并验证一个 validation task result。"""

    payload = _mapping(value, "validation_task_result")
    result = ValidationTaskResult(
        validation_task_id=_required(payload, "validation_task_id"),
        status=VerificationStatus(_required(payload, "status")),
        observations=tuple(
            _array(_required(payload, "observations"), "observations")
        ),
        failure_codes=tuple(
            _array(_required(payload, "failure_codes"), "failure_codes")
        ),
        task_result_hash=_required(payload, "task_result_hash"),
    )
    if compute_validation_task_result_hash(result) != result.task_result_hash:
        raise ReconciliationError(
            "RECONCILIATION_EVIDENCE_CORRUPT",
            "ValidationTaskResult body does not match its committed hash",
        )
    return result


def _verification_result_payload(
    value: SemanticVerificationResult,
) -> dict[str, object]:
    """编码完整 semantic verification result。"""

    return {
        "verification_id": value.verification_id,
        "changeset_hash": value.changeset_hash,
        "execution_slice_hash": value.execution_slice_hash,
        "actual_delta_hash": value.actual_delta_hash,
        "evidence_bundle_hash": value.evidence_bundle_hash,
        "task_results": [
            _task_result_payload(item) for item in value.task_results
        ],
        "status": value.status.value,
        "verification_hash": value.verification_hash,
    }


def _decode_verification_result(value: object) -> SemanticVerificationResult:
    """恢复 SemanticVerificationResult，并验证全部 task/result hashes。"""

    payload = _mapping(value, "verification_result")
    result = SemanticVerificationResult(
        verification_id=_required(payload, "verification_id"),
        changeset_hash=_required(payload, "changeset_hash"),
        execution_slice_hash=_required(payload, "execution_slice_hash"),
        actual_delta_hash=_required(payload, "actual_delta_hash"),
        evidence_bundle_hash=_required(payload, "evidence_bundle_hash"),
        task_results=tuple(
            _decode_task_result(item)
            for item in _array(
                _required(payload, "task_results"),
                "task_results",
            )
        ),
        status=VerificationStatus(_required(payload, "status")),
        verification_hash=_required(payload, "verification_hash"),
    )
    if compute_semantic_verification_hash(result) != result.verification_hash:
        raise ReconciliationError(
            "RECONCILIATION_EVIDENCE_CORRUPT",
            "SemanticVerificationResult body does not match its committed hash",
        )
    return result


def evidence_kind_and_hash(value: object) -> tuple[str, str]:
    """返回三类 evidence body 的稳定 kind/content hash，并先验证 body。"""

    if isinstance(value, ActualDelta):
        validate_actual_delta_integrity(value)
        return _ACTUAL_DELTA, value.actual_delta_hash
    if isinstance(value, VerificationEvidenceBundle):
        validate_verification_evidence_bundle_integrity(value)
        return _VERIFICATION_BUNDLE, value.evidence_bundle_hash
    if isinstance(value, SemanticVerificationResult):
        for item in value.task_results:
            if compute_validation_task_result_hash(item) != item.task_result_hash:
                raise ReconciliationError(
                    "RECONCILIATION_EVIDENCE_CORRUPT",
                    "ValidationTaskResult body does not match committed hash",
                )
        if compute_semantic_verification_hash(value) != value.verification_hash:
            raise ReconciliationError(
                "RECONCILIATION_EVIDENCE_CORRUPT",
                "SemanticVerificationResult body does not match committed hash",
            )
        return _VERIFICATION_RESULT, value.verification_hash
    raise TypeError("unsupported reconciliation evidence body")


def encode_reconciliation_evidence(value: object) -> dict[str, object]:
    """把一个已验证 evidence body 编码为 schema_version=1 JSON 载荷。"""

    kind, _ = evidence_kind_and_hash(value)
    if kind == _ACTUAL_DELTA:
        body = _actual_delta_payload(value)
    elif kind == _VERIFICATION_BUNDLE:
        body = _bundle_payload(value)
    else:
        body = _verification_result_payload(value)
    return {
        "schema_version": _CODEC_VERSION,
        "kind": kind,
        "body": body,
    }


def decode_reconciliation_evidence(payload: Mapping[str, object]) -> object:
    """恢复一个 evidence body，并重新执行其领域/hash 完整性校验。"""

    normalized = _mapping(payload, "reconciliation_evidence")
    version = _required(normalized, "schema_version")
    if version != _CODEC_VERSION or isinstance(version, bool):
        raise ReconciliationError(
            "RECONCILIATION_EVIDENCE_CODEC_UNSUPPORTED",
            f"unsupported reconciliation evidence codec version: {version!r}",
        )
    kind = _required(normalized, "kind")
    body = _required(normalized, "body")
    if kind == _ACTUAL_DELTA:
        return _decode_actual_delta(body)
    if kind == _VERIFICATION_BUNDLE:
        return _decode_bundle(body)
    if kind == _VERIFICATION_RESULT:
        return _decode_verification_result(body)
    raise ReconciliationError(
        "RECONCILIATION_EVIDENCE_CODEC_UNSUPPORTED",
        f"unsupported reconciliation evidence kind: {kind!r}",
    )


class ReconciliationEvidenceStore(Protocol):
    """Execution reconciliation owner 的 content-addressed evidence body port。"""

    def put_actual_delta(self, value: ActualDelta) -> str: ...

    def get_actual_delta(self, content_hash: str) -> ActualDelta | None: ...

    def put_verification_bundle(self, value: VerificationEvidenceBundle) -> str: ...

    def get_verification_bundle(
        self,
        content_hash: str,
    ) -> VerificationEvidenceBundle | None: ...

    def put_verification_result(self, value: SemanticVerificationResult) -> str: ...

    def get_verification_result(
        self,
        content_hash: str,
    ) -> SemanticVerificationResult | None: ...


class InMemoryReconciliationEvidenceStore:
    """测试/兼容路径使用的 immutable reference backend。"""

    def __init__(self) -> None:
        self._payloads: dict[str, dict[str, object]] = {}

    def _put(self, value: object) -> str:
        kind, content_hash = evidence_kind_and_hash(value)
        payload = encode_reconciliation_evidence(value)
        existing = self._payloads.get(content_hash)
        if existing is not None and existing != payload:
            raise ReconciliationError(
                "RECONCILIATION_EVIDENCE_CORRUPT",
                f"evidence hash {content_hash} already owns a different body",
            )
        if existing is None:
            self._payloads[content_hash] = payload
        if payload["kind"] != kind:
            raise ReconciliationError(
                "RECONCILIATION_EVIDENCE_CORRUPT",
                "evidence codec returned an unexpected kind",
            )
        return content_hash

    def _get(self, content_hash: str, expected_kind: str):
        payload = self._payloads.get(content_hash)
        if payload is None:
            return None
        if payload.get("kind") != expected_kind:
            raise ReconciliationError(
                "RECONCILIATION_EVIDENCE_CORRUPT",
                "evidence hash resolves to an unexpected body kind",
            )
        value = decode_reconciliation_evidence(payload)
        _, decoded_hash = evidence_kind_and_hash(value)
        if decoded_hash != content_hash:
            raise ReconciliationError(
                "RECONCILIATION_EVIDENCE_CORRUPT",
                "decoded evidence body does not match lookup hash",
            )
        return value

    def put_actual_delta(self, value: ActualDelta) -> str:
        return self._put(value)

    def get_actual_delta(self, content_hash: str) -> ActualDelta | None:
        value = self._get(content_hash, _ACTUAL_DELTA)
        return value if isinstance(value, ActualDelta) else None

    def put_verification_bundle(self, value: VerificationEvidenceBundle) -> str:
        return self._put(value)

    def get_verification_bundle(
        self,
        content_hash: str,
    ) -> VerificationEvidenceBundle | None:
        value = self._get(content_hash, _VERIFICATION_BUNDLE)
        return value if isinstance(value, VerificationEvidenceBundle) else None

    def put_verification_result(self, value: SemanticVerificationResult) -> str:
        return self._put(value)

    def get_verification_result(
        self,
        content_hash: str,
    ) -> SemanticVerificationResult | None:
        value = self._get(content_hash, _VERIFICATION_RESULT)
        return value if isinstance(value, SemanticVerificationResult) else None


__all__ = [
    "InMemoryReconciliationEvidenceStore",
    "ReconciliationEvidenceStore",
    "decode_reconciliation_evidence",
    "encode_reconciliation_evidence",
    "evidence_kind_and_hash",
]
