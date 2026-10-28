# Claro Spring Microservice Conventions 1.0.0

These conventions are supported by reference evidence and reconciled with the approved decisions in `decisions.md`. The approved decisions take precedence when the reference contains conflicting alternatives.

## Platform and Maven

- Use Java 21, Spring Boot parent 3.4.1, a single Maven module, JAR packaging, Maven Compiler Plugin 3.8.1 with `release=21`, and the Spring Boot Maven Plugin with Lombok excluded from the packaged artifact. [`pom.xml:3-16,178-206`]
- Keep Maven Wrapper 3.3.4 configured for Maven 3.9.12 with script-only distribution. No checksum is invented because none is present in the evidence. [`.mvn/wrapper/maven-wrapper.properties:1-3`; `mvnw:21-29`; `mvnw.cmd:21-27`]
- Use the reference POM repository convention (D-012): the `repository-url` property with the `release`, `local-claro-snapshot` and `local-claro-release` repositories composed as `${repository-url}/<path>/`, and the D-009 non-secret checked-in static `settings.xml` mirrors, profiles, repositories, and plugin repositories. Under D-010, derive `group_id` from `base_package` and default the initial project version to `1.0.0-SNAPSHOT` unless explicitly overridden. Never store Maven credentials; corporate network/VPN reachability remains an execution prerequisite. [D-009; D-010]

## Application structure and ownership

- Place the Spring Boot bootstrap class at the generated package root and retain corporate logger component scanning. Package and class names are parameters. [`IndividualApplication.java:1-14`]
- Preserve package seams for controller contract/implementation, service contract/implementation, DTOs, mappers, clients, persistence models/repositories, exceptions, configuration, and security. A seam is a destination, not permission to create speculative business code. [`IndividualController.java:33-69`; `IndividualService.java:19-33`; `IndividualRepository.java:17-31`]
- OpenAPI owns HTTP methods and paths, headers and parameters, server/base URLs, request/response schemas, status codes, and API-declared validation. Sparx owns behavior, integrations, external clients, and persistence. OpenAPI and Sparx jointly determine mappings. [`AGENTS.md:80-103,210-235`]
- Concrete entities, tables, DTOs, repository queries, field mappings, service behavior, domain exceptions, test scenarios, and fixtures from the reference are not archetype conventions. [`IndividualEntity.java:19-65`; `IndividualServiceImpl.java:51-379`; `IndividualServiceImplTest.java:36-703`]

## Maven baseline (approved correction D-012)

- **The `pom.xml` of the approved reference project is the mandatory Maven baseline of every service generated from this archetype.** It is the technical base project, not an example. `template/pom.xml` is that POM byte-for-byte with only five declared substitutions (group id, artifact id and name, project version, application class in the Sonar exclusions, base-package path in the JaCoCo exclusions); `archetype.yml#/maven/reference_pom_baseline` records the substitutions, the reference hash and the complete inventory. [D-012; E-024]
- A generated POM is therefore: **reference POM + justified service-specific additions**. Generators and planners must preserve the parent, Java/Spring baseline, all 17 properties (including `repository-url` and the reference version properties), the three repositories, all 21 dependencies with the reference scopes and versions, the five build plugins with their configuration (Lombok exclusion from the Spring Boot plugin, Checkstyle on test sources in `validate`, JaCoCo with `doxia-core`, the reference exclusions, the 80 percent package rule and the report/check lifecycle), and the `local` profile. Never prune a baseline item because the target does not appear to use it, and never alter baseline values or replace the repository convention with an equivalent layout.
- Service-specific dependencies may be added only when justified by the target implementation or its generated tests; each addition records its justification and `requiredBy` in the implementation plan, is rendered after the baseline, and never replaces a baseline item.
- The reference carries version overrides that differ from Spring Boot's managed versions (for example `tomcat.version`). They are baseline values: they are preserved, and any resulting security or compatibility concern is reported as a risk rather than silently changed.

## Activity logging (approved correction D-013)

