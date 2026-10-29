# Normalized archetype contract v1

`scripts/archetype_contract.py` is the executable validator/adapter and capability
registry (both version 1). Normalization is pure: it reads one selected manifest
and never edits it or loads another baseline. Unknown profiles can be described
and extracted; `require_backend` rejects planning/materialization explicitly.

Required normalized fields: `contractVersion: 1`, `adapter`, `identity{name,version}`,
`lifecycle{approved,frozen,generationEnabled}`, `profile`, `registryVersion`,
`backendSupported`, `backend`, `decisions`, `quality.checkstyle{applicability,source}`,
`style`, `templateInventory`. Missing source facts remain null/unknown, not defaults
from another archetype. The detached backend record declares adapter version,
planner, materializer, HTTP/batch input kind, token dialect, scaffold support and limits.

Supported source schemas:
- `identity` with `schemaVersion: 1`: explicit profile and baseline-owned facts.
- `archetype` with `schema_version: "1.0"`: compatibility adapter scoped strictly
  to `claro-spring-ms/1.0.0`. Its historical missing profile resolves to legacy JPA;
  absent lifecycle flags remain unknown. The existing approved baseline is preserved.

No inference of a legacy profile solely from a persistence dependency. An unknown
fourth archetype remains independent. Template rendering dialect is an adapter
capability, not a migration of frozen templates. JDBC target coupling is an explicit
existing limitation pending package 5, not evidence of general domain support.

Selection precedes adaptation (`generation_context.py`). A plan's profile must match
the selected manifest; only the legacy compatibility adapter permits missing old
plan profile fields. Checkstyle applicability comes from that manifest, independently
of whether input is HTTP or batch. Actual execution evidence remains separate.
