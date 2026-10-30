---
name: materialize-full-service
description: Deterministically materializes the supported Java components of a FULL implementation plan into output/<service>/ behind the mandatory consistency gate and file protection; validates generated services generically and runs a preventive style lint (never the official Checkstyle).
---

# Materialize FULL service (v5)

Shared integrity controls for all FULL profiles are documented in
`docs/artifact-integrity-v1.md`: declared-inventory fingerprints, whole-payload
file protection (including identical user-owned content), service-scoped writer
locks, unique atomic replacements and guarded manifest-last publication.
Old all-tree fingerprints require replanning, never silent hash refresh.

## Scope of baseline-specific rules

Select the backend from the selected archetype's supported profile. The JPA,
ActivityLogger, D-011 through D-014, Checkstyle and legacy Maven assembly sections
below describe `claro-spring-ms/1.0.0` only. JDBC/WAR and batch use their own
documented adapters and conventions. Shared gates, file protection, provenance
and honest validation reporting apply to every profile. No Maven goal is implicitly
authorized by this skill. A quality tool absent from the selected baseline is
`not-applicable`, never `passed`; a required unexecuted tool stays `unverified`.

Scripts (`.opencode/skills/materialize-full-service/scripts/`): `full_materializer.py`, `renderers.py`, `validate_generated_service.py`, `style_lint.py`.
Run through `python .opencode/skills/service-workspace/scripts/workspace_cli.py materialize <service> [--supported-only] [--dry-run]`.

## Controls (nothing is written before all pass)
1. The Sparx/Swagger consistency gate is recomputed and must be CLEARED (a blocked service writes no Java and leaves its workspace untouched). The skill is registered as post-gate, so the sandbox runner refuses it too.
2. The workspace plan must be a ready full plan of this service, built from the current workspace `service-spec.yml` and the current archetype fingerprint; planned paths must be relative and safe.
3. Components outside the supported set stop the operation (exit 4, nothing written). `--supported-only` writes only the supported ones and marks the manifest `complete: false`.
4. Every file goes through `file_protection`: manual, untracked or user-owned content is preserved (exit 3, nothing written) unless an authorization bound to its exact content exists; `application*.properties` is never read, listed, written or blocking.
5. `guard_write` is re-checked immediately before each write; writes are atomic and recorded with hashes in `.generation-manifest.yml`. The orchestrator has no edit permission on `output/**`.

Same plan + archetype + workspace spec (and retained inputs) => identical generated
payload and manifest bytes (UTF-8, LF, no timestamps). Operational reports honestly
distinguish `written` from `unchanged`; their bytes may change on a repeat run.

## Supported in v2 (`full-materializer-2`)
Foundation (v1): `archetype-activity-logger`, `archetype-activity-logger-test`, `activity-constants`, `request-headers-model`, `internal-typed-exception`, `jpa-entity`, `spring-data-jpa-repository`.
Functional layer (v2), all rendered by pure functions of a typed model extracted from the plan (`service_model.py`, `java_components.py`, `java_components2.py`):
`contract-dto` (request DTOs with `@JsonInclude(NON_NULL)`, `@JsonSetter(nulls=FAIL)`, enum `@Schema`; presence tracking only for DTOs used by an update), `contract-api-interface` (mappings, Operation/ApiResponses from the effective statuses,
parameter constraints, `@Validated`), `controller-implementation` (RequestHeaders from the header roles, entry log), `application-service-contract/implementation` (ActivityLogger activities, `ejecutarActividad`, data-access error logging, 404 from the plan),
`business-validator` (typed command records, `Field<T>` presence wrapper, lossless numeric conversions with precision from the column type, enum checks, plan rules), `explicit-contract-data-mapper`, `jpa-specification` (OR/AND policy, exact/contains),
`internal-query-model`, `offset-based-pageable`, `data-access-error-translator`, `central-contract-error-advice` (statuses, types, subtypes and details taken verbatim from the contract examples).
Supported pattern: one JPA entity with a Long IDENTITY key; at most one search (GET, no body), any number of inserts and presence-aware updates by identifier; validation rules `pagination-pairing`, `conditional-required`, `at-least-one-of`.

