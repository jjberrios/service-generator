---
name: parse-sparx
description: Use when deterministically indexing Sparx Enterprise Architect HTML exports or, in a separately authorized future stage, interpreting indexed Sparx evidence into semantic behavior.
---

# Parse Sparx

This workflow separates collection of source evidence from interpretation of
that evidence. Never combine the stages implicitly.

## Inputs And Invariants

Target-local exports may live directly at `input/sparx/`; no PROJECT/PROYECT
subfolder is mandatory. Use the workspace resolver and preserve its actual root.
For HTTP services without Swagger use `resolve_target_authority.py --sparx-only`
and the evidenced contract format in `service-workspace/docs/sparx-only.md`.
`--non-http` remains exclusive to genuinely non-HTTP services.

For every service with Sparx, WITH or WITHOUT Swagger, attachment review is
mandatory; Swagger never replaces the attached functional documentation.
Target-local detail extraction also inventories attached documents with
`sparx_attachments.py` into `sparx-attachments.yml`. Review these as source
evidence: HTML embeds, linked DOCX/PDF/text documents, their exact quotes and
page/paragraph/section locators. No remote fetch, document execution, macros or
general link crawl. Unsupported or missing documents stay unverified. PDF text
extraction uses an already-installed optional `pypdf`; no dynamic installation
or implicit OCR. All selected branch pages are checked, not the whole export.

Establish:

- `<source>`: one Sparx HTML export directory under `input/sparx/`, read-only;
- `<index-output>`: `.factory/sparx-index.yml`;
- `<index-script>`: `.opencode/skills/parse-sparx/scripts/index_sparx.py`;
- `<context-output>`: `.factory/sparx-context.yml`;
- `<context-script>`: `.opencode/skills/parse-sparx/scripts/select_sparx_context.py`;
- `<stage>`: `index`, `select-context`, or, only when separately authorized,
  `interpret`.

Read repository-root `AGENTS.md` first. Resolve paths before reading or writing.
Never modify `<source>`, an archetype, an OpenAPI artifact, or a generated
service. Never execute exported scripts, evaluate event handlers, access the
network, or follow a local reference outside `input/sparx/`.

## Stage 1: Deterministic Indexing

Stage 1 is implemented by `index_sparx.py`. It records source-observable HTML
structure and raw text. It does not determine business meaning.

### Preflight

1. Verify `<source>` exists, is a directory, and resolves under
   `input/sparx/`.
2. Verify `<index-output>` has a `.yml` or `.yaml` suffix and resolves to a file
   under `.factory/` without overlapping `<source>`.
3. Reject symlink or `..` traversal outside either approved root.
4. Record the repository-relative source path.
5. Confirm `.factory/sparx-spec.yml` is not an output of this stage.
6. Confirm no OpenAPI merge, code generation, or semantic inference is part of
   the task.

### Source Discovery And Fingerprinting

Discover source files recursively in lexical repository-relative order. Index
files whose suffix is `.htm` or `.html`, case-insensitively. Directory symlinks
are not traversed, even when they point inside the export; file symlinks are
accepted only when their resolved target remains inside the export.

Compute a deterministic SHA-256 export fingerprint from each safe source file's
relative path and content digest in lexical order. Hashing asset bytes for this
provenance fingerprint is permitted; assets are never parsed or followed during
reference resolution. The fingerprint contains no timestamp, absolute machine
path, filesystem inode, or directory enumeration order.

### Safe HTML Parsing

Use Python's standard-library `html.parser.HTMLParser` where practical. Treat
HTML as untrusted data:

- suppress all `script` and `style` content;
- ignore inline handlers such as `onclick` and `onload`;
- do not instantiate a browser or JavaScript runtime;
- do not fetch stylesheets, scripts, images, frames, or external links;
- decode HTML defensively and record fallback decoding;
- preserve partial page evidence and report parser failures.

If a future implementation requires an optional parser, fail with a clear
dependency message. Never install packages dynamically.

### Page Evidence

