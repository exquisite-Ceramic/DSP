"""Revit 墙厚产品 vertical 的独立 post-commit Step33 evidence composition。

该模块只负责把已经 admitted 的 exact provider/native lineage 与一次独立 Revit READ
组合成 provider-neutral ``VerificationEvidenceBundle``。语义映射继续由真实
``DesignFactAdapter`` / ``SemanticService`` 持有，最终 PASS/FAIL 继续只由 Step33
``SemanticVerifier`` 决定；本模块不从 mutation response 推断最终墙厚。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256

from design_approval_scope import ApprovalScopeBoundaryV2, CanonicalAspect
from design_changeset import CanonicalChangeSet, canonical_hash
from design_convergence import build_materialization_canonical_evidence
from design_execution_coordination import VerificationEvidenceUnavailable
from design_execution_planning import ExecutionSliceV2
from design_execution_reconciliation import (
    ActualDelta,
    SemanticVerificationResult,
    VerificationContractEvidence,
    VerificationEvidenceBundle,
    VerificationSubjectEvidence,
    compute_verification_evidence_bundle_hash,
    validate_actual_delta_integrity,
)
from design_gateway_authorization import AdmittedExecutionAuthorityV2
from design_orchestrator.canonical_operations import SET_WALL_THICKNESS_V1
from design_provider_binding import (
    ProviderBindingSetV2,
    validate_provider_binding_set_v2,
)
from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    AssuranceLevel,
    CoverageState,
    ReconstructionResult,
    SemanticAspect,
    SemanticDepth,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    build_operation_contract,
)

from .revit_semantics import (
    _canonical_hash,
    _claim_payload,
    _claim_uses_fact,
    _fact_ids_for_kind,
    _required_text,
    _strongest_claim_assurance,
)


class RevitWallThicknessVerificationEvidencePort:
    """从 exact admitted Revit lineage 构造独立 READ 驱动的 Step33 evidence。

    该端口故意不接收 Host mutation port，因此在结构上无法为了取得更“干净”的 evidence
    再发一次 ``set_wall_thickness``。READ 不可获得时只抛出
    ``VerificationEvidenceUnavailable``；已经获得但 identity/revision 不一致的 evidence
    则直接 fail closed。
    """

    def __init__(
        self,
        *,
        snapshot_reader,
        design_fact_adapter,
        semantic_service,
        semantic_environment,
    ) -> None:
        """显式注入只读 Host adapter 与现有 semantic owners。"""
        if snapshot_reader is None or not callable(getattr(snapshot_reader, "read", None)):
            raise TypeError("snapshot_reader must provide read")
        if design_fact_adapter is None or not callable(
            getattr(design_fact_adapter, "normalize_snapshot", None)
        ):
            raise TypeError("design_fact_adapter must provide normalize_snapshot")
        if semantic_service is None or not callable(
            getattr(semantic_service, "project_facts", None)
        ):
            raise TypeError("semantic_service must provide project_facts")
        _required_text(
            getattr(semantic_environment, "environment_id", None),
            "semantic_environment.environment_id",
        )
        _required_text(
            getattr(semantic_environment, "content_hash", None),
            "semantic_environment.content_hash",
        )
        self._snapshot_reader = snapshot_reader
        self._design_fact_adapter = design_fact_adapter
        self._semantic_service = semantic_service
        self._semantic_environment = semantic_environment

    @staticmethod
    def _validate_lineage(
        *,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
        actual_delta: ActualDelta,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundaryV2,
    ):
        """要求 Step30/31/32、ActualDelta 与 Step28/29 owner truth 精确闭合。"""
        if not isinstance(execution_slice, ExecutionSliceV2):
            raise TypeError("execution_slice must be ExecutionSliceV2")
        if not isinstance(authority, AdmittedExecutionAuthorityV2):
            raise TypeError("authority must be AdmittedExecutionAuthorityV2")
        if not isinstance(binding_set, ProviderBindingSetV2):
            raise TypeError("binding_set must be ProviderBindingSetV2")
        if not isinstance(actual_delta, ActualDelta):
            raise TypeError("actual_delta must be ActualDelta")
        if not isinstance(canonical_changeset, CanonicalChangeSet):
            raise TypeError("canonical_changeset must be CanonicalChangeSet")
        if not isinstance(approval_scope_boundary, ApprovalScopeBoundaryV2):
            raise TypeError("approval_scope_boundary must be ApprovalScopeBoundaryV2")

        validate_provider_binding_set_v2(binding_set, execution_slice)
        validate_actual_delta_integrity(actual_delta)

        runtime = execution_slice.host_runtime_ref
        if runtime.host_type != "revit":
            raise ValueError("Revit verification evidence requires a Revit execution slice")
        if (
            execution_slice.changeset_hash != canonical_changeset.changeset_hash
            or execution_slice.approved_scope_ref.scope_hash != approval_scope_boundary.scope_hash
            or authority.execution_slice_hash != execution_slice.execution_slice_hash
            or authority.binding_set_hash != binding_set.binding_set_hash
            or authority.changeset_hash != canonical_changeset.changeset_hash
            or authority.approved_scope_hash != approval_scope_boundary.scope_hash
            or authority.host_instance_id != runtime.host_instance_id
            or binding_set.execution_slice_hash != execution_slice.execution_slice_hash
            or actual_delta.execution_slice_hash != execution_slice.execution_slice_hash
            or actual_delta.binding_set_hash != binding_set.binding_set_hash
            or actual_delta.grant_hash != authority.grant_hash
            or actual_delta.changeset_hash != canonical_changeset.changeset_hash
            or actual_delta.approved_scope_hash != approval_scope_boundary.scope_hash
            or actual_delta.host_instance_id != runtime.host_instance_id
            or actual_delta.document_ref != runtime.document_ref
        ):
            raise ValueError(
                "REVIT_VERIFICATION_LINEAGE_MISMATCH: admitted execution lineage does "
                "not join exactly"
            )

        if len(execution_slice.execution_units) != 1 or len(binding_set.bindings) != 1:
            raise ValueError(
                "REVIT_VERIFICATION_LINEAGE_MISMATCH: wall-thickness verification requires "
                "one execution unit and one binding"
            )
        unit = execution_slice.execution_units[0]
        binding = binding_set.bindings[0]
        if len(unit.targets) != 1 or len(binding.native_targets) != 1:
            raise ValueError(
                "REVIT_VERIFICATION_LINEAGE_MISMATCH: wall-thickness verification requires "
                "one semantic/native target"
            )
        native_target = binding.native_targets[0]
        semantic_id = unit.targets[0]
        if (
            unit.canonical_operation != "set_wall_thickness.v1"
            or binding.canonical_operation != unit.canonical_operation
            or binding.execution_unit_hash != unit.execution_unit_hash
            or binding.execution_slice_hash != execution_slice.execution_slice_hash
            or binding.host_runtime_ref != runtime
            or native_target.semantic_id != semantic_id
            or native_target.host_type != "revit"
            or native_target.document_ref != runtime.document_ref
            or native_target.native_kind != "Wall"
        ):
            raise ValueError(
                "REVIT_VERIFICATION_LINEAGE_MISMATCH: provider/native binding does "
                "not match the admitted wall-thickness slice"
            )
        return unit, binding, native_target

    def _read_snapshot(
        self,
        *,
        execution_slice: ExecutionSliceV2,
        binding,
        native_target,
        actual_delta: ActualDelta,
    ):
        """按 ActualDelta committed revision 对 exact Wall.UniqueId 发起一次独立 READ。"""
        command_material = (
            f"{actual_delta.actual_delta_hash}\n{binding.binding_hash}\n"
            f"{actual_delta.revision_after}\n{native_target.native_id}"
        )
        command_suffix = sha256(command_material.encode("utf-8")).hexdigest()[:24]
        try:
            evidence = self._snapshot_reader.read(
                command_id=f"PRODUCT-VERIFY-{command_suffix}",
                document_id=execution_slice.host_runtime_ref.document_ref,
                host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
                wall_unique_id=native_target.native_id,
                expected_revision=actual_delta.revision_after,
            )
        except ValueError as exc:
            # 只有“没有取得可用 READ response”才是可恢复 unavailable。已经返回但 identity、
            # revision 或 target 不一致时必须把原错误继续抛出，防止 newer state 被误接受。
            if str(exc).startswith("REVIT_SNAPSHOT_READ_FAILED:"):
                raise VerificationEvidenceUnavailable(
                    "REVIT_VERIFICATION_EVIDENCE_UNAVAILABLE",
                    str(exc),
                ) from exc
            raise

        if (
            getattr(evidence, "document_id", None) != execution_slice.host_runtime_ref.document_ref
            or getattr(evidence, "host_instance_id", None)
            != execution_slice.host_runtime_ref.host_instance_id
            or getattr(evidence, "wall_unique_id", None) != native_target.native_id
            or getattr(evidence, "native_kind", None) != "Wall"
            or getattr(evidence, "revision_before", None) != actual_delta.revision_after
            or getattr(evidence, "revision_after", None) != actual_delta.revision_after
        ):
            raise ValueError(
                "REVIT_VERIFICATION_EVIDENCE_MISMATCH: independent READ does not match "
                "committed identity/revision"
            )
        return evidence

    def _project_snapshot(
        self,
        *,
        canonical_changeset: CanonicalChangeSet,
        execution_slice: ExecutionSliceV2,
        unit,
        semantic_id: str,
        native_target,
        actual_delta: ActualDelta,
        evidence,
    ):
        """复用真实 DesignFactAdapter + SemanticService 生成 canonical post-state projection。"""
        facts = self._design_fact_adapter.normalize_snapshot(
            {
                "document_id": actual_delta.document_ref,
                "host_instance_id": actual_delta.host_instance_id,
                "source_revision": actual_delta.revision_after,
                "native_id": native_target.native_id,
                "native_kind": getattr(evidence, "native_kind", None),
                "builtin_category": getattr(evidence, "builtin_category", None),
                "wall_thickness_mm": getattr(evidence, "wall_thickness_mm", None),
            }
        )
        if not callable(getattr(facts, "to_dict", None)) or not hasattr(facts, "facts"):
            raise ValueError(
                "REVIT_VERIFICATION_FACTS_INVALID: design fact adapter returned an "
                "unsupported batch"
            )

        environment_id = _required_text(
            getattr(self._semantic_environment, "environment_id", None),
            "semantic_environment.environment_id",
        )
        environment_hash = _required_text(
            getattr(self._semantic_environment, "content_hash", None),
            "semantic_environment.content_hash",
        )
        changeset_environment = canonical_changeset.semantic_environment_ref
        if (
            getattr(changeset_environment, "environment_id", None) != environment_id
            or getattr(changeset_environment, "content_hash", None) != environment_hash
        ):
            raise ValueError(
                "REVIT_VERIFICATION_ENVIRONMENT_MISMATCH: pinned semantic environment "
                "differs from ChangeSet authority"
            )

        claims = self._semantic_service.project_facts(facts, environment_id)
        if not isinstance(claims, tuple):
            raise TypeError(
                "REVIT_VERIFICATION_SEMANTIC_INVALID: SemanticService project_facts "
                "must return a tuple"
            )

        classification_fact_ids = _fact_ids_for_kind(facts, "CLASSIFICATION")
        property_fact_ids = _fact_ids_for_kind(facts, "PROPERTY")
        classification_claims = tuple(
            claim
            for claim in claims
            if getattr(claim, "predicate", None) == "classification"
            and isinstance(getattr(claim, "canonical_term_id", None), str)
            and _claim_uses_fact(claim, classification_fact_ids)
        )
        thickness_claims = tuple(
            claim
            for claim in claims
            if getattr(claim, "predicate", None) == "property"
            and getattr(claim, "canonical_term_id", None) == "dsp:WallThickness"
            and _claim_uses_fact(claim, property_fact_ids)
        )
        if len(classification_claims) != 1 or len(thickness_claims) != 1:
            raise ValueError(
                "REVIT_VERIFICATION_SEMANTIC_INVALID: exact wall classification/thickness "
                "claims are unresolved"
            )
        classification_claim = classification_claims[0]
        thickness_claim = thickness_claims[0]
        # claim 的 provider-specific native:// subject 不是 semantic identity authority。
        # 两条 claim 已由 exact design-fact ids 证明来自本次 admitted native target 的独立 READ；
        # native→semantic identity 继续只由上游 admitted NativeTargetBindingEvidence 持有。
        if getattr(thickness_claim, "unit", None) != "mm":
            raise ValueError(
                "REVIT_VERIFICATION_SEMANTIC_INVALID: wall thickness claim must use canonical mm"
            )
        canonical_kind = _required_text(
            getattr(classification_claim, "canonical_term_id", None),
            "classification_claim.canonical_term_id",
        )

        guarantees: list[AspectGuarantee] = [AspectGuarantee(SemanticAspect.IDENTITY)]
        classification_assurance = _strongest_claim_assurance(classification_claims)
        property_assurance = _strongest_claim_assurance(thickness_claims)
        if classification_assurance is None or property_assurance is None:
            raise ValueError(
                "REVIT_VERIFICATION_SEMANTIC_INVALID: wall evidence lacks semantic assurance"
            )
        guarantees.extend(
            (
                AspectGuarantee(
                    SemanticAspect.CLASSIFICATION,
                    coverage_state=CoverageState.RESOLVED,
                    semantic_depth=SemanticDepth.CANONICAL,
                    assurance_level=classification_assurance,
                ),
                AspectGuarantee(
                    SemanticAspect.PROPERTIES,
                    coverage_state=CoverageState.RESOLVED,
                    semantic_depth=SemanticDepth.CANONICAL,
                    assurance_level=property_assurance,
                ),
            )
        )

        normalized_fact_batch_hash = _canonical_hash(facts.to_dict())
        claim_payloads = tuple(
            sorted(
                (_claim_payload(claim) for claim in claims),
                key=_canonical_hash,
            )
        )
        mapping_material = tuple(
            sorted(
                (
                    {
                        "mapping_id": evidence_item.removeprefix("mapping:"),
                        "provider_id": payload["provider_id"],
                        "provider_version": payload["provider_version"],
                    }
                    for payload in claim_payloads
                    for evidence_item in payload["evidence"]
                    if isinstance(evidence_item, str) and evidence_item.startswith("mapping:")
                ),
                key=_canonical_hash,
            )
        )
        mapping_profile_set_hash = _canonical_hash(mapping_material)
        semantic_model_versions = {
            compatibility.strip()
            for provider in getattr(self._semantic_environment, "providers", ())
            for compatibility in getattr(provider, "compatibility", ())
            if isinstance(compatibility, str)
            and compatibility.strip().startswith("dsp.semantic.projection-facts.")
        }
        if len(semantic_model_versions) != 1:
            raise ValueError(
                "REVIT_VERIFICATION_SEMANTIC_INVALID: pinned environment must expose "
                "one facts projection compatibility"
            )
        semantic_model_version = next(iter(semantic_model_versions))
        projection_hash = _canonical_hash(
            {
                "environment_id": environment_id,
                "environment_hash": environment_hash,
                "normalized_fact_batch_hash": normalized_fact_batch_hash,
                "mapping_profile_set_hash": mapping_profile_set_hash,
                "claims": list(claim_payloads),
            }
        )
        projection_ref = SemanticProjectionRef(
            projection_id=f"semantic-projection:{projection_hash}",
            projection_hash=projection_hash,
            semantic_model_version=semantic_model_version,
            provider_set_hash=environment_hash,
            mapping_profile_set_hash=mapping_profile_set_hash,
            normalized_fact_batch_hash=normalized_fact_batch_hash,
        )
        environment_ref = SemanticEnvironmentRef(environment_id, environment_hash)

        freshness_contract = build_operation_contract(
            project_id=canonical_changeset.project_id,
            document_ref=actual_delta.document_ref,
            canonical_operation=unit.canonical_operation,
            targets=unit.targets,
            arguments=dict(unit.arguments),
            requirements=(
                AspectRequirement(SemanticAspect.IDENTITY),
                AspectRequirement(
                    SemanticAspect.CLASSIFICATION,
                    minimum_coverage=CoverageState.RESOLVED,
                    semantic_depth=SemanticDepth.CANONICAL,
                    minimum_assurance=AssuranceLevel.RULE_DERIVED,
                ),
                AspectRequirement(
                    SemanticAspect.PROPERTIES,
                    minimum_coverage=CoverageState.RESOLVED,
                    semantic_depth=SemanticDepth.CANONICAL,
                    minimum_assurance=AssuranceLevel.RULE_DERIVED,
                ),
            ),
        )
        snapshot = SemanticSnapshot.create(
            freshness_contract,
            ReconstructionResult(
                document_ref=actual_delta.document_ref,
                host_revision=str(actual_delta.revision_after),
                coverage=freshness_contract.coverage,
                guarantees=tuple(guarantees),
                projection_ref=projection_ref,
                semantic_environment_ref=environment_ref,
            ),
        )
        return (
            snapshot,
            projection_ref,
            environment_ref,
            canonical_kind,
            thickness_claim,
        )

    def build_bundle(
        self,
        *,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
        actual_delta: ActualDelta,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundaryV2,
    ) -> VerificationEvidenceBundle:
        """从 independent exact-revision READ 构造 immutable Step33 evidence bundle。"""
        unit, binding, native_target = self._validate_lineage(
            execution_slice=execution_slice,
            authority=authority,
            binding_set=binding_set,
            actual_delta=actual_delta,
            canonical_changeset=canonical_changeset,
            approval_scope_boundary=approval_scope_boundary,
        )
        evidence = self._read_snapshot(
            execution_slice=execution_slice,
            binding=binding,
            native_target=native_target,
            actual_delta=actual_delta,
        )
        (
            snapshot,
            projection_ref,
            environment_ref,
            canonical_kind,
            thickness_claim,
        ) = self._project_snapshot(
            canonical_changeset=canonical_changeset,
            execution_slice=execution_slice,
            unit=unit,
            semantic_id=native_target.semantic_id,
            native_target=native_target,
            actual_delta=actual_delta,
            evidence=evidence,
        )

        thickness_value = getattr(thickness_claim, "value", None)
        if isinstance(thickness_value, Mapping):
            # 当前真实 provider 返回 scalar；mapping 说明 semantic contract 已漂移，不能静默兼容。
            raise TypeError(
                "REVIT_VERIFICATION_SEMANTIC_INVALID: wall thickness claim must be scalar"
            )
        subject = VerificationSubjectEvidence(
            semantic_id=native_target.semantic_id,
            canonical_kind=canonical_kind,
            properties={
                "dsp:WallThickness": {
                    "value": thickness_value,
                    "unit": "mm",
                }
            },
            placement=None,
            geometry_evidence=None,
            relationships=(),
            constraints=(),
            classification=(canonical_kind,),
            evidence_aspects=(CanonicalAspect.PROPERTIES,),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.hash,
            projection_ref=projection_ref,
        )
        verification_contract = SET_WALL_THICKNESS_V1.verification_contract
        bundle_identity = sha256(
            (
                f"{actual_delta.actual_delta_hash}\n{snapshot.hash}\n"
                f"{projection_ref.projection_hash}"
            ).encode()
        ).hexdigest()[:20]
        draft = VerificationEvidenceBundle(
            evidence_bundle_id=f"VEB-REVIT-{bundle_identity}",
            changeset_hash=canonical_changeset.changeset_hash,
            execution_slice_hash=execution_slice.execution_slice_hash,
            actual_delta_hash=actual_delta.actual_delta_hash,
            semantic_environment_ref=environment_ref,
            post_execution_snapshot_ref=snapshot,
            post_execution_projection_ref=projection_ref,
            base_host_revision=str(actual_delta.revision_after),
            baseline_snapshot_ref=None,
            baseline_projection_ref=None,
            contract_evidence=(
                VerificationContractEvidence(
                    contract_ref=canonical_hash(verification_contract),
                    contract_body=verification_contract,
                ),
            ),
            subject_evidence=(subject,),
            baseline_subject_evidence=(),
            evidence_bundle_hash="0" * 64,
        )
        return replace(
            draft,
            evidence_bundle_hash=compute_verification_evidence_bundle_hash(draft),
        )

    def build_evidence(
        self,
        *,
        materialization_id: str,
        execution_slice: ExecutionSliceV2,
        actual_delta: ActualDelta,
        verification_result: SemanticVerificationResult,
        verification_bundle: VerificationEvidenceBundle,
        convergence_profile,
    ):
        """本地 Step33 PASS 后直接委托现有 canonical convergence evidence builder。"""
        return build_materialization_canonical_evidence(
            materialization_id=materialization_id,
            execution_slice=execution_slice,
            actual_delta=actual_delta,
            verification_result=verification_result,
            verification_evidence_bundle=verification_bundle,
            convergence_profile=convergence_profile,
        )


__all__ = ["RevitWallThicknessVerificationEvidencePort"]
