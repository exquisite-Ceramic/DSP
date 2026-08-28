"""Contract-bound two-phase semantic freshness and snapshots."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from hashlib import sha256
import json
from typing import Protocol


class SemanticAspect(str, Enum):
    IDENTITY = "IDENTITY"
    PROPERTIES = "PROPERTIES"
    PLACEMENT = "PLACEMENT"
    GEOMETRY = "GEOMETRY"
    SPATIAL = "SPATIAL"
    CONNECTIVITY = "CONNECTIVITY"
    RELATIONSHIPS = "RELATIONSHIPS"
    CONSTRAINTS = "CONSTRAINTS"
    CLASSIFICATION = "CLASSIFICATION"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    DIRTY = "DIRTY"
    UNKNOWN = "UNKNOWN"
    RECONSTRUCTING = "RECONSTRUCTING"


class CoverageState(IntEnum):
    UNRESOLVED = 0
    PARTIAL = 1
    RESOLVED = 2


class SemanticDepth(IntEnum):
    NATIVE = 0
    NORMALIZED = 1
    CANONICAL = 2
    DOMAIN = 3


class GeometryLevel(IntEnum):
    NONE = 0
    BOUNDS = 1
    APPROXIMATE = 2
    EXACT = 3
    NATIVE = 4


class AssuranceLevel(IntEnum):
    UNKNOWN = 0
    HEURISTIC = 1
    RULE_DERIVED = 2
    STANDARD_MAPPED = 3
    NATIVE_ASSERTED = 4


class ContractType(str, Enum):
    CONTEXT = "CONTEXT_FRESHNESS"
    OPERATION = "OPERATION_FRESHNESS"


class SnapshotKind(str, Enum):
    CONTEXT = "CONTEXT"
    PLANNING = "PLANNING"


class FreshnessError(ValueError):
    """Base class for deterministic freshness barrier failures."""


class RevisionChangedError(FreshnessError):
    """Host revision changed while reconstruction was in progress."""


class CoverageMismatchError(FreshnessError):
    """Reconstruction result does not match the requested coverage."""


class FreshnessUnsatisfiedError(FreshnessError):
    """Reconstruction did not satisfy every required semantic aspect."""


class SnapshotSetError(ValueError):
    """SnapshotSet violates PlanningSnapshot-only invariants."""


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


@dataclass(frozen=True, slots=True)
class SemanticEnvironmentRef:
    environment_id: str
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "environment_id",
            _required_text(self.environment_id, "environment_id"),
        )
        object.__setattr__(
            self,
            "content_hash",
            _required_text(self.content_hash, "content_hash"),
        )

    def payload(self) -> dict[str, str]:
        return {
            "environment_id": self.environment_id,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class SemanticProjectionRef:
    projection_id: str
    projection_hash: str
    semantic_model_version: str
    provider_set_hash: str
    mapping_profile_set_hash: str
    normalized_fact_batch_hash: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "projection_id",
            "projection_hash",
            "semantic_model_version",
            "provider_set_hash",
            "mapping_profile_set_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        normalized_fact_batch_hash = (
            self.normalized_fact_batch_hash.strip()
            if self.normalized_fact_batch_hash is not None
            else None
        )
        if normalized_fact_batch_hash == "":
            normalized_fact_batch_hash = None
        object.__setattr__(
            self,
            "normalized_fact_batch_hash",
            normalized_fact_batch_hash,
        )

    def payload(self) -> dict[str, str | None]:
        return {
            "projection_id": self.projection_id,
            "projection_hash": self.projection_hash,
            "semantic_model_version": self.semantic_model_version,
            "provider_set_hash": self.provider_set_hash,
            "mapping_profile_set_hash": self.mapping_profile_set_hash,
            "normalized_fact_batch_hash": self.normalized_fact_batch_hash,
        }


@dataclass(frozen=True, slots=True)
class AspectRequirement:
    aspect: SemanticAspect
    geometry_level: GeometryLevel = GeometryLevel.NONE
    minimum_coverage: CoverageState | None = None
    semantic_depth: SemanticDepth | None = None
    minimum_assurance: AssuranceLevel = AssuranceLevel.UNKNOWN

    def __post_init__(self) -> None:
        if self.aspect is not SemanticAspect.GEOMETRY and self.geometry_level is not GeometryLevel.NONE:
            raise ValueError("geometry_level applies only to GEOMETRY")

    @property
    def required_state(self) -> FreshnessState:
        return FreshnessState.FRESH


@dataclass(frozen=True, slots=True)
class AspectGuarantee:
    aspect: SemanticAspect
    geometry_level: GeometryLevel = GeometryLevel.NONE
    coverage_ref: str | None = None
    coverage_state: CoverageState | None = None
    semantic_depth: SemanticDepth | None = None
    assurance_level: AssuranceLevel = AssuranceLevel.UNKNOWN

    def __post_init__(self) -> None:
        if self.aspect is not SemanticAspect.GEOMETRY and self.geometry_level is not GeometryLevel.NONE:
            raise ValueError("geometry_level applies only to GEOMETRY")
        coverage_ref = self.coverage_ref.strip() if self.coverage_ref is not None else None
        if coverage_ref == "":
            coverage_ref = None
        object.__setattr__(self, "coverage_ref", coverage_ref)

    @property
    def required_state(self) -> FreshnessState:
        return FreshnessState.FRESH


@dataclass(frozen=True, slots=True)
class Coverage:
    document_ref: str
    root_entities: tuple[str, ...]
    neighborhood_depth: int = 0
    neighborhood_relations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        document_ref = self.document_ref.strip()
        if not document_ref:
            raise ValueError("document_ref is required")
        if self.neighborhood_depth < 0:
            raise ValueError("neighborhood_depth must be >= 0")
        roots = tuple(sorted({item.strip() for item in self.root_entities if item.strip()}))
        relations = tuple(
            sorted({item.strip() for item in self.neighborhood_relations if item.strip()})
        )
        object.__setattr__(self, "document_ref", document_ref)
        object.__setattr__(self, "root_entities", roots)
        object.__setattr__(self, "neighborhood_relations", relations)

    def payload(self) -> dict[str, object]:
        return {
            "document_ref": self.document_ref,
            "root_entities": list(self.root_entities),
            "neighborhood": {
                "depth": self.neighborhood_depth,
                "relations": list(self.neighborhood_relations),
            },
        }


def _max_optional(left, right):
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _normalized_requirements(
    requirements: Iterable[AspectRequirement],
) -> tuple[AspectRequirement, ...]:
    strongest: dict[SemanticAspect, AspectRequirement] = {}
    for item in requirements:
        current = strongest.get(item.aspect)
        if current is None:
            strongest[item.aspect] = item
            continue
        strongest[item.aspect] = AspectRequirement(
            item.aspect,
            geometry_level=max(current.geometry_level, item.geometry_level),
            minimum_coverage=_max_optional(
                current.minimum_coverage,
                item.minimum_coverage,
            ),
            semantic_depth=_max_optional(current.semantic_depth, item.semantic_depth),
            minimum_assurance=max(
                current.minimum_assurance,
                item.minimum_assurance,
            ),
        )
    return tuple(
        strongest[aspect]
        for aspect in sorted(strongest, key=lambda value: value.value)
    )


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _requirement_payload(items: Iterable[AspectRequirement]) -> list[dict[str, str | None]]:
    return [
        {
            "aspect": item.aspect.value,
            "required_state": item.required_state.value,
            "geometry_level": item.geometry_level.name,
            "minimum_coverage": (
                item.minimum_coverage.name
                if item.minimum_coverage is not None
                else None
            ),
            "semantic_depth": (
                item.semantic_depth.name if item.semantic_depth is not None else None
            ),
            "minimum_assurance": item.minimum_assurance.name,
        }
        for item in items
    ]


def _guarantee_payload(items: Iterable[AspectGuarantee]) -> list[dict[str, str | None]]:
    return [
        {
            "aspect": item.aspect.value,
            "coverage_ref": item.coverage_ref,
            "required_state": item.required_state.value,
            "geometry_level": item.geometry_level.name,
            "coverage_state": (
                item.coverage_state.name if item.coverage_state is not None else None
            ),
            "semantic_depth": (
                item.semantic_depth.name if item.semantic_depth is not None else None
            ),
            "assurance_level": item.assurance_level.name,
        }
        for item in items
    ]


@dataclass(frozen=True, slots=True)
class FreshnessContract:
    project_id: str
    contract_type: ContractType
    coverage: Coverage
    requirements: tuple[AspectRequirement, ...]
    operation_fingerprint: str | None = None
    contract_id: str = field(init=False)
    hash: str = field(init=False)

    def __post_init__(self) -> None:
        project_id = self.project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        requirements = _normalized_requirements(self.requirements)
        if self.contract_type is ContractType.CONTEXT and self.operation_fingerprint is not None:
            raise ValueError("Context Freshness cannot have an operation_fingerprint")
        if self.contract_type is ContractType.OPERATION and not self.operation_fingerprint:
            raise ValueError("Operation Freshness requires an operation_fingerprint")
        payload = {
            "project_id": project_id,
            "contract_type": self.contract_type.value,
            "coverage": self.coverage.payload(),
            "requirements": _requirement_payload(requirements),
            "operation_fingerprint": self.operation_fingerprint,
        }
        digest = _hash_payload(payload)
        prefix = "CTX" if self.contract_type is ContractType.CONTEXT else "OP"
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "requirements", requirements)
        object.__setattr__(self, "hash", digest)
        object.__setattr__(self, "contract_id", f"FC-{prefix}-{digest[:12]}")


def build_context_contract(
    document_ref: str,
    root_entities: Iterable[str],
    extra_requirements: Iterable[AspectRequirement] = (),
    *,
    project_id: str,
) -> FreshnessContract:
    extras = tuple(extra_requirements)
    for requirement in extras:
        if (
            requirement.aspect is SemanticAspect.GEOMETRY
            and requirement.geometry_level > GeometryLevel.BOUNDS
        ):
            raise ValueError("Context Freshness geometry must stay at NONE or BOUNDS")
    return FreshnessContract(
        project_id=project_id,
        contract_type=ContractType.CONTEXT,
        coverage=Coverage(document_ref, tuple(root_entities), 0),
        requirements=(AspectRequirement(SemanticAspect.IDENTITY), *extras),
    )


def build_operation_contract(
    *,
    project_id: str,
    document_ref: str,
    canonical_operation: str,
    targets: Iterable[str],
    arguments: dict[str, object],
    requirements: Iterable[AspectRequirement],
) -> FreshnessContract:
    canonical_operation = canonical_operation.strip()
    if not canonical_operation:
        raise ValueError("canonical_operation is required")
    coverage = Coverage(document_ref, tuple(targets), 0)
    operation_fingerprint = _hash_payload(
        {
            "canonical_operation": canonical_operation,
            "targets": list(coverage.root_entities),
            "arguments": arguments,
        }
    )
    return FreshnessContract(
        project_id=project_id,
        contract_type=ContractType.OPERATION,
        coverage=coverage,
        requirements=tuple(requirements),
        operation_fingerprint=operation_fingerprint,
    )


@dataclass(frozen=True, slots=True)
class ReconstructionResult:
    document_ref: str
    host_revision: str
    coverage: Coverage
    guarantees: tuple[AspectGuarantee, ...]
    projection_ref: SemanticProjectionRef
    semantic_environment_ref: SemanticEnvironmentRef

    def __post_init__(self) -> None:
        document_ref = self.document_ref.strip()
        host_revision = self.host_revision.strip()
        if not document_ref or not host_revision:
            raise ValueError("document_ref and host_revision are required")
        if not isinstance(self.projection_ref, SemanticProjectionRef):
            raise TypeError("projection_ref must be a SemanticProjectionRef")
        if not isinstance(self.semantic_environment_ref, SemanticEnvironmentRef):
            raise TypeError("semantic_environment_ref must be a SemanticEnvironmentRef")
        guarantees = tuple(
            sorted(
                (
                    item
                    if isinstance(item, AspectGuarantee)
                    else AspectGuarantee(
                        item.aspect,
                        item.geometry_level,
                        coverage_state=item.minimum_coverage,
                        semantic_depth=item.semantic_depth,
                        assurance_level=item.minimum_assurance,
                    )
                    for item in self.guarantees
                ),
                key=lambda item: item.aspect.value,
            )
        )
        object.__setattr__(self, "document_ref", document_ref)
        object.__setattr__(self, "host_revision", host_revision)
        object.__setattr__(self, "guarantees", guarantees)


@dataclass(frozen=True, slots=True)
class SemanticSnapshot:
    snapshot_id: str
    kind: SnapshotKind
    project_id: str
    freshness_contract_id: str
    freshness_contract_hash: str
    document_ref: str
    base_host_revision: str
    coverage: Coverage
    projection_ref: SemanticProjectionRef
    semantic_environment_ref: SemanticEnvironmentRef
    aspect_guarantees: tuple[AspectGuarantee, ...]
    hash: str

    @classmethod
    def create(
        cls,
        contract: FreshnessContract,
        result: ReconstructionResult,
    ) -> "SemanticSnapshot":
        if result.document_ref != contract.coverage.document_ref:
            raise CoverageMismatchError("reconstruction document does not match contract")
        if result.coverage != contract.coverage:
            raise CoverageMismatchError("reconstruction coverage must exactly match contract coverage")
        expected_coverage_ref = f"{contract.contract_id}#coverage"
        bound_guarantees = tuple(
            AspectGuarantee(
                guarantee.aspect,
                guarantee.geometry_level,
                guarantee.coverage_ref or expected_coverage_ref,
                coverage_state=guarantee.coverage_state,
                semantic_depth=guarantee.semantic_depth,
                assurance_level=guarantee.assurance_level,
            )
            for guarantee in result.guarantees
        )
        kind = (
            SnapshotKind.CONTEXT
            if contract.contract_type is ContractType.CONTEXT
            else SnapshotKind.PLANNING
        )
        payload = {
            "kind": kind.value,
            "project_id": contract.project_id,
            "freshness_contract_id": contract.contract_id,
            "freshness_contract_hash": contract.hash,
            "document_ref": result.document_ref,
            "base_host_revision": result.host_revision,
            "coverage": result.coverage.payload(),
            "semantic_projection_ref": result.projection_ref.payload(),
            "semantic_environment_ref": result.semantic_environment_ref.payload(),
            "aspect_guarantees": _guarantee_payload(bound_guarantees),
        }
        digest = _hash_payload(payload)
        prefix = "CS" if kind is SnapshotKind.CONTEXT else "PS"
        return cls(
            snapshot_id=f"{prefix}-{digest[:12]}",
            kind=kind,
            project_id=contract.project_id,
            freshness_contract_id=contract.contract_id,
            freshness_contract_hash=contract.hash,
            document_ref=result.document_ref,
            base_host_revision=result.host_revision,
            coverage=result.coverage,
            projection_ref=result.projection_ref,
            semantic_environment_ref=result.semantic_environment_ref,
            aspect_guarantees=bound_guarantees,
            hash=digest,
        )


@dataclass(frozen=True, slots=True)
class SnapshotSet:
    members: tuple[SemanticSnapshot, ...]
    kind: SnapshotKind = field(default=SnapshotKind.PLANNING, init=False)
    semantic_environment_ref: SemanticEnvironmentRef = field(init=False)
    snapshot_set_id: str = field(init=False)
    hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.members:
            raise SnapshotSetError("SnapshotSet requires at least one PlanningSnapshot")
        if any(member.kind is not SnapshotKind.PLANNING for member in self.members):
            raise SnapshotSetError("SnapshotSet may contain PlanningSnapshots only")
        document_refs = [member.document_ref for member in self.members]
        if len(set(document_refs)) != len(document_refs):
            raise SnapshotSetError("SnapshotSet requires one PlanningSnapshot per document")
        environments = {member.semantic_environment_ref for member in self.members}
        if len(environments) != 1:
            raise SnapshotSetError("SnapshotSet requires one pinned SemanticEnvironment")
        semantic_environment_ref = next(iter(environments))
        members = tuple(sorted(self.members, key=lambda item: (item.document_ref, item.snapshot_id)))
        payload = {
            "kind": self.kind.value,
            "semantic_environment_ref": semantic_environment_ref.payload(),
            "members": [
                {
                    "document_ref": item.document_ref,
                    "snapshot_id": item.snapshot_id,
                    "snapshot_hash": item.hash,
                    "base_host_revision": item.base_host_revision,
                    "semantic_projection_ref": item.projection_ref.payload(),
                }
                for item in members
            ],
        }
        digest = _hash_payload(payload)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "semantic_environment_ref", semantic_environment_ref)
        object.__setattr__(self, "hash", digest)
        object.__setattr__(self, "snapshot_set_id", f"PSS-{digest[:12]}")

    @classmethod
    def create(cls, members: Iterable[SemanticSnapshot]) -> "SnapshotSet":
        return cls(tuple(members))

    @property
    def member_snapshot_ids(self) -> tuple[str, ...]:
        return tuple(member.snapshot_id for member in self.members)


class _DirtyMap(Protocol):
    def mark_fresh(
        self,
        document_id: str,
        semantic_ids: Iterable[str],
        aspects: Iterable[SemanticAspect],
    ) -> None: ...


Reconstructor = Callable[[FreshnessContract, str], ReconstructionResult]


class FreshnessResolver:
    """Apply a contract-bound freshness barrier and emit an explicit snapshot."""

    def __init__(self, dirty_map: _DirtyMap) -> None:
        self._dirty_map = dirty_map

    def resolve(
        self,
        contract: FreshnessContract,
        *,
        expected_host_revision: str,
        reconstruct: Reconstructor,
    ) -> SemanticSnapshot:
        expected_host_revision = expected_host_revision.strip()
        if not expected_host_revision:
            raise ValueError("expected_host_revision is required")

        result = reconstruct(contract, expected_host_revision)
        if result.host_revision != expected_host_revision:
            raise RevisionChangedError(
                f"host revision changed from {expected_host_revision!r} to {result.host_revision!r}"
            )
        if result.document_ref != contract.coverage.document_ref:
            raise CoverageMismatchError("reconstruction document does not match contract")
        if result.coverage != contract.coverage:
            raise CoverageMismatchError("reconstruction coverage must exactly match contract coverage")

        expected_coverage_ref = f"{contract.contract_id}#coverage"
        strongest: dict[SemanticAspect, GeometryLevel] = {}
        for guarantee in result.guarantees:
            if guarantee.coverage_ref is not None and guarantee.coverage_ref != expected_coverage_ref:
                raise CoverageMismatchError(
                    f"guarantee scope {guarantee.coverage_ref!r} does not match "
                    f"{expected_coverage_ref!r}"
                )
            strongest[guarantee.aspect] = max(
                strongest.get(guarantee.aspect, GeometryLevel.NONE),
                guarantee.geometry_level,
            )

        missing: list[str] = []
        for requirement in contract.requirements:
            level = strongest.get(requirement.aspect)
            if level is None or level < requirement.geometry_level:
                missing.append(requirement.aspect.value)
        if missing:
            raise FreshnessUnsatisfiedError(
                "reconstruction did not satisfy: " + ", ".join(sorted(missing))
            )

        self._dirty_map.mark_fresh(
            contract.coverage.document_ref,
            contract.coverage.root_entities,
            tuple(requirement.aspect for requirement in contract.requirements),
        )
        return SemanticSnapshot.create(contract, result)
