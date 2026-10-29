---
name: extract-archetype
description: Use when extracting, revising, or validating a reusable Java/Spring microservice archetype from a reference project while separating technical conventions from business-specific implementation.
---

# Extract Archetype

Use this deterministic methodology to extract, revise, or validate a technical
archetype from an approved Java/Spring reference project.

The reference project is evidence. It is not a template to copy wholesale.

## Inputs And Invariants

Establish:

- `<reference-root>`: approved reference project, always read-only
- `<target-root>`: versioned archetype directory
- `<repository-policy>`: repository-root `AGENTS.md`
- `<operation>`: `extract`, `revise`, or `validate`
- `<approved-decisions>`: existing `<target-root>/decisions.md` plus explicit
  human decisions provided by the current task

Read `AGENTS.md` first.

Do not inspect future OpenAPI contracts or Sparx exports while performing
archetype extraction unless explicitly requested by a different workflow.

Never modify `<reference-root>`.

## Operation Modes

### Extract

Use when creating a new archetype version.

The target version must not already contain an archetype.

Never silently overwrite an existing version.

### Revise

Use only when the user explicitly requests changes to an existing archetype
version.

Before changing anything:

1. read the existing archetype;
2. read `decisions.md` when present;
3. identify the requested approved decisions;
4. determine affected files;
5. preserve unrelated approved decisions.

### Validate

Do not modify the archetype.

Inspect consistency, decision implementation, domain leakage, parameter usage,
inventory completeness, and source ownership.

## Decision Precedence

Resolve conflicts using this order:

1. explicit current human instruction;
2. approved decision in `decisions.md`;
3. repository policy in `AGENTS.md`;
4. reference-project evidence;
5. model inference.

Never override an approved human decision solely because the reference project
contains another plausible implementation.

If evidence contradicts an approved decision, record the contradiction for
review.

## Classification Rules

Assign each candidate artifact or convention one primary disposition.

### Reusable / Static

Use when:

- it represents technical architecture or engineering structure;
- it may remain identical between generated services;
- evidence exists;
- it contains no service-specific business meaning.

### Parameterized

Use when the structure is reusable but values vary between services.

For every parameter define:

- parameter name;
- source;
- valid form where applicable;
- affected files;
- replacement scope.

Do not parameterize business code merely to disguise it as reusable structure.

### Generated From Specification

Use when future OpenAPI or Sparx specifications determine the implementation.

Typical ownership:

- HTTP methods -> OpenAPI
- paths -> OpenAPI
- request/response schemas -> OpenAPI
- declared API validation -> OpenAPI
- business flow -> Sparx
- business decisions -> Sparx
- integrations -> Sparx
- external clients -> Sparx
- persistence behavior -> Sparx
- mappings combining contract and behavior -> OpenAPI + Sparx

During archetype extraction, create only the technical seam or extension point.

Do not invent specification content.

### Project-Specific / Excluded

Exclude concrete domain entities, business tables, endpoints, request/response
models, repository queries, business mappings, business services, business
rules, domain test fixtures, sample business payloads, local development state,
runtime data, credentials, and generated build output.

Preserve the selected reference's complete POM dependency baseline, including
dependencies whose observed callers are excluded. Inventory declared dependencies
and observed use separately. Removing or changing a dependency requires an explicit
approved deviation for the target version; domain-code exclusion alone is insufficient.

## Ambiguity And Approved Decisions

Ambiguity is a review state, not an extraction class.

When no approved decision exists and evidence is insufficient:

- do not silently select an alternative;
- document the ambiguity;
- identify evidence;
- describe competing interpretations;
- explain consequences;
- request a concrete human decision.

Once a human explicitly resolves an ambiguity:

- record a stable decision ID;
- add or update the decision in `decisions.md`;
- remove the ambiguity as unresolved;
- apply the decision consistently;
- preserve whether the decision is temporary, configurable, or final.

A human-approved baseline does not automatically become a universal corporate
standard.

## Evidence Standard

Every extracted or approved convention should retain traceability.

Record where applicable:

