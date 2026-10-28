# Approved Decisions — claro-spring-ms 1.0.0

These decisions are approved for this archetype version. They take precedence over reference-project evidence in accordance with `AGENTS.md`. Approval is confirmed by the explicit revision instruction dated 2026-09-30. They do not automatically apply to another archetype version.

## D-001 — Logging baseline

**Status:** approved

Use `src/main/resources/logback.xml` as the logging baseline and do not include `logback-spring.xml`. Preserve the reusable JSON-console and corporate-appender strategy observed in the reference. Service identity, package, levels, and time zone are parameters.

**Evidence:** `src/main/resources/logback.xml:1-54`; conflicting alternative at `src/main/resources/logback-spring.xml:1-6`.

## D-002 — Temporary security baseline

**Status:** approved, temporary for 1.0.0

Retain the reference Spring Security/JWT implementation without redesigning its behavior. Sanitize packages and configuration, parameterize the JWT roles claim, and require the signing secret from the environment with no fallback value. Preserve the observed permissive filter chain and the fact that the JWT filter is not registered in it. This is compatibility behavior, not a claim that authentication is enforced.

**Evidence:** `pom.xml:152-174`; `src/main/java/com/claro/biometria/individual/support/configuration/security/SecurityConfig.java:9-28`; `src/main/java/com/claro/biometria/individual/support/security/filter/JwtRequestFilter.java:28-102`; `src/main/java/com/claro/biometria/individual/support/security/service/JwtValidatorService.java:15-38`; `src/main/java/com/claro/biometria/individual/support/security/service/impl/JwtValidatorServiceImpl.java:25-91`; `src/main/resources/application.properties:51-54`.

## D-003 — Maven settings and corporate repositories

**Status:** approved

Retain support for a checked-in, sanitized `settings.xml` and corporate Maven repositories. Repository IDs, mirror selection, and URLs are parameters. Credentials must never be hardcoded; secure runtime or CI injection owns credentials when they are required.

**Evidence:** `pom.xml:41-59`; `settings.xml:1-92`; `Dockerfile:17-28`.

## D-004 — Coverage configuration

**Status:** approved

Keep JaCoCo enabled at an 80 percent package-level instruction covered ratio. JaCoCo exclusions and Sonar coverage exclusions are independently configurable generation inputs so that intentional differences are explicit.

**Evidence:** `pom.xml:30-40,224-276`.

## D-005 — Docker baseline

**Status:** approved

Use the reference Dockerfile as the baseline. Preserve its multi-stage build, Maven settings use, separated classes/dependencies runtime layout, non-fat-JAR classpath launch, and Java 21 builder/runtime intent. Parameterize images, main class, exposed port, external configuration location, and time zone. Exclude the unexplained `libs` copy, private addresses, Oracle-only runtime flags, stale comments, and all service/domain identities.

**Evidence:** `Dockerfile:1-44`; `settings.xml:1-92`.

## D-006 — Kubernetes baseline

**Status:** approved

Use the reference Kubernetes templates as a structural guide. Preserve reusable Deployment, rolling-update, ConfigMap mount, ExternalSecret injection, and restricted container-security patterns. Parameterize service and resource names, namespace, labels, registry/image, environment, service account, ConfigMap, Secret, Vault store/path/property, port, and other deployment-specific values. Remove biometric ownership and database-specific secret/configuration content.

**Evidence:** `config/deployment.yml.j2:1-70`; `config/ExternalSecret.yml.j2:1-29`; `config/configmap.yml.j2:1-76`.

## D-007 — OpenAPI server ownership

**Status:** approved

Do not place `@Server(url = "/")` or another server/base URL in the static template. OpenAPI owns server declarations, base URLs, HTTP contracts, schemas, and API-level validation. The archetype retains only Springdoc tooling and neutral wiring.

**Evidence:** `src/main/java/com/claro/biometria/individual/support/configuration/swagger/SwaggerConfig.java:13-24`; repository policy `AGENTS.md:80-103,210-235`.

## D-008 — Java base-package naming

**Status:** approved

Use the reusable package form `com.claro.<normalized-service-identity>.support`. Normalize the service identity to lowercase and convert its hyphen-separated components into dot-separated Java package segments. Do not remove a service-identity prefix by default; prefix removal is permitted only when explicitly authorized for that target. Derive `base_package_path` by replacing dots with slashes.

