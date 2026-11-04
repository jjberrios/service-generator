# Decision requests and contexts v1 — stage 2A

**Proposal only. H-02 remains open.** Requests, classifications, recommendations,
hashes and CLI output never authenticate humans or authorize anything. Legacy
`gate-resolve`, `gate-authorize`, `protect-authorize` and existing approvals retain
their behavior. No new file is consumed by the gate, planner or materializer.
2B must replace the legacy trust boundary atomically, not enable another trusted
path alongside it. No migration or reattestation occurs in 2A.

## Context contract

`decision_context.build(repo, service, purpose)` produces schemaVersion 1,
kind `decision-context`, and contextId: SHA-256 of canonical JSON, UTF-8, sorted
object keys, LF, excluding contextId itself. It binds:

- Repository location digest (**untrusted**, local identity only; relocation or
  cloning changes the context), service and purpose.
- Explicit archetype/version, profile from the existing read-only adapter,
  technical and documentation fingerprints.
- Canonical fingerprints of normalized OpenAPI, Sparx authority/detail/spec,
  service-spec, prior reviewed decisions/resolutions/coverage and semantic reviews.
- Live raw hashes of OpenAPI, input source bindings, cited Sparx pages
  (`page`/`pagePath`) and the current `js/data/*.xml` hierarchy inventory.
  Missing cited files have null hashes; hierarchy additions invalidate.
- Findings from the non-persisting gate evaluation, review content, prior
  decisions and audit availability. Batch retains
  `not-applicable-non-http-batch`; no HTTP audit is invented.

Excluded: checkpoint status/runId/timestamps, gate output, legacy resume
authorization, future plans, parameters, output/validation reports, requests,
caches and local `application*.properties`. Selection still checks plan/parameter
declarations for conflicts. Relevant artifact changes can invalidate
conservatively (including readiness fields in service-spec). YAML formatting
alone does not invalidate artifacts; raw source/archetype comments do.

This is an artifact-declared closure, NOT proof of exhaustive Sparx interpretation.
The reused evaluator may use its own temporary directory, but `persist=False`
never writes the service workspace/gate/checkpoint. Unavailable audit is explicit,
not a cleared gate. Analysis requests may precede conflict resolution.

## Proposal input

CLI input is workspace-relative YAML with unique keys and only these fields:

```yaml
schemaVersion: 1
purpose: clarify-analysis
decisions:
  - key: inspect-validation
    classification: analysis-required
    problem: Confirm the authoritative validation rule.
    findingFingerprints: []
    evidence:
      - path: sparx-authoritative-endpoint-detail.yml
        pointer: /operations/0
        summary: Documented validation activity.
    alternatives:
      - id: inspect
        description: Expand the cited analysis.
        effects: [No approval and no generation.]
      - id: ask
        description: Request missing documentation.
        effects: [Analysis remains incomplete.]
    recommendation:
      alternativeId: inspect
      rationale: The cited activity is available.
      evidenceIndexes: [0]
```

Purposes: `resolve-findings`, `clarify-analysis`, `technical-choice`,
`authorize-operation`. These label scope; none invokes an operation.

Classifications are declared by the caller, not inferred by a classifier:

| Value | Meaning | Effect in 2A |
|---|---|---|
| agent-technical | Technical choice within existing approved conventions | Representation only; no expanded autonomy |
| analysis-required | Further analysis needed | Does not automatically request approval |
| human-functional | Functional/source decision requiring a human | Current finding fingerprint required; no approval |
| explicit-authorization | Request for permission | Does not grant permission |

Require 1–100 decisions with unique slug keys, nonempty problem/evidence/
alternatives/effects, unique alternative IDs. Evidence paths must be allowlisted
context artifacts or context sources, with pointer and summary. Recommendations
are optional and reference an existing alternative and evidence indexes.
The engine validates structure/binding, **not semantic truth** of summaries,
validity of business alternatives or independence of prose questions. Those
remain review responsibilities. Never invent alternatives, recommendations or
findings to fill the format. Unknown findings/approval fields fail.

## Storage, grouping and freshness

`decision_requests.create` writes only
`.factory/services/<service>/decision-requests/request-<sha256>.yml`.
Stored fields: schemaVersion, kind `decision-request`, authority `none`, service,
purpose, embedded context, decisions and requestId. Individual decisionId binds
its entire decision and context. Decisions are sorted by key: group order is
immaterial. Adding a question changes requestId but preserves other individual
IDs. Editing one changes its ID. No group approval is possible. Evidence and
alternative order intentionally affect content identity.

A unique temporary file and exclusive hard-link publication avoid overwriting
existing content. Identical repeats reuse bytes; modified requests are preserved
and rejected. Filesystems without hard-link support fail explicitly, with no
unsafe fallback. Stored IDs are rechecked on read, but a self-consistent forged
hash is not authenticity.

Freshness is computed without mutations: `current`, `stale`, `unavailable`
(cannot rebuild context), or list row `invalid` (malformed stored file). Keep
history unchanged; create a new request for a changed context. No status grants
authority, even when current.

## CLI

Prefix with `python -B .opencode/skills/service-workspace/scripts/workspace_cli.py`:

```text
decision-request-create <service> --proposal <workspace-relative.yml>
decision-request-list <service>
decision-request-show <service> <request-id>
decision-request-context <service> --purpose clarify-analysis
decision-request-context <service> --request <request-id>
decision-request-status <service> <request-id>
decision-request-stale <service>
```

All print YAML. Only create writes a request. `context --request` shows the
historical embedded context; `--purpose` computes the current one. Status exits
0 for current, 4 for stale/unavailable; malformed input/errors exit 3. List/stale
exit 0 with per-row errors. Stale lists all non-current rows, including
invalid/unavailable. None refreshes a gate/checkpoint or resumes generation.

## Security limits and 2B

Shared safe-path checks reject traversal, absolute paths, ADS, protected
configuration and redirected request/source paths. This is not an OS sandbox:
same-identity arbitrary execution can replace files/runtime between checks.
Hashes, CLI flags and names cannot authenticate humans with that trust model.
2B needs an external protected approval ledger, separate approver identity,
trusted runtime/imports and verification binding each choice/effect to the exact
context. Re-evaluate v1 closure for that stronger use; these proposal IDs are not
ready-made security tokens. Preserve checkpoints, the mandatory consistency gate,
FULL feasibility and manual-file protection.