- decision ID;
- classification;
- reference source;
- line/key/location;
- observed value;
- approved value;
- rationale;
- affected outputs;
- confidence;
- status.

Human approval itself is valid decision evidence, but reference evidence should
still be retained when the decision originates from a reference-project
pattern.

## Procedure

### 1. Preflight

1. Read `AGENTS.md`.
2. Resolve reference and target paths.
3. Determine operation mode.
4. Verify reference exists.
5. Confirm reference is read-only.
6. Read existing `decisions.md` during revision or validation.
7. Record an equivalent source-tree baseline when feasible.
8. Confirm the current phase does not include Swagger/Sparx analysis.

### 2. Inventory

Inventory before classification:

- POMs
- Maven wrapper
- settings.xml
- Java source roots
- resources
- tests
- application configuration
- logging
- security
- quality configuration
- Docker
- Kubernetes
- CI/CD
- relevant technical documentation

Do not blindly copy files.

### 3. Build And Platform

Inspect Java version, Spring Boot version, Maven structure, properties,
dependency management, dependencies, plugin management, plugins, repositories,
settings.xml support, wrapper, and build lifecycle.

Trace why dependencies and plugins exist.

### 4. Application Architecture

Inspect representative implementations for package structure, controllers,
services, repositories, persistence, DTOs, mappers, exceptions, configuration,
logging, security, and OpenAPI tooling.

Extract only technical patterns or explicitly approved baselines.

#### 4.1 Code-style conventions that the generator must reproduce (mandatory)

Inspect how the reference externalizes values and record the findings in
`archetype.yml` under `generation.style` and in `conventions.md`/`generation-rules.md`
(with evidence references). At minimum capture:

- where literal values live (constants class and package, naming of constants,
  index/parameter/column/log-text/path constants) and whether hard-coded literals
  are allowed in main code (`hardcodedLiterals: forbidden|allowed`);
- which values are external properties (class that binds them, annotation, key naming
  pattern, per-operation keys, timeouts, datasource/JNDI names, response codes and
  messages, stored-procedure owner/package/name) and which class owns the binding;
- bean/qualifier names, exception hierarchy, naming of DAO/repository/config classes.

The generator must not emit code that contradicts these observed conventions
(for example literals inline, environment values in code, classes named differently
from the reference). If the reference does not externalize values, record that
explicitly (`not-present-in-reference`) instead of imposing the style of another
archetype. A reviewer must compare a sample of generated code against the reference
style before an archetype is declared generation-ready; planners/materializers stop
when `generation.style` is missing for their profile.

#### 4.2 Utility classes and configuration templates must be inventoried and kept (mandatory)

Never drop reusable reference artifacts just because the file is "mixed" or lives
outside `src/`:

- **Utility classes** (for example `common.util.*`): inventory every reference utility
  class method by method. Split technical/reusable methods (JSON printing, date
  formats, exception-message helpers, null/empty checks, value mapping, server IP,
  logging helpers) from business-specific ones (per-request validators, response
  error builders bound to a contract). Put the technical part in `template/` as a
  parameterized class and declare it in `archetype.yml` `generation.utilities.items`
  (template path, class, scope, `requiredConstants` that the generator must register
  in the constants class). Generated code must use these utilities instead of
  duplicating helpers; only business-specific methods are excluded and documented.
- **Configuration templates** (`*.j2`, `jndi/*.yml`, similar deployment config files,
  excluding `application*.properties` which are never read): copy them into
  `template/` parameterized and without secrets, declare them in
  `generation.configuration.items`, and record which keys are generic (kept) and which
  are service-specific (appended by the materializer). Listing them only in
  `exclusions` is not allowed unless they contain secrets, and the reason must be
  recorded in `decisions.md`.
- Every reference file not copied must appear in `exclusions` with a reason; a
  reviewer checks that list against the reference tree before declaring the
  archetype complete.

### 5. Tests And Quality

Inspect JUnit, Mockito, test layout, naming, JaCoCo, coverage thresholds,
coverage exclusions, Sonar configuration, Checkstyle, and static analysis.

