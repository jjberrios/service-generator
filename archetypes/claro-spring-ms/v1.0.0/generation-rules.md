# Generation Rules

Generation uses this frozen archetype plus approved OpenAPI and Sparx inputs. It must not re-read the reference project. Parameter definitions and affected paths in `archetype.yml` are authoritative.

## Reusable / Static

1. Retain Java 21, Spring Boot 3.4.1, single-module Maven JAR packaging, the Maven Wrapper baseline, and the inventoried plugin versions/configuration. Do not silently upgrade them. [`pom.xml:3-25,178-278`; `.mvn/wrapper/maven-wrapper.properties:1-3`]
2. Retain **every** dependency of the reference POM (21 dependencies, reference scopes and versions). Never prune a baseline dependency because the target does not appear to use it. [`pom.xml:60-174`; D-001; D-002; D-011; D-012]
3. Retain Checkstyle enforcement and JaCoCo report/check execution with `minimumCoverage: 80`. [D-004; `pom.xml:207-276`; `checkstyle.xml:1-76`]
4. Retain `logback.xml` with JSON console and corporate appenders. Never generate `logback-spring.xml`. [D-001; `logback.xml:1-54`]
5. Retain Springdoc tooling but keep `OpenApiConfig` free of `@Server`, base URLs, and all API contract metadata. [D-007; `SwaggerConfig.java:13-24`]
6. Retain the temporary permissive security chain and unregistered JWT filter exactly as documented for 1.0.0. Do not claim that this baseline enforces authentication and do not redesign it during generation. [D-002; `SecurityConfig.java:13-27`; `JwtRequestFilter.java:47-101`]
7. Retain the Docker multi-stage/separated-classpath strategy and Kubernetes rolling-update, ConfigMap, ExternalSecret, and restricted-security-context structures. [D-005; D-006; `Dockerfile:1-44`; `config/deployment.yml.j2:1-70`; `config/ExternalSecret.yml.j2:1-29`]
8. Retain repository hygiene, wrapper line endings, and the Jenkins shared-library invocation. [`.gitignore:1-33`; `.gitattributes:1-2`; `Jenkinsfile:1-5`]

Static values change only through a reviewed archetype revision or new version.

## Parameterized

1. Derive `group_id` from `base_package` and use `1.0.0-SNAPSHOT` as the initial project version unless a target explicitly overrides it (D-010). Replace service name, base package/path, application class, and CI Vault name only with values that satisfy `archetype.yml`. Derive `__BASE_PACKAGE_PATH__` from `__BASE_PACKAGE__` by replacing dots with slashes. [`pom.xml:3-17`; D-010]
2. Replace all Logback service/package/level/time-zone tokens. Do not rename `logback.xml` or introduce `logback-spring.xml`. [D-001; `logback.xml:1-54`]
3. Set the JWT roles claim from approved security/deployment input. Supply the JWT signing key only at runtime through `JWT_SECRET_KEY`; never replace it with a literal or fallback. [D-002; `application.properties:51-54`; `JwtRequestFilter.java:65-70`]
4. The JaCoCo and Sonar exclusions are part of the reference POM baseline; only `__BASE_PACKAGE_PATH__` and `__APPLICATION_CLASS__` are substituted. Additional exclusions must be explicit, justified additions. [D-004; D-012; `pom.xml:30-40,235-247`]
5. Retain the reference POM repository convention (`repository-url` property, `release`, `local-claro-snapshot`, `local-claro-release`) and the D-009 approved non-secret static settings baseline. Do not add usernames, passwords, tokens, or other credentials; any future credential mechanism remains external and must be explicitly approved. Corporate network/VPN reachability is an execution prerequisite, not a guessed setting. [D-003; D-009; `pom.xml:33-59`; `settings.xml:1-90`]
6. Replace Docker image, port, configuration-location, time-zone, package, and application-class tokens. Do not restore `libs`, private reference registries, Oracle flags, or service-specific comments. [D-005; `Dockerfile:1-44`]
7. Replace every Kubernetes identity, namespace, label, image, registry, service-account, ConfigMap, Secret, Vault, port, mount, and environment token from approved deployment input. No unresolved token may reach a generated manifest. [D-006; `config/deployment.yml.j2:1-70`; `config/ExternalSecret.yml.j2:1-29`]
8. Structured markers may be replaced only with syntax-validated entries of their declared type: ExternalSecret `data` list items or sanitized Java properties. They are not unrestricted text-substitution points. [D-004; D-006; `pom.xml:235-247`; `config/ExternalSecret.yml.j2:21-29`; `config/configmap.yml.j2:28-76`]
9. Derive `base_package` using `archetype.yml#/package_naming`: `com.claro.<normalized-service-identity>.support`, with lowercase hyphen-separated identity components converted to dot-separated package segments. Keep every identity prefix unless an explicit target-specific instruction authorizes removing it. Derive `base_package_path` by replacing dots with slashes. [D-008]

