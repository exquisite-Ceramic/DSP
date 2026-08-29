# Enterprise Mapping Provider

`dsp.enterprise.mapping@1.0.0` is the Phase E Step 20 ENTERPRISE Semantic Provider for deterministic projection of structured native classification evidence into canonical claims.

Current machine source is packaged in `data/enterprise_mappings_v1.yaml`. It is loaded locally, normalized into an immutable catalog, and checked against a reviewed golden SHA-256. Runtime network access and Markdown parsing are not part of the provider path.

The provider declares only `ifc` EXTENSION authority and requires `buildingSMART.ifc43@4.3.2.0`; it does not own IFC vocabulary meaning. It declares `PROJECTION` plus compatibility token `dsp.semantic.projection-facts.v1`.

Step 20 mapping source contains the deterministic A-WALL rules that will project `autocad.layer` classification evidence to `ifc:IfcWall`. Match language is intentionally restricted to EXACT and PREFIX; regex/glob semantics are not supported. Conflicting overlapping rules fail catalog construction rather than relying on rule order.

Step 20 does not add an `acme:*` vocabulary, Semantic MCP endpoint, D5 integration, Host SDK dependency, or changes to AutoCAD/IFC/Metro production implementations. D5 zero-change proof is deferred to Step 21.
