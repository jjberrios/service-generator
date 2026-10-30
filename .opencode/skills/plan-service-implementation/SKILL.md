---
name: plan-service-implementation
description: Deterministically plans scaffold or full functional service implementation, file actions, mappings, tests and generation parameters from service-spec.yml and a versioned archetype.
---

# Plan Service Implementation

All profile planners use the shared versioned declared-inventory archetype
fingerprint and atomic artifact writer (`service-workspace/scripts/artifact_integrity.py`).
Old all-tree fingerprints are stale and require replanning against reviewed inputs;
do not refresh stored hashes or modify baseline decisions to bypass validation.

Read repository-root `AGENTS.md` first. The authoritative service input is
`.factory/service-spec.yml`; the selected versioned archetype is the technical
baseline. Never consult raw OpenAPI or Sparx inputs, Sparx indexes/contexts, or
semantic units. Do not rerun analysis/reconciliation and do not generate code.

Select mode explicitly; default is `scaffold`. Preserve service-spec readiness.
Scaffold requires `scaffoldImplementationReady == true`. Full requires both
`functionalCodeGenerationReady == true` and `strictImplementationReady == true`,
with no unresolved business requirement. Never upgrade readiness during planning.

The planner deterministically inventories active operations, contract schemas,
template files, archetype parameters, traceability, and unresolved evidence. It
plans contract-facing interfaces and DTOs plus permitted archetype technical
files in scaffold mode; unresolved functional files are explicitly classified
`omit-unresolved`. Full mode includes specified functional behavior only.
Missing required technical parameter values are planning blockers, never guessed.

Run from repository root:

```text
python .opencode/skills/plan-service-implementation/scripts/build_implementation_plan.py
```

The script writes `.factory/implementation-plan.yml` deterministically. Run it
twice on unchanged inputs and compare SHA-256. Validate that active and inactive
operations remain correctly separated, every planned model cites a service-spec
schema, no unsupported persistence/integration/business artifact is planned,
and all unresolved work is carried forward. Stop after the plan and parameters;
do not generate Java.

## Full functional planning

For JDBC/WAR use the closed evidence-backed contract in
`../materialize-full-service/docs/jdbc-binding-v1.md`. The normalized operation
must contain `jdbcBinding` v1 and the planning input must supply
`technical.jdbcNames`. Never infer procedure order, cursor, row destination,
response codes or target-specific partial-operation behavior. Missing or
unsupported data is an explicit technical planning error; no legacy target
decisions are automatically applied to another service.

### Non-HTTP batch profile

`batch-shell-jar-spring-xml-log4j-sftp-junit4` dispatches to `batch_shell_plan.py`.
It consumes the evidence-bound `service-spec.yml#/batch` IR and the selected archetype,
not OpenAPI or reference sources. It never upgrades readiness or enables the archetype.
Its closed schema, explicit parameters, supported SFTP steps and non-HTTP gate are
documented in `../materialize-full-service/docs/batch-shell-contract.md`.
The JPA/Checkstyle/ActivityLogger requirements below apply to their own legacy profile,
never to batch. `resolve_generation_parameters.py --mode full` uses the same dispatcher.

```text
python .opencode/skills/plan-service-implementation/scripts/build_implementation_plan.py --mode full --planning-input .factory/full-planning-input.yml
```

The generic `full_implementation_plan.py` backend consumes the consolidated
`service-spec.yml` and the approved archetype. A planning input supplies target
package/class names, non-secret connection coordinates and explicit technical
choices; it must not add business rules. The stale plan is never a behavior input.
Prior approved parameter values may be reused from the pre-phase archive.

Full planning inventories existing output (without modifying it), gives every
file create/update/retain/remove semantics, dependencies and ordering, and
embeds effective operation, column, mapping, outcome and test matrices. It
distinguishes absent JSON fields from explicit null, preserves effective contract
amendments, and records runtime database prerequisites separately from source
generation readiness. Never infer sequence names, ID algorithms or extra layers.

### Legacy adapter: claro-spring-ms/1.0.0 only

The D-012/D-014/D-013/D-011 requirements below belong only to this baseline.
Other selected archetypes retain their own POM, persistence, logging and quality
conventions, including absence. Unsupported capabilities are technical errors,
never a request to adopt the legacy stack. Workspace gates apply to every profile.