**Evidence:** the approved `ms-individual` package tree establishes the `com.claro` namespace and terminal `support` package; package identity components are supplied or explicitly normalized per target.

## D-009 — Approved corporate Maven resolution baseline

**Status:** approved

Use the non-secret repository, mirror, profile, and plugin-repository configuration from the approved reference Maven files as the initial corporate resolution baseline for this archetype. The reusable baseline values are recorded in `archetype.yml#/maven/approved_corporate_baseline` and the static `template/settings.xml`; POM release/snapshot coordinates use the declared baseline defaults. Do not embed credentials. This decision supersedes D-003's parameter-only treatment for these approved initial baseline values; target overrides remain explicit inputs. Network/VPN reachability to the private corporate endpoints is an execution prerequisite.

**Evidence:** `input/reference/ms-individual/pom.xml` Maven project/repository declarations; `input/reference/ms-individual/settings.xml` mirrors, profiles, and plugin repositories. No Maven server credentials are declared there.

## D-010 — Maven coordinates defaults

**Status:** approved

Set `group_id` equal to the resolved `base_package`. Use `1.0.0-SNAPSHOT` as the initial project version for generated services unless a target explicitly supplies another version. The reference coordinates are not used as defaults; this decision is the approved reusable source.

**Evidence:** explicit current user approval; the package derivation is governed by D-008.

## D-011 - Persistence architecture inherited from the reference (JPA)

**Status:** approved (explicit current user instruction; correction of a technical planning deviation)

**Decision:** The approved reference project defines the persistence technical architecture. Services generated from `claro-spring-ms` 1.0.0 use Spring Data JPA with Hibernate, Oracle (driver `ojdbc11` 21.11.0.0, runtime) and HikariCP, with the conventions recorded in `archetype.yml#/persistence`. Persistence technology is inherited from the archetype; plain JDBC must not replace it because of simplicity or model preference. A different technology requires an explicit user instruction or an explicit authoritative target technical requirement. Authority order: explicit user instruction, target-specific approved technical requirement, approved archetype/reference architecture.

The reference `application.properties` is the approved technical baseline for the blocks APPLICATION, LOGGING, SWAGGER, ACTUATOR, DATA SOURCE, HIKARI, JPA / HIBERNATE, JWT TOKEN and SPRING CLOUD. Service-specific values (application name, base package for logging/springdoc, datasource URL/credentials via `DB_URL`/`DB_USERNAME`/`DB_PASSWORD`, an explicitly defined port) are adapted; the SUBTYPES IDF section (`subtype.*`, `detail.*`, `message.*`) and reference credentials are excluded.

**Supersedes:** the unsupported-dependency exclusion of JPA/Oracle in X-005 and the "persistence technology is Sparx-owned" reading in the earlier generation rules. Persistence behavior remains Sparx-owned.

**Recorded conflict (not silently resolved):** the reference JWT property declares a development-only default (`${JWT_SECRET_KEY:default...}`) whereas D-002 forbids any fallback. D-002 remains in force; the archetype keeps `${JWT_SECRET_KEY}` only. Revisit explicitly if the fallback is desired.

**Evidence:** E-023 (reference `pom.xml`, `IndividualEntity.java`, `IndividualRepository.java`, `IndividualServiceImpl.java`, `application.properties`).

## D-012 - Reference POM is the mandatory Maven baseline

**Status:** approved (explicit current user instruction; correction of a technical planning/generation deviation)

**Decision:** The Maven POM of the approved reference project is a mandatory technical baseline. Services generated from `claro-spring-ms` 1.0.0 use that POM exactly - parent, Java/Spring baseline, properties, repositories (the `repository-url` convention with `release`, `local-claro-snapshot` and `local-claro-release`), dependencies with the reference scopes and versions, build plugins and their configuration, quality configuration and the `local` profile - **plus justified service-specific additions**. The planner/generator may add target-specific dependencies when the target implementation or its generated tests justify them, but must not prune baseline dependencies, properties, repositories, plugins or profiles, and must not alter baseline values. Only the group id, artifact id and name, project version, the application class in the Sonar exclusions and the base-package path in the JaCoCo exclusions are substituted (`archetype.yml#/maven/reference_pom_baseline`). This applies automatically to every future service-generator execution.

