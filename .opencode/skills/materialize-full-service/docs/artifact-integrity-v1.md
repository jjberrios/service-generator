# Shared artifact integrity — version 1

Implemented in `service-workspace/scripts/artifact_integrity.py`. This core owns
paths, hashes and publication only. It contains no JPA/JDBC/SFTP, logging, quality,
contract or business conventions. Those remain in independent profile adapters.

## Fingerprints

`archetype_hashes` returns version 1 plus separate technical and documentation
SHA-256 values. The technical allowlist is `archetype.yml` and its declared
`templateInventory` (identity schema) or `template_inventory` (legacy adapter).
Documentation is limited to existing `decisions.md`, `generation-rules.md` and
`conventions.md`. Each digest binds sorted relative paths and content hashes.
The planner's single compatibility fingerprint hashes this versioned mapping,
so approved decision changes still invalidate a plan.

Caches, unrelated local files and other archetypes are never walked or hashed.
`application*.properties` is excluded by basename before stat/open; its absence
or local content cannot invalidate a plan. Declared paths reject traversal,
symlinks, junction redirection, duplicates and missing artifacts. JDBC and legacy
assembly render the same declared template allowlist, not arbitrary local files.

Old all-tree fingerprints are intentionally stale: replan against the currently
reviewed inputs. Never rewrite their stored hash to make a gate pass, and never
change an archetype's approved decisions or templates as a migration shortcut.

## Preflight and publication

All three FULL materializer profiles share `prepare` and `publish`:

1. Resolve safe paths and reject protected configuration before content access.
2. Validate existing manifest provenance against a recorded materialization report,
   when available. A changed manifest needs exact-content overwrite authorization.
   Metadata authorization never authorizes its payload implicitly: after a known
   manifest change, existing payload files need their own content-bound approvals.
   Historical manifests without a report remain readable through the legacy
   protection contract; no retrospective provenance verification is claimed.
3. Evaluate the **entire** generated payload using `file_protection`, including
   identical untracked/manual/user-owned files; do not adopt them silently.
4. JDBC and batch reject obsolete tracked paths instead of deleting them. The
   legacy adapter preserves its existing retained/partial-generation semantics.
5. Recheck preflight immediately before publishing, then `guard_write` each file.
6. Stage unique same-directory files, flush/fsync and atomically replace each file.
   Write the guarded generation manifest last as the payload commit marker.

JDBC/batch manifest rows use stable `action: generated`, independent of whether
the output already exists. Legacy plan-owned action semantics are preserved.
Operational reports may differ in `written`/`unchanged`; those are observations,
not reproducibility claims about a report across different filesystem states.

The FULL entry point serializes writers per service through an exclusive lock
under `.factory/.locks/`, after the gate clears; different services remain
independent. The gate is rechecked inside the locked operation. A stale lock is a
technical error requiring inspection, never silently discarded. Use the documented
`workspace_cli.py materialize` entry point, not private backend functions.

Publication is **per-file atomic, not a directory-wide transaction**. A crash can
leave some updated files with the previous manifest. Such files fail protection
checks on resume rather than being adopted or rolled back over possible user work.
No automatic rollback or deletion of manual content is performed. The lock
serializes cooperative generators; it cannot prevent simultaneous human edits.

Planning parameters and plans use the same unique atomic-file writer, with the
plan last and parameter hashes derived from the exact serialized bytes. A crash
between replacements produces stale bindings, not successful validation. JDBC
additionally rebuilds the complete expected plan and parameters from the current
service specification/configuration/archetype; tampered inventories, outcomes,
assumptions or parameter values fail before writing output. Batch retains its
existing independent recomputation; the legacy adapter retains its own validation.

## Evidence and limits

Synthetic tests: `service-workspace/tests/test_artifact_integrity.py` and
`materialize-full-service/tests/test_jdbc_independence.py`, plus the existing
legacy and batch suites. Tests cover exclusive locks, atomic failure cleanup,
protected/unowned read sentinels, path rejection, manifest provenance, identical
manual content, exact inventories, JDBC recomputation and idempotent manifests.
No test authorizes a real service, Maven, network, Oracle, deployment or runtime
compatibility. Source references and real output directories are not modified.

Legacy official Maven integration tests now require an explicit
`SERVICE_GENERATOR_AUTHORIZED_MAVEN_TESTS=1` opt-in in addition to installed tools;
ordinary discovery must never infer authorization from tool availability.

### Package 6 verification — 2026-10-30

- Full materializer suite: `python -m unittest discover -s
  .opencode/skills/materialize-full-service/tests -v`: 276 tests, 270 passed,
  6 skipped, no failures/errors (767.083 seconds). Five official Maven tests
  were skipped without explicit authorization; one batch compilation/JUnit test
  was skipped because JSch was unavailable locally.
- Workspace suite: 68 tests passed, including 11 shared-integrity tests.
- Additional focused suites: planning 22 passed; extraction inventory 10 passed.
- The successful full run supersedes the earlier timed-out runs and the stale
  source-location assertion corrected to verify the shared guarded publisher.
  Synthetic legacy javac/JUnit checks passed; this is not evidence of Maven,
  Checkstyle, JaCoCo, Oracle, remote SFTP or a real service's runtime compatibility.
- An earlier inherited test run incorrectly initiated offline Maven based on
  tool availability. It was interrupted and excluded from package evidence;
  the explicit opt-in above prevents recurrence in ordinary discovery.
