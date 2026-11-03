# Batch shell backend v1

Profile: `batch-shell-jar-spring-xml-log4j-sftp-junit4`.

The selected versioned archetype owns all technical choices. This backend preserves
its Java 8 / Spring XML / log4j / JUnit4+Mockito / shaded JAR templates and utilities.
It does not reread the reference, enable/freeze an archetype, analyze raw Sparx prose,
execute Maven, connect to SFTP or fabricate a Swagger contract.

## Workspace inputs

`.factory/services/<service>/service-spec.yml`:

- `service: {name: <service>, profile: batch-shell}`.
- `readiness.strictImplementationReady: true` and
  `readiness.functionalCodeGenerationReady: true`. No blockers, incomplete operations,
  unresolved evidence/conflicts, HTTP operations or inactive operations.
- `batch`: the normalized IR below, exactly equal to `sparx-spec.yml#/batch`.
  This is a backend input schema, not an automatic raw-Sparx interpreter.

`service-generation-state.yml`: `targetService` and `archetype.path` select the
approved baseline. It must independently have `identity.generationEnabled: true`.
The real `claro-java-8-shell/v1.0.0` remains disabled pending explicit authorization;
only synthetic test copies enable it.

`full-planning-input.yml` contains only:

```yaml
target:
  service: batch-example
  archetype: archetypes/claro-java-8-shell/v1.0.0
  output_directory: output/batch-example
template_parameters:
  GROUP_ID: pe.com.claro.shell
  ARTIFACT_ID: SH_Example
  PROJECT_VERSION: 1.0.0
  BASE_PACKAGE: pe.com.claro.shell.example
  MAIN_CLASS: ExampleMain
  SERVICE_INTERFACE: ExampleService
  PROPERTIES_FILE_BASENAME: Example
```

The two remaining archetype parameters (`BASE_PACKAGE_PATH`, `SERVICE_FIELD`) use
the declared derivations. No guessed coordinates or environment defaults.

## Closed normalized IR (`batch.version: 1`)

Every property, connection, step and outcome has a nonempty `evidence` list such as
`[ea#activity42]`. Every reference must resolve to a source binding id. The binding
contains `{id: ea, path: input/sparx/.../page.htm, sha256: <64 hex chars>}`.
Paths must be relative, inside the Sparx root, with current hashes. The semantic
review is responsible for verifying the meaning of the cited fragment; hashes alone
do not prove semantic correctness.

Required sections:

- `sourceBindings`: nonempty list of `{id, path, sha256}`.
- `properties`: list of `{key, field, secret: true|false, evidence}`. Keys are dotted
  lowercase names; fields are distinct Java identifiers. All values come from the
  environment operator, never the planner or inline Java. Generic reference keys
  (`log4j.file.dir`, `idf*/idt*.codigo/mensaje`) already exist in the template.
- `connections`: list of `{id, username, host, port, password, credentialMode,
  evidence}`. The four connection fields reference declared property keys.
  Password properties must be secret. Only explicitly specified
  `credentialMode: resolved-external` is supported: a usable credential is supplied
  externally. **This does not implement or bypass a specified SOAP decryptor**;
  encrypted/decryption flows fail as unsupported.
- `outcomes`: `{success, sftpFailure, generalFailure, evidence}`. Each outcome names
  an existing external property group (`idf0`, `idf1`, `idt1`, `idt2`, `idt3`).
  No invented numeric codes/messages, HTTP statuses or process exit codes.
- `steps`: nonempty ordered list. Every step has unique Java-identifier `id`, `kind`,
  `evidence` and exactly the following fields (unknown fields/kinds block):

| kind | Additional required fields |
| --- | --- |
| `connect`, `disconnect` | `connection` id |
| `list-mtime`, `list-name` | `connection`, `remoteDirectory`, `date`, `dateFormat`, `onFailure: abort`, `emptyPolicy: success|abort` |
| `for-each` | `list` (prior list step id), nonempty `steps` |
| `download`, `upload` | `connection`, `remoteDirectory`, `localDirectory`, `filename`, `onFailure: abort` |