- **The activity-logging structure of the approved reference project is mandatory for generated services; it must not be reduced to generic SLF4J logging.** `ActivityLogger` (`inicioActividad`, `finActividad`, `logContenido`) and `ConstanApi` are local reference utilities, so they are archetype template files (`template/.../utils/`), not a dependency. The reference `ActivityLoggerTest` is part of the template. [D-013; E-025]
- Service implementations are `@Slf4j`, receive a `RequestHeaders` record as first parameter, build the transaction prefix exactly as the reference (`String tx = headers != null ? headers.transactionId() : null; String menTran = tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;`, prefix `"[SIN-TRANSACTION] "`), and run every authoritative activity through a private `ejecutarActividad(menTran, actividad, Supplier<T>)` wrapper that logs start and end through `ActivityLogger`, logs `ERROR [actividad]` for business and unexpected exceptions, and always rethrows.
- Request entry is logged by one helper per active operation (`logGet`/`logCreate`/`logUpdate` style) inside the validation activity: a metadata line (`applicationName`, `transactionId`, `msgid`, `timestamp`, `userId` - only components that exist in the target header model) and, for request bodies, `ActivityLogger.logContenido(log, "<Operation> body: {}", body, <Type>.class)`. The reference applies no masking; none is added, so sensitive content in a body is a review risk, not a convention.
- Business errors inside an activity log `"{} ERROR [{}] code={} detail={}"` before the business exception is thrown; `QueryTimeoutException` and `DataAccessException` around repository calls log `"{} {}: {}"` with `LOG_TIMEOUT_*`/`LOG_ERROR_DATOS_*` constants. Logging is instrumentation: the target's approved exception-to-status mapping is unchanged.
- Activity constants (`ACT<n>_<NAME>`) come from the authoritative activities of the service specification, never from the reference's domain names and never as artificial steps. The transaction identifier is mapped explicitly from a declared target header and is never a business field.

## Checkstyle quality gate (approved correction D-014)
The reference `src/main/resources/checkstyle.xml` (executed in `validate` with `includeTestSourceDirectory=true`) is a mandatory gate for generated `src/main/java` and `src/test/java`. Generated code must conform to the whole configuration, which is never weakened, suppressed or excluded. Known violating patterns to avoid: annotation-array children not at indentation 6 or 12, `switch` expressions directly after `(`, local declarations more than 3 statements before first use, and numeric literals outside the configured ignore list (name test constants by meaning). Parsing Java is not Checkstyle; an unexecuted gate is `unverified`, never `passed`.

## Persistence architecture (approved correction D-011)

- **The approved reference project defines the persistence technical architecture: Spring Data JPA with Hibernate, Oracle and HikariCP.** Persistence technology is inherited from this archetype. Do not replace JPA with plain JDBC (`NamedParameterJdbcTemplate`, hand-built SQL, `RowMapper`) because it seems simpler or because of model preference. A different technology is allowed only when the user explicitly requires it or an authoritative target technical specification explicitly requires it. Persistence authority order: explicit user instruction, explicit target-specific approved technical requirement, approved archetype/reference architecture. [D-011; E-023]
- Entities live in the `model` package and use Lombok `@Data`, `@NoArgsConstructor`, `@AllArgsConstructor` with `jakarta.persistence` `@Entity`, `@Table(name = ...)`, `@Id`, and `@Column(name = ...)`. A `schema` attribute is set only when the target specification defines it. Use `@GeneratedValue(strategy = GenerationType.IDENTITY)` for generated keys as the reference does; never invent a sequence. Types follow the reference: `Long` keys, `Integer` flags, `String` text, `LocalDate`/`LocalDateTime` dates. [E-023]
- Repositories are `@Repository` interfaces extending `JpaRepository<Entity, Long>` in the `repository` package, using derived finders where possible. The reference has no dynamic-query mechanism; when a target requires one, extend the same repository with `JpaSpecificationExecutor` and `Specification`. Never concatenate SQL manually. [E-023]
- Services set audit timestamps with `LocalDateTime.now(ZoneId.systemDefault())` before `save`, call repository methods without an explicit `@Transactional` (as the reference does), and catch `QueryTimeoutException` and `DataAccessException` around repository calls; target specifications refine the resulting statuses. [E-023]
- Runtime configuration keeps the reference blocks APPLICATION, LOGGING, SWAGGER, ACTUATOR (including `management.health.db.enabled`), DATA SOURCE, Hikari, JPA / HIBERNATE, JWT TOKEN and SPRING CLOUD. Datasource URL, username and password come only from `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`. The reference SUBTYPES IDF properties (`subtype.*`, `detail.*`, `message.*`) and its datasource credentials are never copied. The reference's development-only JWT secret default is not retained because D-002 forbids fallbacks. [D-011; D-002]

## Web, validation, and OpenAPI tooling

- Use Spring MVC, Jakarta Validation tooling, and Springdoc WebMVC UI 2.7.0. Scan the generated base package, publish the UI at `/swagger-ui.html`, and disable the default Swagger URL. [`pom.xml:60-84`; `application.properties:14-18`]
- Keep `OpenApiConfig` contract-neutral. It must not contain `@Server`, a base URL, API metadata, operations, schemas, or other contract values. [D-007; `SwaggerConfig.java:13-24`]

## Logging

