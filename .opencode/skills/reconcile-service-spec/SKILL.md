---
name: reconcile-service-spec
description: Use when creating or validating `.factory/service-spec.yml` by deterministically reconciling `.factory/openapi-spec.yml` with `.factory/sparx-spec.yml` while preserving source ownership, citations, inactive behavior, conflicts, and readiness.
---

# Reconcile Service Specification

Read repository-root `AGENTS.md` first. Reconciliation is a deterministic,
structural combination of the already-approved `.factory/openapi-spec.yml` and
target-specific `.factory/sparx-spec.yml`. Do not re-normalize OpenAPI or rerun
any Sparx stage. Do not read the OpenAPI source contract, global Sparx results,
Sparx index/context, or source HTML. Validate Sparx citations only against the
specific Stage 2A units referenced by target semantic result source units.

## Ownership and reconciliation

OpenAPI owns active HTTP method/path, operationId, path/query/header/cookie
parameters, request bodies, response schemas/status codes/headers, security,
and API-level declared schema constraints. Copy these values from the normalized
OpenAPI artifact with exact artifact fingerprint and operation JSON-pointer
provenance.

Sparx owns process/action/integration/persistence/validation/error behavior,
sequencing, explicit lifecycle, inactive history, warnings and evidence gaps.
Keep Sparx semantics under operation behavior only when exact evidence ties them
to that operation; otherwise retain them at service behavior scope. Never fill
OpenAPI contract fields from Sparx or invent Sparx behavior from OpenAPI.

Match operations by normalized exact method + path. Operation IDs may be used
only when an explicit exact identifier exists in Sparx. A name, summary, tag,
or approximate route resemblance is not sufficient. Classify every active
OpenAPI operation as `matched`, `partially-matched`, `no-sparx-behavior`, or
`ambiguous`; preserve evidence and gaps for the chosen status.

Conflict means two active authoritative statements about the same operation
contradict. Do not create a conflict for an inactive/eliminated Sparx operation
omitted from OpenAPI, implementation gaps, missing persistence evidence, or
additional Sparx metadata. An explicitly inactive item stays in historical
traceability and is never promoted to active behavior.

Deduplicate only where exact evidence-backed identity is established. Merge
only exact method/path operations or exact source/target integrations; preserve
the union of citations and source units, and do not raise confidence. Keep
similar or weakly-related items separate. Preserve all ambiguities, missing
evidence and warnings.

## Deterministic script

Run:

```text
python .opencode/skills/reconcile-service-spec/scripts/reconcile_specs.py
```

The script reads only the normalized OpenAPI artifact and consolidated Sparx
spec, plus target semantic units directly referenced for citation validation.
It writes `.factory/service-spec.yml` atomically and deterministically. It does
not call a model or inspect OpenAPI for Sparx semantics.

The output contains service metadata, source fingerprints, one entry per active
OpenAPI operation, full contract data and field provenance, matched Sparx
behavior, inactive operations, unresolved conflicts/ambiguities/missing evidence,
warnings, global traceability and readiness.

`contractComplete` reports whether the normalized OpenAPI contract passes its
structural validity gate. `behaviorComplete` reports whether required behavior
is free of unresolved ambiguity/gaps. `implementationReady` is false when
required behavior or persistence remains unspecified, even if the contract is
complete. A complete HTTP contract does not imply implementation readiness.

Readiness distinguishes two gates:

- `strictImplementationReady` requires a complete active contract, sufficient
  required behavior and mappings, sufficient persistence/integration semantics
  where required, and no unresolved blocker that would force invented behavior.
  The legacy `implementationReady` value must equal this strict gate.
- `scaffoldImplementationReady` is independent of `behaviorComplete`. It is true
  only when the active contract and operations are complete and known, inactive
  operations are excluded, an approved archetype is available, unresolved
  behavior is explicit, and generation can omit unresolved functional
  implementation.