## Generated From Specification

1. **OpenAPI owns:** server declarations/base URLs, HTTP methods and paths, headers, request parameters, media types, request/response schemas, status codes, and API-declared validation. Generate these into controller and DTO seams; never infer them from the reference. [`AGENTS.md:80-92,210-221`; D-007]
2. **Sparx owns:** service behavior and orchestration, integrations, external clients, persistence behavior, entities/tables required by that behavior, repositories, and queries. Persistence behavior (what is stored, queried and updated) is Sparx-owned, but the persistence technology is archetype-owned: use Spring Data JPA/Hibernate/Oracle/HikariCP (D-011). Add clients or messaging dependencies only when approved Sparx-derived requirements need them. [`AGENTS.md:93-103,217-221`; `pom.xml:128-150`]
3. **OpenAPI + Sparx own mappings:** generate field mappings only where contract models and behavior interact. Do not copy reference mapper fields or select a mapping framework without approved evidence. [`IndividualMapper.java:17-139`; `AGENTS.md:220-221`]
4. Generate exceptions and tests from the same ownership boundary: OpenAPI-declared errors and validation plus Sparx behavior, integrations, and persistence. Reuse the JUnit/Mockito organization, not reference scenarios or fixtures. [`GlobalExceptionHandler.java:27-359`; `IndividualServiceImplTest.java:36-703`]
5. Additional ExternalSecret entries and mounted application properties may be emitted only when the owning deployment configuration, OpenAPI, or Sparx input requires them. Never infer database secrets or domain messages from the reference. [D-006; `config/ExternalSecret.yml.j2:21-29`; `config/configmap.yml.j2:28-76`]

No external Swagger/OpenAPI contract or Sparx export was inspected during this revision.

## Project-Specific / Excluded

1. Exclude every concrete reference entity, table/schema/column, endpoint, DTO, repository query, mapping, service operation, business rule, response message, test scenario, fixture, and sample value. [`IndividualEntity.java:19-65`; `IndividualServiceImpl.java:51-379`; `IndividualServiceImplTest.java:36-703`]
2. Exclude datasource URLs and credentials, development JWT secrets, private IP addresses, private registry/repository values, biometric labels/owners, and machine-local paths. [`application.properties:29-54`; `settings.xml:6-90`; `Dockerfile:5-7`; `config/deployment.yml.j2:10-14,33-36,51`]
3. Exclude `target/`, IDE metadata, runtime data, local binaries, and unexplained `libs`. [`.gitignore:1-33`; reference inventory]
4. Nothing in the reference POM is excluded from the Maven baseline: Kafka, HTTP client, common utilities, the Tomcat override, JSON, Commons IO, Micrometer tracing, Spring Data JPA and Oracle are baseline dependencies (D-011, D-012). [`pom.xml:97-150` and source import evidence]
5. Exclude external Swagger/OpenAPI contract files and Sparx/architecture exports from the template and from this revision's reasoning. [`AGENTS.md:80-112,234-248`]
6. Exclude `@Server(url = "/")` and every other hardcoded OpenAPI server/base URL. [D-007; `SwaggerConfig.java:13-24`]

## Ambiguities Requiring Human Review

None. D-001 through D-007 resolve all ambiguities recorded for this version. D-002 remains a temporary approved compatibility choice and should be reconsidered in a future archetype version rather than silently redesigned.

## Activity logging inheritance (D-013)

1. The reference activity-logging structure is mandatory: copy `ActivityLogger` and `ConstanApi` from `template/.../utils/` (package token only), generate the activity constants from the authoritative activities in `service-spec.yml`, and implement `RequestHeaders`, `ejecutarActividad`, the per-operation request-logging helpers, body logging through `ActivityLogger.logContenido`, and the reference error-logging patterns exactly as `archetype.yml#/activity_logging` describes.
2. The full implementation plan must contain an `activityLogging` section for every active operation (transaction source, request-entry logging, activity sequence and constants with their service-spec evidence, start/end logging, body logging, business and technical error logging). Materialization must not start without it, and must not reread raw Sparx to decide where logs belong.
3. Do not invent activities. If the specification supports a single activity for an operation, only that activity is wrapped. Do not copy reference-service constants or messages. Do not add masking or log fields that the target contract does not declare.
4. Logging never changes behavior: status mapping, exceptions and return values stay those of the approved specification.

