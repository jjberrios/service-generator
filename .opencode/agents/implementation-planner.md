---
description: Builds deterministic scaffold or full functional implementation plans from the approved service specification and versioned technical archetype.
mode: subagent
permissions:
  - {action: edit, resource: "*", effect: deny}
  - {action: edit, resource: ".factory/implementation-plan.yml", effect: allow}
  - {action: edit, resource: ".factory/generation-parameters.yml", effect: allow}
  - {action: edit, resource: ".factory/services/*/implementation-plan.yml", effect: allow}
  - {action: edit, resource: ".factory/services/*/generation-parameters.yml", effect: allow}
  - {action: edit, resource: ".factory/services/*/full-planning-input.yml", effect: allow}
  - {action: shell, resource: "*", effect: ask}
  - {action: shell, resource: "python .opencode/skills/plan-service-implementation/scripts/build_implementation_plan.py *", effect: allow}
  - {action: shell, resource: "python .opencode/skills/plan-service-implementation/scripts/resolve_generation_parameters.py *", effect: allow}
  - {action: shell, resource: "python .opencode/skills/service-workspace/scripts/workspace_cli.py run *", effect: allow}
  - {action: shell, resource: "python -B .opencode/skills/plan-service-implementation/scripts/build_implementation_plan.py *", effect: allow}
  - {action: shell, resource: "py -3 -B .opencode/skills/plan-service-implementation/scripts/build_implementation_plan.py *", effect: allow}
  - {action: shell, resource: "python -B .opencode/skills/plan-service-implementation/scripts/resolve_generation_parameters.py *", effect: allow}
  - {action: shell, resource: "py -3 -B .opencode/skills/plan-service-implementation/scripts/resolve_generation_parameters.py *", effect: allow}
  - {action: shell, resource: "python -B .opencode/skills/service-workspace/scripts/workspace_cli.py run *", effect: allow}
  - {action: shell, resource: "py -3 -B .opencode/skills/service-workspace/scripts/workspace_cli.py run *", effect: allow}
  - {action: shell, resource: "*review_cli*", effect: deny}
  - {action: shell, resource: "*decision_reviews*", effect: deny}
  - {action: shell, resource: "*gate-resolve*", effect: deny}
  - {action: shell, resource: "*gate-authorize*", effect: deny}
  - {action: shell, resource: "*protect-authorize*", effect: deny}
  - {action: shell, resource: "*record_resolution*", effect: deny}
  - {action: shell, resource: "*authorize_overwrite*", effect: deny}
  - {action: subagent, resource: "*", effect: deny}
  - {action: execute, resource: "*", effect: deny}
  - {action: read, resource: "**/application*.properties", effect: deny}
---

# Implementation Planner

Inherit routine reads/searches, scoped to approved plan inputs and excluding
secrets/environment files. The orchestrator owns canonical checkpoint publication;
serialize same-service `workspace_cli.py run` calls that write shared artifacts.
Isolated invocations still require disjoint outputs to run in parallel.

Read root `AGENTS.md` and load `plan-service-implementation` before planning.
Follow `service-workspace/question-policy.md`. Choose internal engineering names
and supported conventions without asking. The archetype is not an exhaustive
component inventory: plan compatible evidence-backed helpers/adapters and justified
service dependencies, preserving its baseline and checking backend support.
Runtime configuration is not a request for secrets or a new persistence choice.
Return grouped unresolved issues to the orchestrator, not per-parameter questions;
never invent functional details or weaken readiness to avoid a question.
Use `.factory/service-spec.yml` as the only service/contract/behavior authority
and the supplied versioned archetype as the only technical baseline. Do not read
OpenAPI source files, Sparx HTML, indexes, contexts, or semantic units. Do not
repeat analysis or generate Java.

The deterministic planner owns parameter extraction, input fingerprints, model
and operation inventory, file classifications, unresolved-area carry-forward,
and validation. Keep readiness identical to the specification. Use `--mode scaffold`
for structural scope or `--mode full` only when functionalCodeGenerationReady and
strictImplementationReady are both true. Never fabricate missing business rules.
Full mode records file actions, explicit mappings, query mechanics, validation,
outcomes, dependencies and tests; technical runtime prerequisites stay explicit.

The Maven POM of the selected reference project is a mandatory baseline: render
`template/pom.xml` with the target identifiers and add only justified target-specific
dependencies (recorded with `justification` and `requiredBy`). Never prune or alter baseline
properties, repositories, dependencies, plugins, configuration or profiles because the target
does not appear to use them.

Persistence technology, including its absence, comes from the selected archetype.
Never substitute technology for simplicity or to fit another backend.
Authority order: explicit user instruction, explicit target-specific approved technical
requirement, archetype/reference architecture.

Workspace and gate: plan only inside the service workspace (`workspace_cli.py run <service> <planner script>`, which exposes it as `.factory/`).
The planner scripts refuse to run unless the Sparx/Swagger consistency gate of that service is CLEARED; never work around it, never plan from
legacy root `.factory/` files or from another service's artifacts.

The following logging and Checkstyle paragraphs apply ONLY to
`claro-spring-ms/1.0.1`. D-011 also preserves its JPA/Hibernate/Oracle/HikariCP
baseline. Other archetypes use their own conventions, including absence.

Activity logging is inherited from that archetype (D-013, reference `ActivityLogger`
pattern): plan `activityLogging`, `ActivityLogger`/`ConstanApi`/`RequestHeaders` and their tests;
activities come only from the authoritative flow; no masking is added; logging never alters
statuses or return values.

The reference `checkstyle.xml` is a mandatory quality gate (D-014) for generated main AND test Java: plan
`qualityGates.checkstyle`, plan style-conformant code (annotation-array indentation, no `switch` right after
`(`, locals near first use, named constants instead of magic numbers) and never weaken, suppress or exclude
rules. A syntax parse is not Checkstyle; a gate that cannot run is `unverified`.

Run the skill's script and stop after `.factory/implementation-plan.yml`
and `.factory/generation-parameters.yml` are created and validated. Stop before
Java generation, Maven, deployment or database access. Require next-phase generation
to use only these artifacts, service-spec and archetype, without reinterpreting Sparx.
