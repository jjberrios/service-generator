# Question policy and lifecycle states (v1)

Implementation: `scripts/lifecycle.py` (`decide`, `group_questions`, `find_decision`, `archetype_lifecycle`,
`service_lifecycle`); command `workspace_cli.py lifecycle <service>`. Tests: `tests/test_lifecycle.py`.

## When to ask

| Situation (`kind`) | Action | Ask the user |
| --- | --- | --- |
| `reference-evidence-clear` | apply and cite the evidence | no |
| `technology-absent-in-reference` | record `not-present-in-reference`; never offer another stack | no |
| `decision-already-approved` | reuse the approved decision of the same target/version | no |
| `request-covers-phase` | proceed; the request already authorizes the phase | no |
| `unsupported-backend` | technical failure and stop (engineering work, not a business choice) | no |
| `source-conflict` | stop the affected behavior | yes |
| `required-parameter-missing` | one grouped question for all missing parameters | yes |
| `intentional-deviation` | approval scoped to this target/version | yes |
| `gate-release` | human authorization bound to the current evaluation hash | yes |
| `source-evidence-clear` | apply the owning contract/Sparx/attachment fact and cite it | no |
| `analysis-incomplete` | finish target-local investigation, including attachments | no |
| `technical-convention` | choose and record a consistent internal engineering convention | no |
| `supported-service-extension` | plan an evidenced, compatible addition supported by the backend | no |
| `environment-configuration` | externalize runtime values using supported profile conventions | no |
| `functional-evidence-missing` | group indispensable facts still absent after analysis | yes |

## Technical autonomy protocol

Every specialist follows this policy. The orchestrator owns user questions: return
structured issues to it rather than asking independently at each phase.
Before asking, search the selected contract, Sparx branch and all its attachments,
then the selected versioned archetype and same-target approved evidence. Do not
reanalyze the reference project. An absent archetype helper is not automatically
an absent business requirement: plan compatible service additions with evidence,
`justification` and `requiredBy`, preserving the baseline. Do not silently change
persistence technology, public routes, SQL, status codes, validations or business
rules. Internal names can be chosen; public names must be sourced. Source absence
after complete investigation may require a question, but unfinished analysis does not.

Before expensive semantic interpretation, run `workspace_cli.py capability-check
<service>` after persisting the selected archetype. It checks profile support
without consuming reviews or clearing the gate. It does NOT prove component support:
run the existing full `preflight` after planning. A failure is a technical report,
never a question asking permission to pretend FULL generation succeeded.

For issue routing, prepare a workspace-local YAML `issues: [...]` with `kind`,
`key`, evidence references and affected scope; run `workspace_cli.py question-triage
<service> --input <workspace-relative.yml>`. It returns autonomous actions and
deduplicated questions. For `supported-service-extension`, include `evidence`,
`compatibleWithArchetype: true`, `backendSupported: true` only after checking actual
capabilities. Missing evidence routes to analysis; missing compatibility/support
routes to technical failure. These flags are routing metadata, not evidence,
approval, readiness or permission to write unsupported output.

Ask only after autonomous actions are exhausted, grouping all currently known
blockers in one message. Describe evidence checked, why each fact is indispensable
and a source-backed recommendation when available. Do not re-ask unchanged issues
or seek per-phase confirmation already covered by the generation request. Runtime
credentials/URLs are external configuration, never guessed and never requested for
static generation when the selected profile supports externalization.

Persist engineering choices in existing planning artifacts with rationale, not in
human approval records. Reuse unchanged source/artifact hashes at phase boundaries;
never skip live currency checks, semantic review, resume approval or file protection.

Duplicates (same kind and key) are asked once. `find_decision` only returns a human-reviewed, non-machine decision whose
`scope` is exactly the requested one: decisions of another target or version are never reused. Gates are not weakened: an
independent stage request is not an authorization for later stages, and a full-generation request covers only the bounded
necessary target-local analysis, attachment review, slicing and interpretation as
well as consolidation/planning/static validation. Do not ask for a second stage
confirmation inside that bounded request. It does not cover global interpretation,
Maven, database access, deployments, overwrites or review/resume authorizations.
Explicit delegation may record only finding/resume reviews through the approved
writer with the verbatim statement; overwrite/historical reattestation stay manual.
Never substitute a technical choice or cached artifact for a current gate/review.

## Lifecycle states (never collapsed into "ready")

Archetype: `extracted`, `approved`, `frozen`, `generationEnabled`, `backendImplemented`,
`serviceGenerationAuthorizedForConcreteTargets`, `runtimeVerified`. Values are `yes`, `no` or `unknown` (a legacy manifest
without flags stays `unknown`). `frozen` and `generationEnabled` are independent, and neither implies a working backend or an
authorized target.

Service: `archetypeSelected`, `gate`/`gateCleared`, `specConsolidated`, `planned`, `materialized`, `functionallyComplete`
(`yes` only when the report says `complete` and the specification declares no limitations; otherwise `partial`),
`declaredLimitations`, and the tools `maven`, `compilation`, `tests`, `jacoco`, `checkstyle` (`not-applicable` when the
archetype says so) plus `runtime`. A tool is `yes`/`no` only with an explicit result in `validation-evidence.yml`;
otherwise `not-verified`. An unreadable workspace reports its gate as `unevaluable`, never as cleared.