For every HTML page, preserve when structurally present:

- repository-relative source file;
- page identifier or GUID;
- structural anchor identifiers from HTML `id` and `a[name]` attributes;
- HTML title and heading levels/text;
- breadcrumb entries, raw breadcrumb text, and linked hierarchy evidence;
- parent/child evidence derived only from explicit breadcrumbs or exported
  project-browser structures;
- object/element name, element type, package name, and stereotype;
- Notes/documentation blocks with raw class/type, source page, containing-element
  identity, structural context, heading/property association, and deterministic
  evidence IDs; the Notes record references its text-block evidence instead of
  duplicating the body;
- textual key/value properties;
- tables with captions, context identifiers, headers, and rows;
- operation or method names only when an exported section/table explicitly
  identifies itself as operations or methods;
- activity or process names only when the export structurally labels an item
  with that type;
- diagram image/map references, including map identity and area evidence with
  shape, coordinates, href/title/alt, associated image asset, and linked page
  target when available;
- image references as metadata only;
- observable visual metadata, including CSS classes, inline style,
  fill/background attributes, direct status attributes, and legend references;
- explicit diagram legend definitions and entries when structurally labelled
  (for example by heading, id, class, role, or data reference);
- anchor and image-map links to other Sparx pages;
- cross-reference text and targets.

Preserve raw text. Whitespace may be normalized deterministically, but wording,
capitalization, identifiers, and names must not be rewritten.

An element's structural context includes its own classes as well as ancestor
classes. In particular, an `li.IndexCell` is explicit project-browser evidence,
and an image's own diagram class participates in diagram recognition. A
filename alone is never diagram evidence.

Preserve legend definitions, literal labels, visual/style evidence IDs, and
deterministic style-to-label mappings. Map a fill/background style to a lifecycle
label only when an explicit legend/equivalent metadata contains both the style
and label. Never infer lifecycle meaning from color alone. Preserve direct
status/state/lifecycle attributes and tagged properties literally; Stage 1 does
not decide whether a state is active or inactive.

Do not conclude that a text block is a requirement, rule, validation, decision,
integration, persistence action, error, or sequence merely because its prose
resembles one.

### Link Classification

Normalize each link without fetching it:

- `internal-page`: a relative `.htm`/`.html` target inside the source export,
  with `resolved` indicating whether the discovered page exists;
- `local-asset`: another safe local target inside the source export;
- `fragment`: an in-page fragment whose page resolves; anchor existence remains
  explicitly unknown unless indexed structural evidence proves it;
- `page-reference`: a query-only reference to the current page;
- `external`: an HTTP, HTTPS, mail, or other external URI;
- `blocked-file`: a `file:` URI;
- `blocked-script`: a `javascript:` or equivalent executable URI;
- `unsafe-local`: a relative path that escapes the source root;
- `unresolved`: an empty or malformed reference that cannot be classified.

Keep the original `href`, a separate normalized value, and anchor text. Resolve
the target page separately from fragment status. Never open external, blocked,
unsafe, or referenced asset targets during link resolution.

### Structural Relationships

Create parent/child relationships only from explicit structural evidence:

- linked breadcrumb order where the current page is represented; or
- exported project-browser/container lists whose items link to pages.

Record the evidence source for every relationship. Do not treat an arbitrary
cross-reference as containment.

### Stable Evidence Identifiers

Assign an `evidenceId` to every indexed heading, property, text block, table,
operation, activity, process, link, visual/style record, legend definition,
legend label/mapping, and resulting literal lifecycle-state record. Each page
exposes an `evidenceKey` in this format:

```text
page-sha256-<sha256-of-export-relative-page-path>
```

Evidence identifiers use:

```text
<evidenceKey>:<evidence-type>:<zero-based-source-index>
```

The page key hashes only the lexical export-relative page path, never an
absolute machine path. Evidence types are structural names such as `heading`,
`property`, `text`, `table`, `operation`, `activity`, `process`, `link`, `visual`,
`legend`, `legend-label`, `legend-mapping`, `lifecycle`, `note`, `image-map`,
and `image-map-area`;
they do not encode inferred business meaning. Stage 2 must reference these IDs
when citing Stage 1 evidence.

