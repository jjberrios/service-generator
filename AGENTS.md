# Service Generator

## Purpose

This repository generates new Java/Spring microservices from:

- a reusable corporate microservice archetype
- an OpenAPI/Swagger contract
- Sparx Enterprise Architect HTML exports

The reference project is used only to extract and version the reusable archetype.
It must not be re-analyzed for every generated service.

## Repository Structure

- `input/reference/`
  Contains reference projects used to extract an archetype.

- `input/contracts/`
  Contains OpenAPI/Swagger specifications.

- `input/sparx/`
  Contains Sparx Enterprise Architect HTML exports.

- `archetypes/`
  Contains versioned reusable archetypes.

- `.factory/`
  Contains intermediate generated specifications and analysis artifacts.

- `.opencode/agents/`
  Contains OpenCode agents.

- `.opencode/skills/`
  Contains reusable agent skills.

- `output/`
  Contains generated microservices.

## Current Archetype

The initial archetype is:

`archetypes/claro-spring-ms/v1.0.0`

It is extracted from:

`input/reference/ms-individual`

The reference project is a source for architecture and engineering conventions only.

Do not copy business-specific implementation from the reference project into the
archetype.

Examples of business-specific content that must not become part of the archetype:

- Individual entities
- Individual repositories
- Individual-specific endpoints
- biometric business rules
- project-specific database tables
- project-specific DTOs

## Source Responsibilities

### Archetype

Defines:

- Java and Spring Boot baseline
- project structure
- package organization
- build conventions
- dependency baseline
- testing conventions
- quality tooling
- approved technical baselines
- reusable deployment patterns

### OpenAPI

Defines the external API contract:

- HTTP methods
- paths
- headers
- request parameters
- request schemas
- response schemas
- HTTP status codes
- declared validations

### Sparx

Defines functional and integration behavior:

- business flows
- processing steps
- integrations
- decisions
- persistence interactions
- error conditions
- sequencing
- explicit diagram lifecycle/status legends and mappings when source-observable

Lifecycle state must come from an explicit status/tagged value or a visual
mapping grounded in an explicit Sparx legend/equivalent metadata. Never infer a
state from color alone. Preserve the literal state and source evidence; an
explicit inactive state remains historical evidence and is not active contract
behavior.

## Generation Principle

New services must be generated from:

Archetype + OpenAPI + Sparx

The reference project must not participate in normal service generation once the
archetype has been extracted and approved.

### Generation Readiness

Readiness has two distinct gates:

- `strictImplementationReady` means the active contract and required behavior,
  mappings, persistence, and integrations are sufficiently specified, with no
  unresolved blocker requiring invented behavior. `implementationReady` remains
  an alias of this strict gate.
- `scaffoldImplementationReady` means a compile-oriented structural scaffold can
  be generated using only the complete active contract, approved archetype-owned
  technical conventions, and evidence-backed behavior, while explicitly omitting
  unresolved functional implementation. It does not mean the service is
  functionally complete.

Scaffold readiness requires a complete contract, known active operations,
inactive operations excluded from generation, an available approved archetype,
and explicit representation of unresolved behavior. The generation path must
support omitting unresolved behavior. If any condition is not established, the
scaffold gate is false.

The safe scaffold scope may include archetype-owned build/project/package
structure, bootstrap/configuration/logging/security/deployment baselines,
contract-derived API interfaces and DTOs, declared contract validation and error
shapes, and empty contract-level test skeletons. Concrete operation behavior,
ports, mappings, repositories, entities, persistence, clients, SQL, and business
tests are excluded unless their existence and semantics are evidence-backed.
Unresolved areas must remain explicit in readiness and any later implementation
plan; they must not be hidden behind placeholders that imply behavior.

## Conflict Handling

Do not invent behavior when sources conflict.

When a conflict exists:

1. identify the conflicting sources
2. describe the conflicting values
3. stop generation for the affected behavior
4. request clarification

## Safety

Do not modify files inside `input/reference/`.

Do not overwrite an existing archetype version during initial extraction.

Do not modify generated services outside the configured output directory.

