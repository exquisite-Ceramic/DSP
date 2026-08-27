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


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    DIRTY = "DIRTY"
    UNKNOWN = "UNKNOWN"
    RECONSTRUCTING = "RECONSTRUCTING"


class GeometryLevel(IntEnum):
    NONE = 0
    BOUNDS = 1
    APPROXIMATE = 2
    EXACT = 3
    NATIVE = 4


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


@dataclass(frozen=True, slots=True)
class AspectRequirement:
    aspect: SemanticAspect
    geometry_level: GeometryLevel = GeometryLevel.NONE

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

    def __post_init__(self) -> None:
        if self.aspect is not SemanticAspect.GEOMETRY and self.geometry_level is not GeometryLevel.NONE:
            raise ValueError("geometry_level applies only to GEOMETRY")

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


def _normalized_requirements(
    requirements: Iterable[AspectRequirement],
) -> tuple[AspectRequirement, ...]:
    strongest: dict[SemanticAspect, GeometryLevel] = {}
    for item in requirements:
        current = strongest.get(item.aspect, GeometryLevel.NONE)
        if item.geometry_level > current:
            strongest[item.aspect] = item.geometry_level
        elif item.aspect not in strongest:
            strongest[item.aspect] = item.geometry_level
    return tuple(
        AspectRequirement(aspect, strongest[aspect])
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


def _requirements_payload(items: Iterable[AspectRequirement | AspectGuarantee]) -> list[dict[str, str]]:
    return [
        {
            "aspect": item.aspect.value,
            "required_state": item.required_state.value,
            "geometry_level": item.geometry_level.name,
        }
        for item in items
    ]


@dataclass(frozen=True, slots=True)
class FreshnessContract:
    contract_type: ContractType
    coverage: Coverage
    requirements: tuple[AspectRequirement, ...]
    operation_fingerprint: str | None = None
    contract_id: str = field(init=False)
    hash: str = field(init=False)

    def __post_init__(self) -> None:
        requirements = _normalized_requirements(self.requirements)
        if self.contract_type is ContractType.CONTEXT and self.operation_fingerprint is not None:
            raise ValueError("Context Freshness cannot have an operation_fingerprint")
        if self.contract_type is ContractType.OPERATION and not self.operation_fingerprint:
            raise ValueError("Operation Freshness requires an operation_fingerprint")
        payload = {
            "contract_type": self.contract_type.value,
            "coverage": self.coverage.payload(),
            "requirements": _requirements_payload(requirements),
            "operation_fingerprint": self.operation_fingerprint,
        }
        digest = _hash_payload(payload)
        prefix = "CTX" if self.contract_type is ContractType.CONTEXT else "OP"
        object.__setattr__(self, "requirements", requirements)
        object.__setattr__(self, "hash", digest)
        object.__setattr__(self, "contract_id", f"FC-{prefix}-{digest[:12]}")


def build_context_contract(
    document_ref: str,
    root_entities: Iterable[str],
    extra_requirements: Iterable[AspectRequirement] = (),
) -> FreshnessContract:
    extras = tuple(extra_requirements)
    for requirement in extras:
        if (
            requirement.aspect is SemanticAspect.GEOMETRY
            and requirement.geometry_level > GeometryLevel.BOUNDS
        ):
            raise ValueError("Context Freshness geometry must stay at NONE or BOUNDS")
    return FreshnessContract(
        contract_type=ContractType.CONTEXT,
        coverage=Coverage(document_ref, tuple(root_entities), 0),
        requirements=(AspectRequirement(SemanticAspect.IDENTITY), *extras),
    )


def build_operation_contract(
    *,
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

    def __post_init__(self) -> None:
        document_ref = self.document_ref.strip()
        host_revision = self.host_revision.strip()
        if not document_ref or not host_revision:
            raise ValueError("document_ref and host_revision are required")
        guarantees = tuple(
            sorted(
                (
                    item
                    if isinstance(item, AspectGuarantee)
                    else AspectGuarantee(item.aspect, item.geometry_level)
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
    freshness_contract_id: str
    freshness_contract_hash: str
    document_ref: str
    base_host_revision: str
    coverage: Coverage
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
        kind = (
            SnapshotKind.CONTEXT
            if contract.contract_type is ContractType.CONTEXT
            else SnapshotKind.PLANNING
        )
        payload = {
            "kind": kind.value,
            "freshness_contract_id": contract.contract_id,
            "freshness_contract_hash": contract.hash,
            "document_ref": result.document_ref,
            "base_host_revision": result.host_revision,
            "coverage": result.coverage.payload(),
            "aspect_guarantees": _requirements_payload(result.guarantees),
        }
        digest = _hash_payload(payload)
        prefix = "CS" if kind is SnapshotKind.CONTEXT else "PS"
        return cls(
            snapshot_id=f"{prefix}-{digest[:12]}",
            kind=kind,
            freshness_contract_id=contract.contract_id,
            freshness_contract_hash=contract.hash,
            document_ref=result.document_ref,
            base_host_revision=result.host_revision,
            coverage=result.coverage,
            aspect_guarantees=result.guarantees,
            hash=digest,
        )


@dataclass(frozen=True, slots=True)
class SnapshotSet:
    members: tuple[SemanticSnapshot, ...]
    kind: SnapshotKind = field(default=SnapshotKind.PLANNING, init=False)
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
        members = tuple(sorted(self.members, key=lambda item: (item.document_ref, item.snapshot_id)))
        payload = {
            "kind": self.kind.value,
            "members": [
                {
                    "document_ref": item.document_ref,
                    "snapshot_id": item.snapshot_id,
                    "snapshot_hash": item.hash,
                    "base_host_revision": item.base_host_revision,
                }
                for item in members
            ],
        }
        digest = _hash_payload(payload)
        object.__setattr__(self, "members", members)
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

        strongest: dict[SemanticAspect, GeometryLevel] = {}
        for guarantee in result.guarantees:
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