### Identifiers And Validation

Use an explicit Sparx ID/GUID property when present. If absent, use `null`; do
not fabricate a semantic identifier from the filename. Detect duplicate
non-null page identifiers and report every conflicting source file.

Report deterministically:

- malformed/unreadable HTML;
- fallback character decoding;
- duplicate page identifiers;
- unsafe or blocked local references;
- unresolved internal page links;
- files or symlinks that resolve outside the source root;
- unsupported structures retained only as raw evidence.

### Stage 1 Output

Run only when Stage 1 execution is explicitly requested:

```text
python .opencode/skills/parse-sparx/scripts/index_sparx.py <source-directory> .factory/sparx-index.yml
```

The deterministic YAML structure is:

```yaml
source:
  path: null
  fingerprint: null
  fileCount: 0
statistics:
  htmlFiles: 0
  indexedPages: 0
  internalLinks: 0
  unresolvedLinks: 0
  externalLinks: 0
  warnings: 0
  errors: 0
pages: []
relationships: []
validation:
  warnings: []
  errors: []
```

Each page uses stable fields for ID, file, title, element metadata, breadcrumb,
headings, properties, text blocks, tables, explicitly structured operations,
activities/processes, links, diagrams, image references, image maps, Notes
references, parent, and children.
Pages may additionally expose `visualMetadata`, `legends`, and
`lifecycleStates`. Their evidence IDs link visual/style observations, legend
definitions/mappings and resulting literal lifecycle labels back to source
evidence.
The page's `evidenceKey` and each applicable unit's `evidenceId` provide stable
Stage 2 traceability. Missing scalar values are `null`; missing repeated values
are empty arrays.

### Stage 1 Validation

1. Parse the generated YAML.
2. Confirm source and page paths are repository-relative.
3. Confirm page order is lexical by source file.
4. Confirm every safe discovered HTML file appears once.
5. Confirm every link retains its original text and reference.
6. Confirm external and blocked links were never fetched.
7. Confirm duplicate IDs and unresolved links are reported.
8. Confirm fingerprint inputs and ordering are stable.
9. Run twice and compare output bytes for determinism.
10. Confirm evidence IDs are identical across unchanged runs.
11. Confirm project-browser relationships require an explicit structural item,
    such as `li.IndexCell`, rather than an arbitrary link.
12. Confirm an image's own structural class participates in diagram detection,
    while its filename alone does not.
13. Confirm `<source>` is unchanged.
14. Confirm no `.factory/sparx-spec.yml`, OpenAPI merge, or code was produced.
15. Confirm matching visual colors alone produce no lifecycle label without an
    explicit legend/equivalent mapping.
16. Confirm legend definitions, labels, visual styles and any mapped state have
    independently traceable evidence IDs.

### Targeted Audit Indexing

When explicitly requested, `index_sparx.py` supports `--target-audit` followed
by a bounded audit YAML under `.factory/`. It reads only the exact
`target.boundedOriginalPages` listed by that audit. The output is a separate
artifact and must never replace `.factory/sparx-index.yml`. Local HTML links
outside the selected set may be retained only as unresolved `outOfScope`
references when explicitly listed by the audit; their target files are not
opened and no recursive expansion is performed.

```text
python .opencode/skills/parse-sparx/scripts/index_sparx.py input/sparx/PROYECT \
  .factory/sparx-target-gap-index.yml --target-audit .factory/sparx-parser-gap-audit.yml
```

Targeted indexing fingerprints only the selected page paths and contents, not
the complete export. Run it twice and compare output bytes before accepting the
target artifact.

## Stage 1.5: Deterministic Context Selection

Stage 1.5 runs only after Stage 1 has produced an approved
`.factory/sparx-index.yml`. It deterministically narrows that index before any
semantic interpretation:

