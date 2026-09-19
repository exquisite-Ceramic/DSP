from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from typing import Any

import pytest
from autocad_sidecar.capability.profile import DesignCapabilityProfile
from design_orchestrator.canonical_operations import MOVE_V1, MVP_CANONICAL_OPERATIONS
from design_orchestrator.operation_resolver import (
    OperationResolver,
    ResolutionContext,
    ResolutionResult,
    SemanticEligibilityContext,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    BoundOperationProposal,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)


_LEGACY_RESOLUTION_HASH = "694069001bda7b1ee84937e488ba594a7804833a046e0df228abdb493daa4251"


def _profile() -> DesignCapabilityProfile:
    """构造会真实进入 ResolutionResult.provider_candidates 的 production profile shape。"""

    return DesignCapabilityProfile(
        provider_server="autocad.local",
        provider_tool="cad.move",
        canonical_operation="move.v1",
        category="MODEL_OPERATION",
        entity_constraints=("LINE", "ARC"),
        execution_freshness=(
            {"aspect": "PLACEMENT", "required_state": "FRESH"},
        ),
        effects=("PLACEMENT", "GEOMETRY"),
        existence_effects=(),
        risk="LOW",
        preview_supported=False,
        rollback_supported=False,
        idempotent=True,
        verification_contract={"type": "HOST_READ_BACK"},
        input_schema={
            "type": "object",
            "properties": {
                "handles": {"type": "array", "items": {"type": "string"}},
                "dx": {"type": "number"},
                "dy": {"type": "number"},
            },
            "required": ["handles", "dx", "dy"],
        },
        output_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
        },
        description="Production move profile",
    )


def _resolution(*, profile: DesignCapabilityProfile | None = None) -> ResolutionResult:
    """用真实 resolver 生成 codec characterization fixture。"""

    return OperationResolver((MOVE_V1,)).resolve(
        (profile or _profile(),),
        ResolutionContext(
            host_provider_servers=frozenset({"autocad.local"}),
            semantic_context=SemanticEligibilityContext(
                context_snapshot_id="CS-codec",
                context_snapshot_hash="snapshot-codec",
                document_ref="drawing-codec",
                semantic_environment_ref="semantic-env@codec",
                entities=(),
            ),
        ),
    )


def _bound_proposal() -> BoundOperationProposal:
    """用真实 ParameterBinder 生成嵌套 enum/read-model 完整的 bound proposal。"""

    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    return binder.bind(
        OperationProposal(
            "move.v1",
            {"displacement": [300, 0, 0]},
        ),
        ParameterBindingContext(
            context_snapshot_id="CS-codec",
            context_snapshot_hash="snapshot-codec",
            document_ref="drawing-codec",
            semantic_environment_ref="semantic-env@codec",
            selection=("S-001", "S-002"),
        ),
    )


def _codec_api() -> tuple[Any, ...]:
    """集中读取 codec public API，characterization 不依赖旧 service private helper。"""

    from design_orchestrator.workflow_artifacts import (
        PERSISTED_CAPABILITY_PROFILE_FIELDS,
        WORKFLOW_ARTIFACT_CODEC_VERSION,
        WorkflowArtifactCodecError,
        decode_workflow_artifact,
        encode_workflow_artifact,
        legacy_workflow_artifact_content_hash,
        workflow_artifact_content_hash,
    )

    return (
        PERSISTED_CAPABILITY_PROFILE_FIELDS,
        WORKFLOW_ARTIFACT_CODEC_VERSION,
        WorkflowArtifactCodecError,
        decode_workflow_artifact,
        encode_workflow_artifact,
        legacy_workflow_artifact_content_hash,
        workflow_artifact_content_hash,
    )


def test_legacy_hash_characterizes_prechange_resolution_fixture() -> None:
    """冻结迁移前 generic artifact hash，后续 ref migration 只能调用等价 legacy 算法。"""

    _, _, _, _, _, legacy_hash, _ = _codec_api()
    resolution = _resolution()

    assert legacy_hash(resolution) == _LEGACY_RESOLUTION_HASH

    changed_profile = replace(_profile(), description="Changed description")
    changed_resolution = _resolution(profile=changed_profile)
    assert legacy_hash(changed_resolution) != _LEGACY_RESOLUTION_HASH


