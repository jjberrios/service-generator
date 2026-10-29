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

## Non-HTTP consistency gate

`sparx-target-authority.yml` must have the correct target and a resolved selection.
`consistency/batch-review.yml` must have:

```yaml
reviewed: true
reviewedBy: <semantic reviewer>
reviewedAgainst:
  serviceSpecSha256: <hash>
  sparxSpecSha256: <hash>
  authoritySha256: <hash>
  archetypeSha256: <hash of selected archetype.yml>
findings: []
```

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
