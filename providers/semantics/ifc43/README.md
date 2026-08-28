# IFC4.3 Semantic Provider

`buildingSMART.ifc43@4.3.2.0` is DSP's reference STANDARD Semantic Provider for the `ifc` namespace.

## Source

- Standard release: `IFC4X3_ADD2 / IFC 4.3.2.0`
- Inspection engine: `ifcopenshell==0.8.5`
- Runtime network lookup: none

IfcOpenShell is the pinned schema/template inspection engine. The normalized IFC semantics, not the library version by itself, define the provider `content_hash`.

## Capabilities

- `VOCABULARY`: entity, relationship, inheritance, attribute, enum, select, datatype, official Pset/Qto terms and members.
- `VALIDATION`: deterministic claim-level legality/type/enum checks only.
- `PROJECTION`: marker-only until the Phase E `NormalizedDesignFact` contract is introduced.
- `MAPPING`: not claimed.

Lookup is exact and case-sensitive. Member identities are owner-qualified, for example `ifc:IfcWall.PredefinedType`, `ifc:Pset_WallCommon.FireRating`, and `ifc:IfcWallTypeEnum.SOLIDWALL`.

## Hash and version policy

The provider hashes normalized machine semantics with canonical JSON + SHA-256. Presentation text is excluded. The reviewed IFC4.3.2.0 catalog hash is frozen as a golden regression value; a semantic drift under the same provider ID/version fails closed.

## Metro boundary

The Metro V3.2 standard is used by PR #9 only as a conformance/reference corpus. Metro `PsetProj_*`, `QtoProj_*`, P-M/P-C/P-R, IDS, mapping, and engineering rules belong to the later Metro Semantic Provider.

## Non-goals

This package does not perform complete IFC STEP-file validation, geometry validation, Alignment continuity, clash/clearance analysis, IDS validation, Host-native extraction/mapping, DSP Canonical Actions, or Metro/enterprise semantic ownership.