Distinguish mechanisms from project-specific exclusions.

### 6. Runtime And Delivery

Inspect application configuration, logging, Docker, Kubernetes,
secrets/configuration templates, and Jenkins/CI.

Separate reusable structure, configurable infrastructure values,
business/domain-specific values, and credentials/secrets.

### 7. Decision Matrix

For every candidate assign:

- `reusable/static`
- `parameterized`
- `generated-from-specification`
- `project-specific/excluded`

Also associate an approved decision ID when applicable, source owner when
generated later, and affected template files.

### 8. Apply Approved Decisions

Before writing or revising outputs:

1. load all applicable approved decisions;
2. identify affected components;
3. ensure decisions do not conflict with each other;
4. parameterize service/environment-specific values where required;
5. mark temporary decisions accordingly;
6. preserve traceability.

Do not substitute a different implementation merely because the agent believes
it is preferable.

### 9. Design Outputs

The complete archetype structure is:

```text
<target-root>/
  archetype.yml
  conventions.md
  generation-rules.md
  decisions.md
  template/
```

Do not recursively copy source trees.

### 10. Produce Or Revise Archetype

#### archetype.yml

Include identity/version, provenance, runtime/build versions, project/package
structure, dependencies, plugins, test configuration, quality configuration,
runtime/container/delivery metadata, parameters, template inventory,
generation ownership, exclusions, evidence references, decision references,
and unresolved ambiguities.

#### conventions.md

Describe reusable conventions, configurable baselines, approved technical
baselines, and temporary baselines.

Do not represent a temporary human-approved decision as a corporate standard.

#### generation-rules.md

Separate:

- Reusable / Static
- Parameterized
- Generated From Specification
- Project-Specific / Excluded

For generated areas, declare their owner.

#### decisions.md

For every human-approved decision include:

- ID
- Topic
- Decision
- Status
- Scope
- Rationale
- Affected areas
- Evidence
- Future review

Use stable IDs such as `D-001`, `D-002`, `D-003`.

Do not reuse an ID for a different decision.

#### template/

Contain only reusable artifacts, explicitly approved baseline artifacts, and
properly parameterized infrastructure/configuration.

No reference business behavior may leak into the template.

## Validation

Run the shared read-only relational validator before the profile-specific validator:

```text
python .opencode/skills/extract-archetype/scripts/validate_inventory.py archetypes/<name>/<version>
python archetypes/<name>/<version>/validate-extraction.py
```

The shared validator checks inventory equality, duplicate YAML keys, exact parameter
locations, decision/evidence references, declared utility/configuration files and
POM dependency/plugin inventory fields. It supports `templateInventory`/`@@TOKEN@@`
and the existing claro-spring-ms manifest through a read-only legacy adapter.
An unknown schema is an explicit unsupported-schema result, never a pass.
It never reads protected application properties or requires a generation backend.
The profile validator retains full POM fidelity and reference-specific checks;
the common checks do not replace those checks or prove compilation/runtime.
Historical reference hashes covering other projects or filesystem modification
times cannot establish target-local provenance. Retain them, report unverified,
and never replace them with the current hash merely to make validation pass.
See `validation-contract.md` for scope and known legacy metadata findings.

Before completion:

1. Parse `archetype.yml`.
2. Validate XML/configuration formats when practical.
3. Validate every declared template artifact.
4. Validate every parameter usage.
5. Validate dependency/plugin inventory.
6. Validate generation ownership.
7. Validate every approved decision against all affected outputs.
8. Verify no unresolved ambiguity is represented as a final rule.
9. Search for reference service names.
10. Search for reference package names.
11. Search for domain entities/tables/DTOs/endpoints.
12. Search for business rules and repository queries.
13. Search for secrets and credentials.
14. Verify OpenAPI/Sparx behavior was not invented.
15. Verify the reference project is unchanged.
16. Verify consistency between `archetype.yml`, `conventions.md`,
    `generation-rules.md`, `decisions.md`, and `template/`.

The archetype is ready to freeze only when its approved decisions are
implemented consistently and no unresolved issue invalidates generation.
