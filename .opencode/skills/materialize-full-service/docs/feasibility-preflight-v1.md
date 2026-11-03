# FULL feasibility preflight v1

Run `workspace_cli.py preflight <service>` after planning. YAML goes to stdout
(exit 0 feasible, 4 otherwise); no files are written. Materialization recomputes
it before publication, never trusting saved verdicts. No checkpoint, approval,
consistency gate or historical output is changed.

Contract: `schemaVersion: 1`, `service`, selected `profile` and `archetype`,
`inputFingerprints` (explicit workspace artifacts, declared archetype inventory,
backend/planner Python), deterministic content-derived `runId`, `requirements`,
`status`, `feasible`, `limitations`, optional `backendPreview`.
Each requirement has `id`, `kind`, `required: true`, `status`, `evidence`.
Statuses: supported, unsupported, unknown, blocked. Only all supported is feasible.

The earliest reliable full assessment is after planning: materializable bindings,
inventory and parameters are not available beforehand. Capabilities come from
the existing registry and actual backends' read-only previews, not a second
matrix. JPA checks each operation model and all file generators, then the complete
model. JDBC and batch reuse planner reconstruction and complete rendering.
Incomplete JDBC operations, batch structure/ports scopes and omitted behavior
are rejected independently of historical approvals. `--supported-only` is rejected.

A backend may fail on its first malformed contract or cross-operation constraint;
other unverified requirements stay unknown. Diagnostics enumerate omissions and
JPA file support, but cannot promise every error in malformed input. Compilation,
tests and real integrations still require separately authorized validation.
Static feasibility is not runtime proof. Existing runtime guards remain.

Private `_materialize_checked` / `_materialize_unlocked` functions are shared
implementation details. Public materialize functions and CLI enforce preflight;
there is no public skip option or partial-generation mode.
