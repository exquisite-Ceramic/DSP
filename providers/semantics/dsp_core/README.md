# DSP Core Semantic Provider

`dsp.core@1.0` is the authoritative `dsp:*` VOCABULARY provider for the DSP v0.6 baseline.

It defines exactly these initial terms:

- `dsp:SemanticIdentity`
- `dsp:HostBinding`
- `dsp:ExternalIdentity`
- `dsp:WallThickness`
- `dsp:Freshness`
- `dsp:Assurance`
- `dsp:Snapshot`
- `dsp:ChangeSet`

Production code depends only on `semantic_service` provider contracts. It does not depend on D5, Semantic MCP, Host products, IFC/Metro providers, D4/D6/D7, or Gateway behavior.

Machine-semantic content is content-addressed. Presentation-only label/description edits do not change the provider content hash; machine-semantic edits do.

The v1.0 provider claims only `VOCABULARY`. `MAPPING`, `VALIDATION`, and `PROJECTION` are intentionally unclaimed and are not implemented as stubs.