When safe scaffold readiness is true, record allowed and excluded scopes and
the unresolved behavior in readiness. Allowed scope is limited to archetype-owned
technical structure/configuration and contract-derived interfaces, DTOs,
declared validation/error shapes, and empty contract-level test skeletons.
Behavioral implementations, mappings, ports, clients, persistence, entities,
repositories, SQL, and business tests require evidence; otherwise exclude them.
Never imply functionality through placeholder behavior. A scaffold-ready service
is not functionally complete.

To recalculate readiness without re-running semantic reconciliation, use the
readiness-only mode of the deterministic script:

```text
python .opencode/skills/reconcile-service-spec/scripts/reconcile_specs.py --readiness-only --archetype archetypes/<name>/<version>/archetype.yml
```

This mode reads and updates only `.factory/service-spec.yml` readiness and the
specified archetype manifest; it does not read or rewrite OpenAPI/Sparx
semantics.

## Validation gate

1. Each active OpenAPI operation appears exactly once and retains method/path,
   operationId, parameters, request/response, headers, security, response codes
   and API-declared constraints from its OpenAPI JSON pointer.
2. Every Sparx semantic item retains exact evidenceIds, confidence class,
   source unit identity/fingerprint and source page.
3. Every citation resolves in a directly referenced target semantic unit, or in
   the embedded human-reviewed decision provenance for the reviewed decision.
4. Explicit inactive behavior stays outside active operations and is not a
   conflict solely because OpenAPI omits it.
5. Missing persistence/flow detail remains unresolved; do not create entities,
   tables, queries, mappings, statuses or behavior to fill gaps.
6. No unrelated/global semantic results or unapproved sources are consumed.
7. Run the script twice on unchanged inputs and compare output SHA-256 bytes.

Do not generate Java, an implementation plan, or any later-stage artifact.

## Source authority gate

Before consolidating, require a resolved `.factory/sparx-target-authority.yml` and consume only
`.factory/sparx-authoritative-endpoint-detail.yml` (plus its authoritative interpretations). Evidence listed in
`.factory/sparx-nonauthoritative-evidence.yml` is stale for generation: keep it for traceability, never merge it by name,
route or label similarity. Conflicts that existed only because of non-authoritative evidence are
`resolved-by-authority-selection`; conflicts between authoritative Sparx and OpenAPI or a human-reviewed decision must be
reported side by side ("authoritative Sparx says / reviewed decision says") and left for human resolution.

## Authoritative consolidation with human-reviewed decisions (Phase 8.5)

When the source authority is resolved and the remaining conflicts are covered by human-reviewed decisions that carry
machine-readable `machineEffects` (column aliases, field mappings, contract amendments, outcome semantics, filter policy),
use `scripts/consolidate_authoritative_specs.py`:

- `--stage reassess` writes `.factory/sparx-decision-reassessment.yml`: every conflict is classified as
  `unresolved-business-blocker`, `resolved-by-authority-selection`, `resolved-by-human-reviewed-decision` or
  `technical-implementation-choice`; technical choices never block readiness.
- `--stage consolidate` runs the reassessment and, only if `strictImplementationReady` and `functionalCodeGenerationReady`
  are both true, archives the previous specs under `.factory/archive/pre-phase-8.5/` and writes
  `.factory/sparx-spec.yml` and `.factory/service-spec.yml` (authoritative branch only, decisions applied exactly once,
  Sparx evidence never rewritten, contract amendments recorded in `effectiveContractDeltas` without touching the input
  OpenAPI). Then run `reconcile_specs.py --readiness-only --archetype …` to recompute scaffold/strict readiness.
- Prose Activity text is interpreted only through `.factory/sparx-authoritative-prose-interpretation.yml`, whose rules cite
  literal source lines and are verified at build time. Process sequencing comes from
  `parse-sparx/scripts/extract_process_sequence.py` (explicit SequenceFlow connectors, never numeric labels).