## Not supported (the WHOLE generation stops, nothing is written)
`repository-persistence-test` (needs an in-memory database absent from the approved POM; adding one needs authorization), test files whose name matches no generator, `remove` actions, other key/column types, enum parameters, cookie parameters, second search operation, write responses with extra fields (for example a generated id: needs an approved decision), unknown rule kinds or filter matches,
activity flows other than validation+behavior, an empty-result or not-found outcome the contract does not declare, a success message absent from the contract example. `--supported-only` writes the supported files and marks the manifest `complete: false`.

## Assumption register
`assumptions-register.yml` (workspace) lists every implemented rule by source: `sparx`, `swagger`, `human-decision`, `archetype-technical`. Human decisions the plan relies on must exist as approved reviews in the workspace. Functional assumptions
(service-spec `derivedAssumptions` with a blocker or a non-technical classification, or plan blockers) are `pending-functional`: they stop the generation until an approved decision resolves them; they are never turned into a business rule.

## Generic validator
`validate_generated_service.py <service> [--write-report]` checks: planned inventory (partial runs against the supported subset), unplanned Java, manifest rows/tree hash/input hashes,
Java structure (package vs path, type vs file, braces, imports), planned JPA and logging components, inactive operations never generated (plan and approved decisions), and that no Java
exists while the gate is not CLEARED. No fixed class names or counts. The official Checkstyle gate is always reported `unverified`.