Directory/date/format/filename operands reference non-secret property keys, except
`filename: $item` inside a loop. Upload reads `localDirectory + filename`; the extracted
utility uses directory concatenation, so operators must provide the required trailing
separator. List date semantics and technical risks are those of the extracted utility
(including current-date fallback for an empty date); the reviewer must confirm that
the target behavior matches. A filename-list uses substring matching, not a regex.

Connect precedes use; disconnect ends use. No connection lifecycle changes or nested
lists/loops inside loops. Unused connection declarations block. Remaining connections
are closed in `finally`. Null listing / unsuccessful transfers abort according to the
explicit policy; outcomes are logged and not propagated, as in the reference.

No raw Java snippets, arbitrary expressions, SOAP/decryption, persistence, retries,
new file filters, midnight business windows, branching or inferred error policy.
Unknown requirements stop the whole generation, never become stubs or empty success.

## Non-HTTP flow (package 7: no OpenAPI, no gate cycle)

1. Authority without OpenAPI: `python .opencode/skills/parse-sparx/scripts/resolve_target_authority.py input/sparx <ws>/sparx-target-authority.yml --target <exact Sparx element name> --non-http` (exactly one of `--openapi` / `--non-http`). The gate rejects an authority that was not produced this way (`kind: sparx-target-authority`, no OpenAPI source). The authority target is the Sparx element name; the gate compares it with the service name ignoring case/punctuation.
2. The normalized candidate is `<ws>/sparx-spec.yml` (`service`, `batch`, optional `warnings`). The gate evaluates this candidate, so it can be CLEARED **before** `service-spec.yml` exists.
3. After the gate is CLEARED, run `workspace_cli.py run <service> .opencode/skills/reconcile-service-spec/scripts/consolidate_batch_spec.py`: it copies the approved IR into `service-spec.yml` (readiness and `unresolved: {}` added; no behavior added) and is refused while the gate is not CLEARED.
4. Evidence is grounded: each entry is `<bindingId>#<literal text>` and the literal (case/accent/whitespace insensitive, at least 5 characters) must occur in the visible text of the bound Sparx page (`batch_evidence.py`, enforced by the gate). A slug or paraphrase fails. Grounding proves the words exist in the cited source, not that the interpretation is right: that is still the semantic review.
5. Planning and materialization are unchanged.

## Non-HTTP consistency gate

`sparx-target-authority.yml` must have the correct target and a resolved selection.
`consistency/batch-review.yml` must have:

```yaml
reviewed: true
reviewedBy: <semantic reviewer>
reviewedAgainst:
  sparxSpecSha256: <hash>
  authoritySha256: <hash>
  archetypeSha256: <hash of selected archetype.yml>
findings: []
```

When `service-spec.yml` already exists its `service` and `batch` must equal the candidate's.

Pending findings block; resolve them against authoritative evidence and review again.
The backend never fills this review or approves it automatically. Human authorization
uses the existing `workspace_cli.py gate-authorize <service> --by ... --statement ...`
and is bound to the evaluation hash. Source changes invalidate release. An existing
`openapi-spec.yml` blocks instead of being silently ignored. The gate reports HTTP
comparison as **not applicable**, not passed.

## Commands and outputs

Run the usual workspace sandbox planner with `--mode full --planning-input
.factory/full-planning-input.yml`, then `workspace_cli.py materialize <service>`.
The parameter resolver dispatches to the same backend. `--dry-run` writes nothing;
partial/Java-only modes are not supported for this profile.

The plan binds spec, planning input, parameter bytes and archetype fingerprint.
Before writing, the materializer recomputes the plan from bound inputs, validates
the exact inventory, rejects obsolete tracked files requiring migration, validates
paths/symlinks and applies `file_protection`/`guard_write`. Manual/untracked/user-owned
files are never overwritten without content-bound approval. Local
`application*.properties` files are never enumerated, read or generated.

All declared templates plus service implementation and JUnit4/Mockito tests are
materialized. Tests mock the protected SFTP factory, verify success, connection
failure, per-step SFTP failures and connection cleanup. No real network is used.
Generated tests are not claimed executed by materialization.

