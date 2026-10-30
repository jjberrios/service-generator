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

Duplicates (same kind and key) are asked once. `find_decision` only returns a human-reviewed, non-machine decision whose
`scope` is exactly the requested one: decisions of another target or version are never reused. Gates are not weakened: an
independent stage request is not an authorization for later stages, and a full-generation request covers only the bounded
phases it names.

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