```text
Sparx export -> Stage 1 index -> Stage 1.5 context -> Stage 2 interpretation
```

Use `select_sparx_context.py`; do not ask an LLM to choose pages. The selector
reads only `.factory/sparx-index.yml`, writes YAML under `.factory/`, performs
no network access, preserves Stage 1 `evidenceId` values exactly, and does not
modify the index or source export.

### Selection Hints

Supply one or more explicit runtime hints using `--hint`, `--title`,
`--ancestor-title`, `--element-name`, `--package-name`, `--page-path`,
`--identifier`, or `--search-term`. Hints are data, not parser rules. Do not
hardcode project names, identifiers, filenames, or current-domain concepts in
the selector.

Candidates must match every supplied hint in source-observable fields. An
ancestor hint excludes breadcrumb entries whose target is the current page.
Matching uses deterministic field precedence: exact identifiers and paths, exact whole
titles, title segments, element/package names, breadcrumb segments, headings,
properties, links, and finally broad source text. A unique highest score is
required. Equal highest-scoring candidates produce an explicit ambiguity and
no selected root; zero candidates produce a distinct `selection_no_match`
error. Lexical order is never used to break a semantic tie.

GUID identifier comparison uses the same case-insensitive, optional-brace
canonicalization as Stage 1 duplicate detection.

Duplicate titles therefore require disambiguating hierarchy, path, identifier,
or other observable evidence. No business meaning is inferred from the hints.

### Bounded Context

After selecting a unique root, traverse only Stage 1 structural relationships
(`breadcrumb` and `project-browser`) in parent and child directions. The
command-line `--traversal-depth` is bounded from `0` through `3` and defaults to
`1`. Arbitrary cross-reference links do not expand the context. Every included
page records `selectionReasons`, including the root hint matches or the exact
structural relationship, source, path, and depth that included it.

Copy selected page evidence without rewriting it, including identity, source
file, titles, headings, breadcrumb, hierarchy, properties, text blocks, tables,
operations, activities, processes, links, diagrams, images, and all
`evidenceId` values. Preserve structural relationships whose endpoints are both
selected. Traverse only `contains` relationships whose source is `breadcrumb`
or `project-browser`; ignore every other relationship type or source.

### Missing Local Evidence

For selected pages, report unresolved `local-asset` links and image references
as `relevant_local_asset_unresolved` warnings. Record the source page, original
reference, resolved target when available, reference type, and link
`evidenceId` when one exists. Never load the referenced asset or silently treat
the selected evidence as complete. Also carry forward each Stage 1 warning or
error whose source is a selected page, so future interpretation can see partial
or malformed source evidence.

### Stage 1.5 Output

Run, for example:

```text
python .opencode/skills/parse-sparx/scripts/select_sparx_context.py \
  .factory/sparx-index.yml .factory/sparx-context.yml \
  --hint "<observable hint>" --traversal-depth 1
```

The output records index provenance and fingerprint, normalized query inputs,
candidate statistics, scored root candidates, the selected root or explicit
ambiguity, selected pages with reasons, selected structural relationships,
evidence counts, unresolved relevant assets, warnings, and errors.

### Stage 1.5 Validation

1. Parse the generated context YAML.
2. Confirm the selected root is unique or ambiguity is explicit.
3. Confirm unrelated same-title pages are absent unless connected through a
   selected structural relationship within the configured depth.
4. Confirm every selected page has at least one selection reason.
5. Confirm every copied `evidenceId` exactly matches Stage 1.
6. Confirm unresolved assets referenced by selected pages are warnings.
7. Run twice and compare output bytes.
8. Confirm `.factory/sparx-index.yml` and `input/sparx/` are unchanged.
9. Confirm no `sparx-spec.yml`/`.yaml` or OpenAPI specification was produced
   or overwritten.

## Stage 2: Semantic Sparx Interpretation

Stage 2 is documented for future work but is not implemented or executable in
the current phase. It must consume an approved Stage 1.5 context rather than the
entire Stage 1 index or re-scraping HTML through LLM inference.