Do not commit, push, reset, clean, or alter Git history unless explicitly requested.

## Archetype Governance

Versioned archetypes are maintained under:

`archetypes/`

Each approved archetype version is a persistent generation baseline.

A versioned archetype may contain:

- `archetype.yml`
- `conventions.md`
- `generation-rules.md`
- `decisions.md`
- `template/`

### Human Decisions

Ambiguities discovered while extracting an archetype must not be resolved
silently by an agent.

Human-approved archetype decisions must be recorded in the corresponding:

`archetypes/<archetype>/<version>/decisions.md`

Approved human decisions take precedence over automatic inference from the
reference project.

Agents must preserve approved decisions unless the user explicitly supersedes
them.

A decision approved for one archetype version must not automatically be applied
to another version.

Temporary decisions must be identified as temporary and may be reconsidered in
future archetype versions.

### Reference-Based Extraction Policy

Each archetype is extracted from its own explicitly selected reference project.
Its technical baseline must reflect that project, not the stack of another
archetype or a technology hardcoded in agent instructions. This applies to
runtime, frameworks, build, persistence, logging, tests, quality tooling,
repositories, packaging and delivery.

- Preserve the reference Maven POM baseline: parent, properties, dependency
  management, dependencies, versions, scopes, repositories, plugins, executions,
  quality configuration and profiles. Inventory all declared dependencies and
  identify observed use separately. Do not prune dependencies, modernize versions
  or correct scopes silently. Parameterize service/environment identity and
  exclude secrets and domain-specific content, documenting each transformation;
  do not copy business exclusions as generic quality rules.
- Use the persistence mechanism actually implemented by the reference. Do not
  introduce JPA, Spring Data repositories, entities, Hibernate, HikariCP or any
  other mechanism merely because another archetype uses them. A dependency
  declared in the POM is not proof of an implemented persistence pattern; keeping
  that dependency does not authorize generating such a pattern. Concrete SQL,
  tables, repositories and integration behavior remain specification-owned.
- Extract only the reference's reusable logging structure and conventions. Do
  not impose ActivityLogger, RequestHeaders records or an adaptation from another
  project. If logging is absent, do not add it. Do not copy business activities,
  payloads or validation logic as technical logging utilities. Record observable
  logging risks without silently changing the reference behavior.
- Include Checkstyle only when the selected reference uses it. Preserve the
  observed configuration and scope; do not invent a plugin, ruleset or mandatory
  scope borrowed from another archetype. If it is absent, mark it
  `not-applicable` / `not-present-in-reference`, never `passed` or an unexecuted
  mandatory gate. If it is required but cannot be executed, mark it `unverified`.
  Apply the same evidence-based inclusion principle to other quality tools.
- Runtime, packaging, repository support and delivery conventions come entirely
  from the selected reference. Parameterize variable values and retain explicit
  external prerequisites. Do not replace WAR/WebLogic with a different runtime,
  invent missing tool/server versions or claim the behavior of an unavailable CI
  library. Missing evidence remains unknown or unverified, not an implicit
  approval or a reason to import another stack.

These rules govern new extraction and explicitly authorized revisions. Existing
approved versions and their decisions remain unchanged unless the user requests
their revision. An intentional deviation from a reference needs an explicit
decision recorded for the target version. Static extraction validation does not
prove compilation, runtime compatibility or support by a service materializer.

### Decision Precedence

For archetype extraction and revision, use this precedence:

1. Explicit current user instruction
2. Approved decision in the target archetype's `decisions.md`
3. Repository policy in `AGENTS.md`
4. Reference-project evidence
5. Agent inference

If an approved decision conflicts with reference evidence, report the conflict
rather than silently changing the decision.

### Archetype Lifecycle

A reference project is analyzed to create an archetype.

Once an archetype has been approved and frozen, normal service generation must
use the versioned archetype instead of re-analyzing the original reference
project.

The reference project should only be revisited when:

- creating a new archetype
- intentionally revising the current archetype
- preparing a new archetype version
- validating provenance or an existing extraction decision