**Supersedes:** the POM-repository parameterization in D-009 (the static `settings.xml` baseline of D-009 is unchanged), the exclusion of Kafka, HTTP client, common utilities, direct Tomcat override, JSON, Commons IO and Micrometer tracing in X-005 and generation rules 2 and 4, and the `jacoco_exclusions`, `sonar_coverage_exclusions` and corporate POM repository id/url parameters. D-004's coverage rule (80 percent) is unchanged; its configurable-exclusions wording now means justified additions to the baseline exclusions.

**Recorded observation (not silently resolved):** the baseline pins `tomcat.version` 10.1.25 and `tomcat-embed-core` explicitly, which differs from the Tomcat managed by Spring Boot 3.4.1. It is preserved as a baseline value; any security or compatibility implication must be reviewed explicitly in a future archetype version.

**Evidence:** E-024 (complete reference `pom.xml`, hash recorded in `archetype.yml#/maven/reference_pom_baseline`).

## D-013 - Activity logging structure of the reference is mandatory

**Status:** approved (explicit current user instruction; correction of a technical generation deviation)

**Decision:** The activity-logging structure of the approved reference project is mandatory for services generated from `claro-spring-ms` 1.0.0: the `ActivityLogger` pattern (`inicioActividad`, `finActividad`, `logContenido`), the transaction-prefix construction, activity constants, an `ejecutarActividad`-style wrapper, reference-compatible business-error and technical-error logging, and per-operation request-entry logging helpers. Names follow the reference unless they carry reference-domain names. `ActivityLogger`, `ConstanApi` (technical constants only) and `ActivityLoggerTest` are template files; no corporate dependency provides them. Activity names come from the authoritative service behavior in `service-spec.yml`, never from the reference and never invented; the transaction identifier is mapped explicitly from a declared target header. It applies automatically to every future service-generator execution; the planner must emit an explicit `activityLogging` plan section and the orchestrator must verify it before materialization.

**Recorded observations (not silently resolved):** the reference applies no masking or filtering of sensitive fields in `logContenido`, so request bodies are logged in full; any sensitive-data policy must be a future explicit decision. The reference's `convertValue(contenido, tipo)` round trip fails for DTOs whose setters reject nulls unless the DTO omits null properties; generated request DTOs therefore use `@JsonInclude(NON_NULL)` where they use `Nulls.FAIL`.

**Evidence:** E-025.

## D-014 - Reference Checkstyle is a mandatory generated-code quality gate

**Status:** approved (explicit current user instruction; correction of a missing generation requirement after the first generated service failed the reference Checkstyle with 35 violations)

**Decision:** The Checkstyle configuration of the approved reference project (`src/main/resources/checkstyle.xml`, executed by `maven-checkstyle-plugin` in the `validate` phase with `includeTestSourceDirectory=true`) is a mandatory quality gate for ALL generated Java: `src/main/java` AND `src/test/java`. Generation is not complete while a violation remains, and a Java syntax parse never substitutes for Checkstyle. The complete `checkstyle.xml` is the authority, not a short list of known rules. The rules must not be weakened, disabled, skipped, suppressed (`@SuppressWarnings`, suppression files) or bypassed with generated-code exclusions. When Checkstyle cannot be executed (for example the corporate repository or plugin cache is unavailable) the gate result is `unverified`, never `passed`. Applies automatically to every future service-generator execution; the planner must emit an explicit `qualityGates.checkstyle` plan section and the orchestrator must require status `passed` with 0 violations before marking generation complete.

**Style patterns known to violate the baseline (generation must avoid them, derived from the reference configuration):** annotation-array children (for example `@ApiResponses({ ... })`) indented at 8 where the rule requires 6 (basic offset 4 + `arrayInitIndent` 2) or 12; `switch` expressions directly after `(` (`WhitespaceAround`; assign to a local variable first); local variables declared more than 3 statements before first use (`VariableDeclarationUsageDistance`); numeric literals in code other than -1, 0, 1, 2, 4, 200, 201, 400, 401, 403, 404, 418, 500 and 1000 (`MagicNumber`; use constants named by their meaning, including in tests), plus line length 250, star/unused/redundant imports, braces, operator wrap on a new line, comma wrap at end of line, one statement per line, modifier order and name formats.

**Evidence:** E-009 (reference `checkstyle.xml` and `pom.xml` Checkstyle plugin configuration); E-026 (offline execution of the gate against the first generated service).

