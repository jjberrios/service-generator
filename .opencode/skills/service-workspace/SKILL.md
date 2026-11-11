---
name: service-workspace
description: Use for per-service workspaces under .factory/services/<service>, migration of archived artifacts, the mandatory Sparx vs Swagger consistency gate, checkpoint resume, sandbox execution of pipeline scripts and protection of manually modified output files.
---

# Service workspace, consistency gate and file protection

## Current authority flow (Iteration 2B, Model B)

Read `docs/operational-reviews-v1.md`. Agents prepare typed requests with
`workspace_cli.py decision-request-prepare`; only the user's separate interactive
`review_cli.py` flow records local operational reviews. Legacy gate-resolve,
gate-authorize and protect-authorize are retired, including direct writer APIs.
Historical approval YAML remains evidence, not current authority. The older
command descriptions below are historical where they conflict with this rule.
H-02 remains open: same-user arbitrary execution is not prevented or authenticated.

Scripts (`.opencode/skills/service-workspace/scripts/`): `workspace.py` (workspaces, checkpoints, sandbox runner), `consistency_gate.py` (blocking gate; reuses
`audit-sparx-swagger`), `gate_guard.py` (guard called by every post-gate script), `migrate_legacy.py`, `file_protection.py`, `workspace_cli.py`.

Autonomous engineering: follow `question-policy.md` in every specialist. Run
`workspace_cli.py capability-check <service>` before expensive source interpretation
and `workspace_cli.py question-triage <service> --input <workspace-relative.yml>`
before presenting grouped blockers. These commands are read-only, grant no
authority and do not replace the post-plan feasibility check or consistency gate.

## Layout

`.factory/services/<service>/` holds, per service: `openapi-spec.yml`, `sparx-target-authority.yml`, `sparx-authoritative-endpoint-detail.yml`,
`sparx-nonauthoritative-evidence.yml`, `sparx-spec.yml`, `service-spec.yml`, `sparx-reviewed-decisions.yml`, `full-planning-input.yml`,
`generation-parameters.yml`, `implementation-plan.yml`, `service-generation-state.yml`, `consistency/` (`findings.yml`, `supplemental.yml`, `resolutions.yml`,
`authorization.yml`, `gate.yml`, `snapshot-manifest.yml`), `migration/`, `user-owned-files.yml`, `overwrite-authorizations.yml` and validation reports.
Provenance paths inside artifacts keep their `.factory/...` form; `workspace_cli.py run` executes an existing script in a sandbox whose `.factory`, `input`,
`archetypes`, `output` and `.opencode` are directory links, so unchanged scripts read and write the service workspace.

## Consistency gate (mandatory, blocking)

For EVERY service with Sparx, WITH or WITHOUT Swagger, review all selected
target attachments. Swagger never waives this requirement. On OpenAPI runs and
resumes (including legacy authorities without `contractMode`), a current
`sparx-attachments.yml` inventory and semantic review bound through
`reviewedAgainst.attachmentsSha256` are mandatory. Missing/stale inventory or
unbound review blocks continuation; do not silently authorize legacy workspaces.
The source-only HTTP review binds the same inventory by its artifact hash.

HTTP services explicitly lacking Swagger use checkpoint `inputs.contractMode:
sparx-only`, the separate evidenced `sparx-http-contract.yml`, and
`consistency/sparx-only-review.yml` (see `docs/sparx-only.md`). The gate reports
`comparison: not-applicable-no-swagger`, never a passed Swagger audit or a batch
classification. Current source/attachment hashes, semantic review, no unresolved
indispensable gaps and explicit scoped resume authorization remain mandatory.

Stage 2A adds proposal-only decision requests and deterministic contexts via
`workspace_cli.py decision-request-{create,list,show,context,status,stale}`;
see `docs/decision-requests-v1.md`. These commands never authorize, resolve a
finding, refresh a checkpoint or clear a gate. Legacy approval commands retain
their behavior: **H-02 remains open**, pending an authentic approval boundary in
2B. Hashes and approver-name strings do not prove human identity.