### Version Safety

Do not overwrite an existing archetype version during initial extraction.

An existing version may be modified only when the user explicitly requests a
revision of that version.

Changes that intentionally alter the approved generation baseline may require
a new archetype version instead of silently changing an already frozen version.

### Generation Ownership

Unless explicitly overridden by an approved archetype decision:

- OpenAPI owns HTTP contracts.
- OpenAPI owns request and response schemas.
- OpenAPI owns API-level declared validation.
- Sparx owns business processes and behavior.
- Sparx owns integrations and external service behavior.
- Sparx owns persistence behavior.
- OpenAPI and Sparx jointly determine mappings where contract and business
  behavior interact.

The archetype owns:

- runtime and framework baseline
- project structure
- engineering conventions
- reusable technical configuration
- build tooling
- quality tooling
- approved technical baselines
- reusable deployment patterns

The selected archetype owns these choices through its own reference evidence
and approved decisions, subject to the Reference-Based Extraction Policy above.

### Existing claro-spring-ms / 1.0.0 Decisions

The following approved baselines apply specifically to
`archetypes/claro-spring-ms/v1.0.0`, extracted from `input/reference/ms-individual`.
They are not requirements for other archetypes. Preserve them for this existing
version unless its revision is explicitly authorized:

- the Maven POM baseline: the approved reference project's `pom.xml` (parent,
  properties, repositories, dependencies, plugins, quality configuration, profiles)
  is mandatory (decision D-012); generated services add only justified
  service-specific dependencies and never prune baseline items
- persistence technology: Spring Data JPA, Hibernate, Oracle and HikariCP, as
  defined by the approved reference project (decision D-011). It may be replaced
  only by an explicit user instruction or an explicit target technical
  requirement, never because another technology seems simpler.
- activity logging: the reference `ActivityLogger` pattern (decision D-013):
  `utils/ActivityLogger` and `utils/ConstanApi` from the archetype template,
  a `RequestHeaders` record, the transaction prefix (`[txId] ` or
  `[SIN-TRANSACTION] `), activity start/end markers derived from the
  authoritative flow, controller/service request logging, body logging through
  `logContenido` and the reference business/technical error logging. Logging
  must not change statuses or return values, never invents activities, and
  does not add masking the reference lacks (reported as a review risk).
- generated-code style gate: the reference `checkstyle.xml` (decision D-014) is
  mandatory for BOTH `src/main/java` and `src/test/java`. Generation is not
  complete until Checkstyle reports 0 violations; a Java syntax parse never
  substitutes for it, an unexecutable gate is `unverified` (never `passed`), and
  the rules are never weakened, suppressed or excluded for generated code.

Agents must not invent Swagger- or Sparx-owned behavior when generating or
maintaining the archetype.

## Current Phase

The existing approved reusable generation baseline is:

`claro-spring-ms` version `1.0.0`

Its extraction source is:

`input/reference/ms-individual`

Normal service generation reuses the approved versioned baseline. Do not repeat
archetype extraction or reference-project analysis for each service.

Additional archetypes may be extracted from other user-selected reference
projects under separate names/versions. Their own artifacts and decisions define
their status; creating one does not replace or approve a different baseline.

## Sparx vs Swagger Audit

`.opencode/agents/sparx-swagger-validator.md` (skill `audit-sparx-swagger`) is an independent,
read-only auditor. It reuses `parse-openapi`, `parse-sparx` and `interpret-sparx`, compares the
authoritative Sparx branch with the OpenAPI contract and writes a per-service registry
(`reports/inconsistencias/registros/<service>/findings.yml`) and a Word report
(`reports/inconsistencias/<service>_sparx_swagger.docx`). It never modifies OpenAPI, Sparx, reviewed
decisions, `service-spec` or `.factory/`, never generates Java and never runs Maven, Oracle or
deployments. It is invoked independently of `@service-generator`:

```text
@sparx-swagger-validator
Target service: <service>
OpenAPI: input/contracts/<service>.yml
Sparx: input/sparx/PROYECT/
```

## Service Workspaces and Mandatory Consistency Gate