def test_operation_resolution_codec_round_trips_all_observed_profile_fields() -> None:
    """ResolutionResult 解码后保留 canonical operation 与 production profile 的显式字段。"""

    (
        persisted_fields,
        codec_version,
        _,
        decode,
        encode,
        legacy_hash,
        content_hash,
    ) = _codec_api()
    resolution = _resolution()

    payload = encode(kind="operation_resolution", value=resolution)
    decoded = decode(
        kind="operation_resolution",
        codec_version=codec_version,
        payload=payload,
    )

    assert codec_version == 1
    assert isinstance(decoded, ResolutionResult)
    assert decoded.resolved_operations == resolution.resolved_operations
    assert tuple(decoded.provider_candidates) == tuple(resolution.provider_candidates)
    assert {
        "description",
        "existence_effects",
        "idempotent",
    } <= set(persisted_fields)
    for candidate_id, original in resolution.provider_candidates.items():
        restored = decoded.provider_candidates[candidate_id]
        for field_name in persisted_fields:
            assert getattr(restored, field_name) == getattr(original, field_name)

    assert legacy_hash(resolution) == _LEGACY_RESOLUTION_HASH
    expected_new_hash = sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert content_hash(resolution) == expected_new_hash


def test_bound_operation_proposal_codec_round_trips_by_dataclass_equality() -> None:
    """BoundOperationProposal 必须重建原始 nested dataclass/enum，而不是普通 dict。"""

    _, codec_version, _, decode, encode, _, content_hash = _codec_api()
    bound = _bound_proposal()

    payload = encode(kind="bound_operation_proposal", value=bound)
    decoded = decode(
        kind="bound_operation_proposal",
        codec_version=codec_version,
        payload=payload,
    )

    assert isinstance(decoded, BoundOperationProposal)
    assert decoded == bound
    assert content_hash(bound) == sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def test_codec_rejects_unsupported_kind_type_and_unknown_version() -> None:
    """Codec 的 kind/type/version 是闭集，未知输入必须 fail closed。"""

    _, codec_version, codec_error, decode, encode, _, content_hash = _codec_api()
    resolution = _resolution()

    with pytest.raises(codec_error):
        encode(kind="unknown", value=resolution)
    with pytest.raises(codec_error):
        encode(kind="operation_resolution", value=_bound_proposal())
    with pytest.raises(codec_error):
        content_hash(object())

    payload = encode(kind="operation_resolution", value=resolution)
    with pytest.raises(codec_error):
        decode(
            kind="operation_resolution",
            codec_version=codec_version + 1,
            payload=payload,
        )


def test_resolution_codec_rejects_missing_extra_and_invalid_nested_enum() -> None:
    """Versioned payload 必须 exact-key 且 nested CanonicalExistenceEffect 不接受未知值。"""

    _, codec_version, codec_error, decode, encode, _, _ = _codec_api()
    payload = encode(kind="operation_resolution", value=_resolution())

    missing = dict(payload)
    missing.pop("provider_candidates")
    with pytest.raises(codec_error):
        decode(
            kind="operation_resolution",
            codec_version=codec_version,
            payload=missing,
        )

    extra = dict(payload)
    extra["unexpected"] = True
    with pytest.raises(codec_error):
        decode(
            kind="operation_resolution",
            codec_version=codec_version,
            payload=extra,
        )

    invalid_enum = json.loads(json.dumps(payload))
    invalid_enum["resolved_operations"][0]["existence_effects"] = ["UNKNOWN"]
    with pytest.raises(codec_error):
        decode(
            kind="operation_resolution",
            codec_version=codec_version,
            payload=invalid_enum,
        )


def test_bound_codec_rejects_missing_extra_and_invalid_binding_enum() -> None:
    """Bound proposal nested payload 同样使用 exact-key validation 和 enum reconstruction。"""

    _, codec_version, codec_error, decode, encode, _, _ = _codec_api()
    payload = encode(kind="bound_operation_proposal", value=_bound_proposal())

    missing = dict(payload)
    missing.pop("planning_requirements")
    with pytest.raises(codec_error):
        decode(
            kind="bound_operation_proposal",
            codec_version=codec_version,
            payload=missing,
        )

    extra = dict(payload)
    extra["unexpected"] = True
    with pytest.raises(codec_error):
        decode(
            kind="bound_operation_proposal",
            codec_version=codec_version,
            payload=extra,
        )

    invalid_enum = json.loads(json.dumps(payload))
    evidence = next(iter(invalid_enum["binding_evidence"].values()))
    evidence["binding_class"] = "UNKNOWN"
    with pytest.raises(codec_error):
        decode(
            kind="bound_operation_proposal",
            codec_version=codec_version,
            payload=invalid_enum,
        )