For an explicitly selected non-HTTP batch archetype, `batch_gate.py` reports
`comparison: not-applicable-non-http-batch` (not a successful Swagger audit). It verifies
the selected archetype, workspace identity, resolved Sparx authority, live source hashes,
equality of the normalized Sparx batch IR with service-spec, a bound semantic review
with no pending findings, and the existing explicit human resume authorization.
An OpenAPI artifact in that workspace blocks; relabeling an HTTP service cannot clear
the gate. The batch contract is documented in
`../materialize-full-service/docs/batch-shell-contract.md`.

For an explicitly selected BFF archetype (`jar-springboot3-webmvc-webclient-bff`) that has no Sparx export and no OpenAPI of its own, `bff_gate.py` reports
`comparison: not-applicable-bff-no-sparx` (never a fabricated audit). The sources are the consumed backend contracts (normalized by `parse-openapi` into
`backend-contracts/*.openapi-spec.yml`) and the user-authored `bff-contract-definition.yml` (literal endpoint list + backend mapping + explicit omissions).
The gate verifies the archetype profile, that the normalized contracts are current with their live `input/contracts` sources, that every mapping is found in its
backend contract (`reconcile-service-spec/scripts/bff_source.py`), that an existing `service-spec.yml` equals the deterministic derivation, that no Sparx/OpenAPI
artifact would be silently ignored, a bound semantic review (`consistency/supplemental.yml`, `reviewedAgainst` = definition/backend/archetype hashes, `findings: []`) and the
existing explicit resume authorization. The BFF is detected from the checkpoint archetype, not from a label inside an artifact.

Statuses: `NO_AUDIT`, `SEMANTIC_REVIEW_PENDING`, `BLOCKED_BY_INCONSISTENCIES`, `AWAITING_AUTHORIZATION`, `CLEARED`. Checkpoint statuses mirror them
(`BLOCKED_BY_INCONSISTENCIES`, `CONSISTENCY_REVIEW_PENDING`, `AWAITING_RESUME_AUTHORIZATION`). Blocks: every verified contradiction, every documental
difference, unverified `comportamiento-no-especificado`/`verificacion-pendiente`. Does not block: internal-to-one-source, non comparable sources, discarded false
positives. Release requires, per item, an approved human resolution bound to the item's fingerprint (`gate-resolve`; machine approvers rejected; may cite an
existing human decision), the agent's semantic review of prose against the current sources, and the user's explicit authorization bound to the evaluation hash
(`gate-authorize`). `check_cleared` recomputes everything from the files and live sources each time; `enter_phase`, `run`, and the guard inside the consolidation,
parameter, planner and materializer scripts refuse otherwise. Never choose between Sparx and Swagger automatically.

Flow: analyze -> authority -> `gate-evaluate` -> (semantic review -> re-evaluate) -> blocked? ask the user, record answers, authorize -> `resume` -> consolidation -> planning -> generation.

## Migration (copy only)

`workspace_cli.py migrate-archive <service> <archive-dir>` after verifying the archive belongs to that service (all identifiable artifacts agree); `migrate-root` copies the
root `.factory/` artifacts of the active service that can be tied to it. Sources are never modified or deleted; a different destination file aborts; the migrated checkpoint
is `legacy-migrated` with the gate NOT_EVALUATED and no invented phases or decisions.

## File protection

`file_protection.py` classifies existing output files (generated-unmodified, user-modified, untracked, user-owned, excluded) using the hashes of the generation manifest;
manual content is preserved and replaced only with an authorization bound to its exact content (`protect-authorize`). A difference from the archetype is not an error.
`application*.properties` is excluded: never read, reported, compared or written, and it never blocks.

## Materialization

`workspace_cli.py materialize <service>` runs the deterministic FULL materializer (skill `materialize-full-service`) after re-checking the gate; it is registered as a post-gate skill.

## Tests

`python -m unittest discover -s .opencode/skills/service-workspace/tests` (synthetic fixtures; no live service required).
