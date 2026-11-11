# Performance and bounded parallel execution

These controls optimize engineering work, not source ownership or authorization.
Normal service generation does **not** run the generator's global regression
suite. Maven, databases, real integrations and deployment still require their
separate explicit authorization.

## Routine generation

- Reuse hash-current target analysis rather than repeating interpretation on an
  unchanged resume. A missing/unsupported backend is a technical failure, not a
  reason to repeat unchanged source analysis or ask the same engineering question.
- The orchestrator may delegate independent bounded work with **disjoint output
  artifacts**. OpenAPI normalization, bounded Sparx discovery and capability
  checks can overlap when their inputs are available. Interpretation depending
  on selected authority waits for that authority. Consolidation, planning,
  reviews and canonical publication remain dependency-ordered single-writer work.
- Separate services have separate workspaces. A unique sandbox per invocation
  prevents one runner from deleting another runner's links; it does **not** make
  two writers to the same canonical artifact safe. Do not parallelize publication
  or two validators/materializers that compete for the same materializer lock.

## Freshness-preserving reuse

`artifact_reads.py` prefers PyYAML's safe C loader when available, otherwise the
safe Python loader. Selection documents retain duplicate-key rejection. Parsing
is reused only within an outer invocation, keyed by supplied **live bytes**, with
independent returned objects and a bounded parsing cache. There is no persistent
filesystem/mtime cache and no stored `CLEARED` verdict is trusted.

For batch, preflight and materialization share a pure prepared plan/render when
the exact current plan/spec/planning-input bytes, declared template bytes and
actual template membership match. This eliminates the second planning/rendering
pass in a single materialization. The live consistency gate, review bindings,
parameter checks and manual-file protection still execute. Immediately before
publication, the gate and input snapshot/template integrity are checked again.
No prepared payload is shared between independent invocations. Other backend
renderers retain their existing execution paths.

Typed-backend discovery similarly reuses AST parsing only for current source
bytes within the invocation. The validator reads each manifest row and Java
source once for its own checks, rather than rereading to format diagnostics.

## Runner timing, cancellation and state

`workspace_cli.py run` records metadata in
`.factory/services/<service>/runs/<run-id>.json`: run identifier, known phase,
script basename/skill, elapsed seconds, exit code and outcome. It records **no
arguments, output, credentials or complete paths**. Recording is best effort and
cannot change the command outcome or grant authority. These records cover sandbox
script execution, not LLM reasoning, permission waiting or every direct CLI action.

The runner has a default 900-second timeout; set a bounded value before the
service/script arguments when the phase needs a different budget:

```text
python -B .opencode/skills/service-workspace/scripts/workspace_cli.py run --runner-timeout 120 <service> .opencode/skills/<skill>/scripts/<script>.py <script-arguments>
```

Valid budgets are 1–86400 seconds. A timeout returns CLI code 124, attempts to stop
the child process tree and cleans only that invocation's sandbox. This is ordinary
process cancellation, not containment of hostile detached processes. Inspect the
run record before retrying; do not restart an entire suite blindly after a timeout.

Checkpoint updates use a short independent lock and unique atomic replacements.
Cooperating `set_state`/`complete_phase` updates preserve concurrent unrelated
fields. Explicit full replacements still require a current snapshot, and external
manual writers must serialize too. Locks are never automatically removed as stale.

## Explicit developer regression

```text
python -B tools/run_tests.py --list
python -B tools/run_tests.py --module .opencode/skills/materialize-full-service/tests/test_batch_shell.py --timeout 900
python -B tools/run_tests.py --skill service-workspace --jobs 4 --timeout 900
python -B tools/run_tests.py --all --jobs 4 --timeout 900
```

The runner requires an explicit selection. `--list` does not import tests. Jobs
run in separate interpreters, never threads sharing test `sys.path`/`cwd` state.
Timeouts stop the process tree; failures/skips and wall/module-seconds are reported.
Segments are actual skills/modules/classes, not an unverified classification of
all tests as fast/integration/Java. Existing optional execution prerequisites and
Maven opt-ins remain unchanged. This runner is not called by service generation.

## Measured result and limits

The batch suite previously discovered 101 cases, including 64 inherited repeats.
It now discovers the same **37 unique scenarios**, with shared setup in a fixture
that has no executable tests. In the local validation recorded during this change,
the old suite took 711.432 seconds (five repeated skips); the optimized suite took
64.456 seconds (one skip). This compares combined deduplication and implementation
changes on this checkout, not a controlled end-to-end generation benchmark.

Additional tests check current-source invalidation, new undeclared templates,
manual files created after preview, duplicate selection keys and invocation
isolation. Do not claim a one-hour generation is now a fixed duration: interpretation,
backend support, input size and real external validation remain variable. General
typed behavior IR expansion is a separate feature, not silently enabled here.