- Use only `src/main/resources/logback.xml`; do not generate `logback-spring.xml`. Retain the JSON console encoder and corporate appender strategy. [D-001; `logback.xml:1-54`; `logback-spring.xml:1-6`]
- Parameterize service identity, base package, logging levels, and logging time zone. The Logstash encoder and `claro-common-logger` dependencies are part of this approved logging baseline. [D-001; `pom.xml:18-19,91-106`; `logback.xml:4-52`]

## Security — temporary 1.0.0 compatibility rule

- Retain Spring Security and JJWT 0.11.5 with the reference `SecurityConfig`, JWT filter, validator interface, and validator implementation structure. [D-002; `pom.xml:152-174`; `SecurityConfig.java:9-28`; `JwtRequestFilter.java:28-102`; `JwtValidatorServiceImpl.java:25-91`]
- Preserve the observed permissive filter chain and do not register the JWT filter as part of this revision. This temporary baseline does **not** enforce JWT authentication and must not be described as doing so. [D-002; `SecurityConfig.java:13-27`]
- Obtain the JWT signing secret only from `JWT_SECRET_KEY`, with no hardcoded or development fallback. Parameterize the roles-claim name. [D-002; `application.properties:51-54`; `JwtRequestFilter.java:65-70`]

## Runtime and operations

- Enable virtual threads and parameterize `spring.application.name`. Expose Actuator health only, enable default/liveness/readiness indicators, and retain `show-details=always` as observed. Database health (`management.health.db.enabled=true`) is part of the approved baseline (D-011). [`application.properties:4-27`]
- Keep service/domain response messages and integration settings out of static runtime configuration. Datasource, Hikari, JPA and port baselines are governed by D-011; domain-specific properties remain target-owned. [D-011; `AGENTS.md:210-235`]

## Testing and quality

- Put tests under `src/test/java`, mirror production package paths, and use the `Test` suffix. Use JUnit Jupiter and Mockito; isolated tests use `MockitoExtension`, `@Mock`, and `@InjectMocks`, with `@Nested` and `@DisplayName` available for scenario grouping. Test scenarios and fixtures are generated from the owning specifications. [`IndividualServiceImplTest.java:13-47,129-133`]
- Run Checkstyle 3.3.1 in Maven `validate`, include test sources, and use the checked-in rule file. [`pom.xml:207-223`; `checkstyle.xml:1-76`]
- Keep JaCoCo 0.8.11 enabled with agent preparation plus report/check during `test`, enforcing a package-level instruction covered ratio of at least 80 percent. JaCoCo exclusions are the reference baseline (only the target package path is substituted); additional exclusions are allowed only as explicit justified additions. [D-004; D-012; `pom.xml:224-276`]
- Keep the reference Sonar coverage exclusions (only the application class name is substituted); they remain independent of the JaCoCo exclusions and any intentional difference must be explicit. [D-004; D-012; `pom.xml:30-40,235-247`]

## Docker, Kubernetes, and CI

- Use the parameterized multi-stage Dockerfile. Build with Maven and sanitized `settings.xml`, copy compiled classes and dependencies separately, and launch via a classpath entrypoint. Images, main class, port, configuration location, and time zone are parameters. Do not copy reference `libs`, private addresses, Oracle-only flags, or stale service comments. [D-005; `Dockerfile:1-44`]
- Preserve the Deployment rolling-update strategy, ConfigMap volume, Secret `envFrom`, service account, and restricted container security context. Parameterize all resource identity, labels, namespace, image, registry, environment, and mount values. [D-006; `config/deployment.yml.j2:1-70`]
- Preserve the ExternalSecret mechanism for the JWT secret while parameterizing Secret/Vault identifiers, path, property, store kind, refresh interval, and any specification-owned additional data. Do not retain biometric ownership or database-specific secret keys. [D-006; `config/ExternalSecret.yml.j2:1-29`]
- Treat `config/configmap.yml.j2` as the application-properties payload mounted through the parameterized ConfigMap. Additional contract/behavior configuration is generated only from OpenAPI/Sparx ownership. [D-006; `config/configmap.yml.j2:1-76`]
- Invoke the observed Jenkins shared library and pipeline; service and Vault names are parameters. [`Jenkinsfile:1-5`]

## Repository hygiene

- Keep generated output, IDE state, runtime data, local paths, binaries, credentials, and private infrastructure identifiers out of the archetype. Preserve the evidenced ignore and wrapper line-ending rules. [`.gitignore:1-33`; `.gitattributes:1-2`]

## Approved ambiguity resolution

D-001 through D-007 resolve the prior logging, security, Maven repository, quality-exclusion, Docker, Kubernetes, and OpenAPI-server ambiguities for version 1.0.0. There are no unresolved extraction ambiguities in this revision. The security decision remains explicitly temporary.