**The reference POM is the mandatory Maven baseline (D-012).** `template/pom.xml` is the
approved reference project's `pom.xml` with only declared substitutions
(`archetype.yml#/maven/reference_pom_baseline`). Full planning renders it with
`scripts/pom_baseline.py` (group id, artifact id and name, version, application class,
base-package path) and plans `pom.xml` as `update` only when the current file differs from
that rendering (`expectedSha256`). Parent, properties, repositories (`repository-url`),
all dependencies with reference scopes/versions, build plugins and configuration, quality
configuration and profiles may never be pruned or altered because a target seems not to
use them. Only justified target-specific dependency additions (planning input
`technical.maven_additions`, each with `justification` and a planned `requiredBy`
component) are rendered after the baseline. Validation must produce the machine-readable
baseline comparison (inherited, parameterized, target-specific addition, intentionally
excluded) and fail on any missing, modified or unjustified item.

**Workspace and consistency gate:** planning runs inside a service workspace (`workspace_cli.py run <service> <script>`); `build_implementation_plan.py`, `resolve_generation_parameters.py` and the materializers exit 3 unless the Sparx/Swagger consistency gate of that service is CLEARED. Prior approved engineering values come only from that workspace's `generation-parameters.yml` (a new service starts from the archetype); no `archive/` dependency.

**Checkstyle is a mandatory quality gate (D-014):** the plan must contain `qualityGates.checkstyle` (built by
`checkstyle_gate`/`checkstyle_gate.py`: reference `checkstyle.xml` hash, sources `src/main/java` and `src/test/java`,
no suppression/exclusion/weakening, applies to every planned main and test Java file, `unverified` when not
executable). Plan generated Java to satisfy the complete reference configuration, avoiding the known patterns:
annotation-array children not at indentation 6/12, `switch` expression directly after `(`, locals declared more than 3
statements before first use, and numeric literals outside the configured ignore list (use constants named by
meaning, also in tests). Fail closed if the archetype does not declare the gate.

**Activity logging is inherited from the approved archetype (D-013):** the plan must contain an
`activityLogging` section (derived by `activity_logging_plan`: transaction header role,
`RequestHeaders` components, activity constants from the authoritative flow, per-operation
request/body/error logging, no masking) and plan `utils/ActivityLogger`, `utils/ConstanApi`,
`dto/request/RequestHeaders`, `ActivityLoggerTest` and the activity-logging test. Files that
change because of logging (`logging_dependent`) are `update` until the manifest carries
`activityLogging.decision: D-013`. Fail closed when no transaction header can be derived.

**Persistence technology is inherited from the approved archetype (D-011):**
Spring Data JPA, Hibernate, Oracle and HikariCP, exactly as the approved reference
project uses them (`archetype.yml#/persistence`, `conventions.md`). The planner may
not select plain JDBC (NamedParameterJdbcTemplate, SQL builders, RowMapper) or any
other technology because it is simpler or preferred. Authority order: (1) explicit
user instruction, (2) explicit target-specific approved technical requirement,
(3) the archetype/reference architecture. A planning input that names another
technology without such an override fails with a planning error; an authorized
override still fails closed until a backend for it is implemented explicitly.

Current backend: JPA for one explicitly specified Oracle relational table, with
select/insert/update actions: `@Entity` in the model package, a repository extending
`JpaRepository` (plus `JpaSpecificationExecutor` only for specified dynamic filters),
reference audit-timestamp and exception conventions, and an `application.properties`
rendered from the archetype template (reference blocks; SUBTYPES IDF excluded). The
backend chooses actions from literal specified persistence behavior, never HTTP
methods, branch directory names or target-specific fields. Existing output is
inventoried: files written by an earlier persistence technology are planned as
`update` or `remove`, never silently retained; IDE metadata is ignored.

`resolve_generation_parameters.py --mode full` dispatches to the same full backend.
The next generator may consume only implementation-plan, generation-parameters,
service-spec and archetype; planning inputs are copied into the plan/parameters,
and raw Sparx must not be read. No Java, Maven, deployment or database connection
is performed during planning.

For Phase 5.1 parameter-only refinement, run:

```text
python .opencode/skills/plan-service-implementation/scripts/resolve_generation_parameters.py
```

This deterministic refinement reads the current implementation plan, approved
service spec, and archetype metadata/template files; it writes
`.factory/generation-parameters.yml` and updates file-level parameter readiness
in `.factory/implementation-plan.yml`. It does not generate source or deployment
resources and does not modify the service spec or archetype.