## Preventive style lint
`style_lint.py <output-dir>` flags annotation-array indentation (annotation +2 or +8), magic numbers (ignore list read from the project's checkstyle.xml), whitespace around
keywords/operators/`switch`, declaration/use distance, line length, star/unused imports and missing braces, for `src/main/java` and `src/test/java`. It is heuristic and NEVER replaces
the D-014 Maven Checkstyle gate (`checkstyleOfficial: not-verified`).

## Tests
`python -m unittest discover -s .opencode/skills/materialize-full-service/tests` (synthetic services in temporary directories only).

Official offline Maven test groups are opt-in: they are skipped unless a human
explicitly authorizes Maven and sets `SERVICE_GENERATOR_AUTHORIZED_MAVEN_TESTS=1`.
Having Maven installed is not authorization. Never set that flag automatically.

Optional compile evidence: `test_generated_java_compiles_with_javac_against_local_jars_without_running_maven` compiles synthetic output with `javac` and the jars of the local Maven cache (Lombok as processor). It is NOT Maven, Checkstyle or JaCoCo.

## Generated tests (P2; `full-materializer-3`, current `full-materializer-4`)
Planned `unit-mapping-persistence-test`, `controller-contract-test` and `activity-logging-test` files are rendered by `test_components*.py` (dispatch by file-name stem in `test_support.py`; tests mirror the target package):
validator (rules, conversions, precision, enums), mapper (presence-aware patch), specification (Mockito Criteria mocks), service (Mockito repository + real validator/mapper/translator, activity logging), controller contract (MockMvc standalone with
`LocalValidatorFactoryBean` and the real advice: success, declared statuses, header roles, required headers, malformed body, null field), advice (contract texts only), corporate logging (logback `ListAppender`) and entity mapping.
Expected texts/statuses come only from the plan/contract; numeric literals respect the D-014 magic-number list; no literal log-text assertions.
Registers written to the workspace: `tests-traceability.yml` (rule id -> test methods; uncovered rules carry a reason, never invented tests) and `coverage-scope.yml` (JaCoCo scope from the generated/archetype POM: threshold, exclude globs
translated with JaCoCo semantics, measured vs excluded classes, risks; status is always `not-verified`: JaCoCo/Maven were not executed and no percentage is claimed).
Honest limits: tests were executed only with `javac` + a JUnit Platform launcher against local jars (not Maven, Checkstyle or JaCoCo). `@DataJpaTest` persistence tests are unsupported until a test database dependency is explicitly authorized.

## P3 (`full-materializer-4`)
- **Declared constraints are executed** (`test_components4.py`): `@Size/@Min/@Max/@Pattern` on path/query parameters run through Hibernate Validator method validation on the generated controller (`validateParameters` against the API interface method);
  `@NotBlank/@Email/@Size/@Pattern` on String request-DTO fields run through bean validation. Per constraint: valid boundary, invalid beyond-boundary, absent optional parameters. Samples come only from the declared values; a pattern with no derivable sample is
  listed in `tests-traceability.yml` as uncovered (or with a `gaps` note when only one side could be sampled). Constraints declared on header parameters are not applied by the generated API interface, so they are reported uncovered with that reason.
- Numbers in `@Size/@Min/@Max` that the reference Checkstyle `MagicNumber` does not ignore become named constants (`public static final` in the API interface, `private static final` in DTOs). Limits are unchanged.
- **Injectable Clock**: only for services that stamp audit dates. `private Clock clock = Clock.systemDefaultZone()` plus `@Autowired(required = false) void setClock(Clock)` (no new bean, no plan or archetype change); the zone policy is the previous `ZoneId.systemDefault()`.
  Tests use `Clock.fixed` (UTC and Asia/Tokyo) and also check the default clock. SYSDATE is NOT used and the database is untouched.
- **Reports**: `coverage-scope.yml` v2 adds components with generated tests, covered/uncovered rule counts and list, excluded/measured packages, pending persistence tests, tool states (maven `not-executed`, official Checkstyle `unverified`, JaCoCo `not-verified`),
  compilation/tests (`not-executed` unless `execution_evidence.py` recorded a real javac/JUnit-launcher run bound to the exact generated tree; becomes `stale` when the tree changes; Maven/Checkstyle/JaCoCo can never be recorded) and limitations.
  `validate_generated_service.py` exposes it as `validationScope` and fails if a tool status is overstated.
- Evaluated, NOT implemented (P3.3): Slice / COUNT-free pagination. See the P3 analysis: Spring Data already skips COUNT on partial pages; full pages still count; arbitrary offsets need `scroll(OffsetScrollPosition)` or a custom fragment.

## Maven project assembly (`full-materializer-5`, `assemble_project.py`)
`materialize` now also assembles the technical files of the archetype (token substitution only; POM, Checkstyle and JaCoCo rules are never edited) behind the same gate, `guard_write` and manifest:
build (`pom.xml`, `settings.xml`, `.gitignore`, `.gitattributes`, `.mvn/wrapper/maven-wrapper.properties`, `mvnw`, `mvnw.cmd`, `checkstyle.xml`, `logback.xml`), Java (application class, `OpenApiConfig`, `SecurityConfig`, `JwtRequestFilter`, `JwtValidatorService(+Impl)`)
and, only when the plan says `deploymentGenerationAuthorized: true`, `Dockerfile`, `Jenkinsfile` and `config/*.j2`. `--no-assemble` keeps the Java-only behavior.
- Parameters: `plan.service` (name, package, packagePath, groupId, projectVersion, applicationClass) + `values` of the workspace `generation-parameters.yml`. Only approved derivations: group id = base package and version `1.0.0-SNAPSHOT` (D-010), artifact id = service name.
  A missing parameter (`missing-parameter`), an invalid form (`invalid-parameter`), a plan/parameter disagreement (`parameter-conflict`) or any unresolved `__TOKEN__` (except the 3 official Maven Wrapper identifiers) stops everything before a write (exit 3).
- Files that exist in the output but are not tracked by the manifest are kept as they are (`retainedExisting`); tracked files modified by hand block the run (`protected-files`).
- `src/main/resources/application*.properties` is never read, copied or written. A new project must get its baseline (archetype `runtime.application_properties`) provisioned outside the generator; secrets (`JWT_SECRET_KEY`, `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`) are environment-only.
- `file_protection.norm` no longer strips the leading dot of dot files.

## Official validation evidence (`validation_evidence.py`)
`run <service> --workdir <temp> --authorized-maven` copies the manifest files of the project to a temporary directory, runs `mvn -o -B -s <project settings.xml> verify` there (never inside `output/`) and records what the reports say
(`validation-evidence.yml`): Maven exit/BUILD result, compilation, surefire counts, Checkstyle violations (`checkstyle-result.xml`), JaCoCo per-package ratios (`jacoco.csv`) against the threshold read from the project POM. `ingest` records an existing build only when its files match the manifest hashes.
Evidence is bound to the SHA-256 of the exact project; a different tree makes every tool `stale`. `coverage-scope.yml` and the generic validator follow the evidence (`verified-by-maven-evidence` only with a fresh JaCoCo `passed`); no evidence means `not-executed`/`unverified`/`not-verified`.

## application.properties.example and header constraints (`assemble-project-2`)
- `src/main/resources/application.properties.example` is assembled from `archetype.yml#/runtime/application_properties` only (static values, parameterized `service_name`/`base_package`/`jwt_roles_claim`, environment-only secrets as `${JWT_SECRET_KEY}`, `${DB_URL}`, `${DB_USERNAME}`, `${DB_PASSWORD}`),
  grouped in the baseline blocks (APPLICATION, LOGGING, SWAGGER, ACTUATOR, DATA SOURCE, HIKARI, JPA / HIBERNATE, JWT TOKEN, SPRING CLOUD). It goes through `guard_write` and the manifest; a missing parameter stops with `missing-parameter`. The real `application.properties` is still never read, created or touched.
  Real configuration: copy the example to `src/main/resources/application.properties` outside version control, review values per environment and export the four environment variables.
- Header constraints declared in the contract (`@Size/@Pattern/@Min/@Max`) are now emitted on the API interface parameters (required-ness was already enforced). Tests: method validation on the interface plus MockMvc with the controller behind `MethodValidationInterceptor`
  (what `MethodValidationPostProcessor` does in production): invalid header -> 400 and no service call, boundary header -> 200. Valid requests send header values that satisfy the declared constraints. Rule ids `<op>:param:<header>:<Annotation>`.
  Not supported (stops with a reason, never guessed): constraints on non-text headers, `@Min/@Max` on a header, patterns with no derivable sample.

## Profile dispatch (per archetype)

JDBC/WAR now uses `jdbc-war-materializer-3-explicit-bindings` and
`docs/jdbc-binding-v1.md`. Legacy inferred JDBC plans stop before writes; target
class names, procedure mappings/order and outcomes must be explicit. No
claro-post-atencion decisions or pending-operation exception are defaults for
other targets. Existing target outputs/decisions remain unchanged. The profile's
older v2 description below is historical externalization/style context, not
permission to consume an inferred plan.

Profile `batch-shell-jar-spring-xml-log4j-sftp-junit4` dispatches to
`batch_shell_materializer.py` + `batch_shell_plan.py`. It preserves Spring XML, Java 8,
log4j, the reference utilities, external properties, JUnit4/Mockito and the shaded JAR POM.
No HTTP, JPA, Boot, ActivityLogger, scheduler or Checkstyle is introduced. Full assembly
only: `--supported-only` and `--no-assemble` are rejected for batch. All unsupported
behavior fails before writes. See `docs/batch-shell-contract.md` for the bounded SFTP IR,
semantic review, authorization, input hashes and tests. `validate_generated_service.py`
also validates batch via a side-effect-free materialization preview; Checkstyle is N/A.

The backend is selected by the archetype's `generation.profile` (`profiles.py`), never fixed. Profile `war-jdbc-callablestatement-junit4` (claro-spring-java-8) is implemented by `jdbc_war_plan.py` + `jdbc_war_materializer.py` (`jdbc-war-materializer-2`): JDBC CallableStatement over JNDI, Java 8, JUnit4/Mockito, no JPA/ActivityLogger/Checkstyle.
- The profile must declare `generation.style` (constants class, external-properties class, JNDI key, `hardcodedLiterals: forbidden`); the planner stops without it.
- Generated main code contains no string literal outside `common.property.Constantes`, `common.property.PropertiesExternos` and `repository.JdbcConfig` (`style_violations`; the materializer fails otherwise). Environment/operation values (SP owner/package/name, execution timeouts, response codes/messages, JNDI) are `@Value` fields of `PropertiesExternos`.
- The materializer writes `<workspace>/required-properties.yml` (keys + suggested values from OpenAPI/Sparx) for the operator; it never writes or reads `application*.properties`.