Workspace outputs include `required-properties.yml`, `assumptions-register.yml`,
`tests-traceability.yml`, `materialization-report.yml`; output has the hash manifest.
Values/secrets are operator-required; no local property files or missing external
JARs/log4j configuration are invented. The static validator checks batch through a
side-effect-free materialization preview. Checkstyle is N/A, not passed; compilation,
Maven, tests and JaCoCo remain unverified/not-run without actual evidence.

Regression fixture and safety tests: `tests/test_batch_shell.py` (temporary synthetic
repositories only). The optional javac/JUnit test skips if local dependencies are
missing; it never invokes Maven or downloads artifacts. No legacy JPA/JDBC rules are
applied to this profile.

A separate JDK parser test validates all rendered Java at source level 8 without
resolving dependencies. This is syntax-only evidence, never compilation/runtime proof.

## Scopes structure-only and ports-flow (SH-D-022, SH-D-023)

Both scopes require explicit `omittedBehavior` (`id` Java identifier, `description`, grounded `evidence`), declare no `properties`,
`connections` or `steps` and keep readiness honest: `scaffoldImplementationReady: true`, functional/strict `false` and `blockers` equal to the
omitted ids. The `sftp-transfer` and `credential-decrypt-soap` modules are pruned when unused (no unused code, SH-D-019).

- `structure-only`: `outcomes = {generalFailure, evidence}`; `run()` logs the configured failure outcome and never simulates success.
- `ports-flow`: adds `dtos` (String/Integer/Long/Boolean fields), `ports` (`db|rest|mail` with typed methods) and `flow`:
  `call` (`port`, `method`, `args`, optional `result`, `onFailure` = `abort` | `skip-item` | `log`), `for-each` (no nesting; `abort` is
  not allowed inside; each item is isolated with `skip-item`) and `if` (`<` over Integer operands or `present` over a dto variable). Every declared
  port method must be used. `outcomes = {success, generalFailure, evidence}`.
  Generated: `dto/*`, `port/<Port>` + `port/<Port>Impl` (the adapter throws `OperacionNoImplementadaException`; no SQL, HTTP, mail,
  URL or scheduling is implemented), the service flow and JUnit4/Mockito tests derived from every condition path and every failure policy
  (at most 16 paths; contradictory operand constraints are a technical error).

## Nested loops, guards and compound conditions (SH-D-027)

`for-each` may nest to depth 2 (`skip-item` applies at any loop depth; `abort` only outside loops). The `guard` step (only inside a `for-each`) skips the current item when its condition is false. Conditions (`if`, `guard`) are simple `{left, op, right?}` or exactly one of `all`/`any` over at least two simple ones. Operators: `<` (Integer), `present` (dto variable), `nonempty` (list variable), `equals` (Integer/Long/String with literal `right`), `true` (Boolean). Tests are derived per condition path (max 16; contradictory constraints on one operand are a technical error). REST methods may return `Boolean` with optional `okStatus` (extra accepted HTTP codes besides 2xx); any communication error yields `false`.

## Adapters (ports-flow, SH-D-024)

`batch.adapters` (optional, ports-flow only) gives each port a concrete implementation: `db` methods declare `sql`, `bind` (`arg` or `arg.field`), `result` (none|scalar|single|list) and `columns`; `rest` methods declare `httpMethod` (GET|POST|PATCH), `path`, `query` and `body` items (`json` plus exactly one of `from` or literal `value`); `mail` methods declare `placeholders`. Every method is `assumed: true` with Sparx literal evidence and each adapter implements all methods of its port. Generated: `util/ConexionBd` (plain JDBC, external driver), `util/RestClienteHttp` (Apache HttpClient + Jackson), `<Port>Impl` adapters, JUnit4/Mockito tests for db and rest (not mail). Environment values (`bd.*`, `rest.<port>.url`, `rest.timeout.ms`, `mail.*`) are blank external properties listed in `required-properties.yml`; extra POM dependencies are justified additions (baseline never pruned). Assumptions are recorded in `assumptions-register.yml`; readiness stays partial and scheduling is external. No Maven, network or runtime verification.