## Persistence technology inheritance (D-011)

1. Persistence technology is inherited from the approved archetype: Spring Data JPA, Hibernate, Oracle, HikariCP. Generators and planners must not choose plain JDBC (`NamedParameterJdbcTemplate`, SQL builders, `RowMapper`) or another technology because it is simpler, shorter or preferred.
2. Authority order for the persistence technology: (1) explicit user instruction; (2) explicit target-specific approved technical requirement; (3) approved archetype/reference architecture. An override must be recorded with its provenance in the plan; absence of an override means JPA.
3. Follow the persistence conventions in `archetype.yml#/persistence` and `conventions.md`: model-package `@Entity` with Lombok and `@Table`/`@Column`; `@GeneratedValue(IDENTITY)` for generated keys with the real database mechanism kept as an explicit runtime risk; `JpaRepository<Entity, Long>`; `JpaSpecificationExecutor`/`Specification` only when a target behavior needs dynamic filters; audit timestamps via `LocalDateTime.now(ZoneId.systemDefault())` in the service; repository calls wrapped for `QueryTimeoutException`/`DataAccessException`.
4. Render `application.properties` from `template/src/main/resources/application.properties`, which preserves the reference blocks APPLICATION, LOGGING, SWAGGER, ACTUATOR, DATA SOURCE, HIKARI, JPA / HIBERNATE, JWT TOKEN and SPRING CLOUD. Replace only `__SERVICE_NAME__`, `__BASE_PACKAGE__`, `__JWT_ROLES_CLAIM__` and an explicitly defined target port. Datasource values stay `${DB_URL}`, `${DB_USERNAME}`, `${DB_PASSWORD}`. Never copy `SUBTYPES IDF`, reference credentials, or the reference JWT development default (D-002).

## Checkstyle quality gate (D-014)
1. The reference `checkstyle.xml` (`archetype.yml#/quality/checkstyle`) is the style authority for generated production AND test Java. The planner records it in `qualityGates.checkstyle`; the materializer writes style-conformant code from the start.
2. Never weaken, disable, skip, suppress or add generated-code exclusions to satisfy it; never edit `checkstyle.xml` or the plugin configuration in the generated service.
3. Plan and write code that avoids the known violating patterns: annotation-array children at indentation 6 (or 12), no `switch` expression directly after `(` (assign to a local first), declare locals within 3 statements of first use, and no numeric literals beyond the configured ignore list - use constants named by test/domain meaning (never `VALUE_1`).
4. Final validation order: expected file inventory, Java syntax, imports/structure, reference Checkstyle (main and test sources), generation manifest consistency. Java parsing never substitutes for Checkstyle.
5. Run the narrowest Checkstyle execution available (for example `mvnw -o -s settings.xml validate`). If it cannot run, record `unverified` (with reason); only 0 violations may be recorded as `passed`. Generation is complete only after `passed`.

## Maven baseline inheritance (D-012)

1. The reference project's `pom.xml` is the mandatory Maven baseline. `template/pom.xml` is the reference POM with only the substitutions declared in `archetype.yml#/maven/reference_pom_baseline/substitutions`. Render it with the target values (group id, artifact id and name, project version, application class, base-package path) using `plan-service-implementation/scripts/pom_baseline.py`; do not hand-compose a POM from the dependencies a target seems to need.
2. The planner and generator must preserve, unchanged: the parent, every property (including `repository-url` and all reference version properties), every repository, every dependency with its reference scope and version, every build plugin with its configuration, the quality configuration (Checkstyle, JaCoCo exclusions and 80 percent rule, `doxia-core`, Sonar exclusions) and every profile (`local`, `activeByDefault`).
3. Pruning a baseline item, changing a baseline value, or replacing the repository convention is a generation defect. Version overrides that differ from Spring Boot's managed versions (for example `tomcat.version`) are baseline values and may only be reported as risks.
4. Target-specific dependency additions are allowed when the target implementation or its generated tests require them. Record each in the implementation plan with a justification and the planned component that requires it; render them after the baseline; never let an addition replace or cause the pruning of a baseline item.
5. Every generation must produce a machine-readable baseline comparison (reference item, generated item, status: inherited, parameterized, target-specific addition, intentionally excluded). Any missing, modified or unjustified item fails validation.