Each service owns an independent workspace `.factory/services/<service>/` (artifacts, decisions, plan, parameters, checkpoint, validation); processing
another service never archives or overwrites it (skill `service-workspace`, `workspace_cli.py`). Legacy artifacts are recovered by copy only
(`migrate-archive`, `migrate-root`) and migrated work is never gate-cleared.

Before any consolidation, planning, scaffold or Java generation, and on every resume, the Sparx vs Swagger consistency gate must be `CLEARED`. It reuses the
`@sparx-swagger-validator` comparison. Verified contradictions, documental differences and indispensable unverified behavior block with status
`BLOCKED_BY_INCONSISTENCIES`; the agent never chooses between Sparx and Swagger and never invents rules. Release needs explicit approved human resolutions
(bound to the exact finding), the semantic review of the prose, and the user's explicit authorization to resume. A generated audit report authorizes nothing.
Existing approved human decisions are respected and referenced, not reopened unless the sources change or a new conflict appears. The consolidation, parameter,
planning and materialization scripts enforce the gate themselves.

Java for a service is written only by the deterministic FULL materializer (skill `materialize-full-service`, `workspace_cli.py materialize <service>`), which recomputes the consistency gate, protects manual files, writes through `guard_write` and stops on unsupported components; `@service-generator` has no direct edit permission on `output/**`. A generic validator and a preventive style lint exist, but only the actual Checkstyle execution can pass a Checkstyle gate required by the selected archetype (D-014 for claro-spring-ms/1.0.0). An archetype whose reference has no Checkstyle has no such mandatory gate; absence is not a pass.
The following materializer capabilities describe its currently supported technical profile, not requirements to transplant into every extracted archetype. Before using a different archetype, establish backend support for its Java version, templates, persistence and test framework; stop on unsupported profiles instead of rewriting the archetype to match the backend.
For the supported pattern the materializer generates JUnit 5/Mockito tests with a rule traceability register and a static JaCoCo scope report (`tests-traceability.yml`, `coverage-scope.yml`, always `not-verified`); persistence tests need an explicitly authorized test-database dependency.
Declared parameter/DTO constraints are exercised through Bean Validation, audit dates use an injectable `Clock` (system default zone, never SYSDATE), and `coverage-scope.yml` reports tool states honestly (Maven/Checkstyle/JaCoCo never claimed).
The materializer also assembles the archetype technical files into a complete Maven project (`assemble_project.py`; `application*.properties` stays excluded) and `validation_evidence.py` records real offline Maven/Checkstyle/JaCoCo results bound to the exact project hash (stale when it changes; Maven runs only with explicit authorization).

Existing output files modified by hand (or listed as user-owned) are preserved; replacing them needs an authorization bound to their exact content.
`src/main/resources/application*.properties` is local environment configuration: never read, analyzed, reported, compared or overwritten by the generator.

## Service Generation Orchestrator

Use `.opencode/agents/service-generator.md` to coordinate the existing specialized
agents and skills. The orchestrator resumes from
`.factory/service-generation-state.yml`, validates input/artifact hashes, selects
authoritative target-local evidence, pauses only for blocking source/business
decisions, and requires full readiness before functional planning/materialization.
Do not reuse another target's canonical artifacts or reviewed decisions. Archive
previous run state/artifacts before switching the active target; preserve outputs.

Minimal invocation:

```text
@service-generator

Target service:
dom-example-service

OpenAPI:
input/contracts/dom-example-service.yml

Sparx:
input/sparx/PROYECT/

Generate the complete functional service.
```

After a decision or OpenCode restart:

```text
@service-generator
Resume the current service generation from its checkpoint.
Decision for <conflict-id>: <approved resolution>.
```

Unchanged completed phases are reused. Generation reads only the implementation
plan, generation parameters, consolidated service specification and archetype;
it must not reread raw Sparx. The normal stop is production code, planned tests
and static/offline validation. Maven, database access and deployment require
separate explicit authorization. Unsupported technical backend profiles are
reported as stage failures, never hidden behind scaffold output.