When separately authorized, Stage 2 will evaluate indexed evidence and produce
`.factory/sparx-spec.yml` containing traceable semantic candidates such as:

- processes and business steps;
- decisions and validations;
- persistence behavior;
- integrations and external service calls;
- error conditions;
- sequencing;
- source-page and source-fragment traceability.

Stage 2 must distinguish explicit evidence, interpretation, ambiguity, and
missing information. It must not invent behavior, and it must stop affected
interpretations when Sparx evidence conflicts or is insufficient. Reconciliation
with OpenAPI belongs to a later explicitly authorized workflow, not Stage 1.

## Embedded content and endpoint-detail extraction

Sparx pages render rich linked-document bodies (specification tables, pseudocode) inside a
local `<iframe src="…/linkdocs/EAID_<GUID>.htm">`. The global indexer only warns about these
iframes; it does not load them. For explicitly authorized pages only, run:

`python .opencode/skills/parse-sparx/scripts/extract_endpoint_detail.py <source-root> <output.yml> --page <page> [--page …] [--scope-plan plan.yml]`

- `embeddedContent`: iframe/object/embed targets that are local, HTML, inside the same export and within
  `--max-embed-depth` (default 1). They are loaded and carry their own sha256 and evidence key.
  Nested embeds are recorded but never loaded.
- `ordinaryOutOfScopeLink`: external, absolute, missing, non-HTML or root-escaping targets, and all ordinary
  anchors. Never followed.
- Preserved as source text/structured evidence: key/value sections (Tipo, Nombre, Operación, URL/TNSNAMES/JNDI),
  columnar tables (INPUT/OUTPUT: origin, destination, transformation), text sections (CONSIDERACIONES,
  VARIABLES PROPERTIES), literal statements split into clauses/assignments/predicates, notes, response-code
  blocks and numeric code mentions. No SQL is invented and no CRUD is inferred from HTTP methods.

## Source authority (required before any target extraction)

Sparx exports can hold parallel representations of the same service (current, backup, historical).
Names, routes and labels match across them, so they must never be merged by similarity. Required sequence:

target -> authority resolution -> active endpoints -> Activity/linkdoc extraction -> semantic
interpretation only where needed -> spec consolidation.

1. `resolve_target_authority.py <source-root> .factory/sparx-target-authority.yml --target <service element name> --openapi .factory/openapi-spec.yml [--reviewed-decisions …]`
   reads only `js/data/*.xml` hierarchy rows plus a few target pages. It finds the branches (children of the lowest
   common ancestor) that contain the target, records explicit backup/historical markers in the package path (not
   solely a "-BKP" string: the decisive evidence is an unmarked twin of a marked branch), maps each OpenAPI operation to
   its literal `METHOD-path` Method element, and lists method -> process -> pool -> lane -> activities/events from
   explicit parent links. Timestamps are reported, never used as a rule. If no single branch is selectable the result is
   `ambiguous` and extraction stops.
2. `build_authoritative_endpoint_detail.py --authority … --source-root … --output .factory/sparx-authoritative-endpoint-detail.yml --nonauthoritative-output .factory/sparx-nonauthoritative-evidence.yml [--prior-artifact …]`
   extracts only the authoritative branch (validation and behavior Activity linkdocs, linked data definitions, success/error
   events) and registers prior artifacts whose source pages belong to non-authoritative branches as
   `stale-for-code-generation` (kept for traceability, never deleted, never used for generation).
3. Activity role is decided from linkdoc content (validation tables vs Tipo/Nombre/Operación), never from names or HTTP verbs.
   Data definitions come only from elements explicitly linked from the Activity/Method relationship tables with a data stereotype.

Do not repeat exploratory page-by-page searches when deterministic endpoint-detail evidence exists.

`extract_process_sequence.py --authority … --source-root … --output .factory/sparx-authoritative-sequence-flow.yml` reads only the
start/end/error/activity pages of the authoritative operations and resolves SequenceFlow directions structurally.
