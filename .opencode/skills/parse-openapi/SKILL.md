---
name: parse-openapi
description: Use when validating and deterministically normalizing an OpenAPI 3.x YAML or JSON contract into .factory/openapi-spec.yml without generating code or business flows.
---

# Parse OpenAPI

Use this methodology to transform an arbitrary OpenAPI 3.x YAML or JSON
contract into a deterministic intermediate specification. The OpenAPI document
owns the external HTTP contract, request and response schemas, and declared
API-level validation. It does not define unexpressed business behavior.

## Inputs And Invariants

Establish:

- `<source>`: one OpenAPI file under `input/contracts/`, always read-only;
- `<output>`: `.factory/openapi-spec.yml` unless another `.factory/` path is
  explicitly requested;
- `<script>`:
  `.opencode/skills/parse-openapi/scripts/normalize_openapi.py`.

Read repository-root `AGENTS.md` first. Never modify `<source>`. Never inspect
Sparx, generate Java, modify an archetype, or infer a business flow in this
workflow.

## Information Status

Keep these states distinct throughout normalization:

1. `explicit`: the value is directly declared at its OpenAPI location.
2. `local-reference`: the value is obtained through a resolvable local
   `#/...` reference. Preserve both the `$ref` and the resolved representation.
3. `missing`: the optional field is absent. Represent it as `null`, an empty
   collection, or an explicit inherited-security marker as defined by the
   normalized structure. Do not invent a replacement.
4. `unsupported-or-ambiguous`: the construct cannot be normalized reliably.
   Preserve what can be represented and add a deterministic validation warning
   or error with source location and reason.

Descriptions and examples are contract text, not permission to infer rules.
Extract them verbatim; do not convert prose into validations, decisions,
integrations, persistence behavior, or sequencing.

## Deterministic Procedure

### 1. Preflight

1. Verify `<source>` exists, is a regular file, and is under
   `input/contracts/`.
2. Verify `<output>` is under `.factory/` and differs from `<source>`.
3. Resolve paths before use so symbolic links cannot escape either allowed
   directory. Reject invalid paths before creating output directories.
4. Record the repository-relative source path and SHA-256 digest for
   provenance. Never persist a developer-machine-specific absolute path.
5. Confirm no Sparx or code-generation step is part of the task.
6. Confirm the Python interpreter is available. Do not install dependencies.

### 2. Parse And Validate Before Normalization

Parse JSON with the standard JSON parser. Parse YAML with a duplicate-aware
loader derived from `PyYAML.SafeLoader`. Reject duplicate mapping keys with
source line and column information; never choose a duplicate value silently.
Fail clearly if PyYAML is unavailable. Do not use unsafe YAML constructors.

The script itself must enforce the input and output directory boundaries. It
may create output parent directories only after proving they resolve inside
`.factory/`. It must open the source only for reading and must never rewrite,
format, rename, move, or delete it.

Validate at minimum:

- the root is a mapping;
- `openapi` exists and is a string in the 3.x family;
- `info` is a mapping with `title` and `version`;
- `paths` is a mapping;
- path-item and operation structures are mappings;
- operation responses are mappings;
- parameters have valid `name` and `in` values;
- path parameters are required;
- declared operation IDs are unique;
- local references resolve to valid JSON Pointer targets.

Validation errors must be emitted in `validation.errors`. A structurally
invalid document must produce a nonzero exit status even when a diagnostic
normalized file can be written.

### 3. Normalize Document Metadata

Extract without inference:

- exact OpenAPI version;
- `info.title`;
- `info.version`;
- `info.description` when present;
- top-level servers, including variables;
- tags, descriptions, and external documentation when present.

Do not derive a service name from a filename, title, server URL, or path. The
normalized service title is the explicitly declared `info.title`.

### 4. Normalize Operations

Walk paths in lexical order and methods in this fixed order:

`get`, `put`, `post`, `delete`, `options`, `head`, `patch`, `trace`.

For every operation record:

- path and uppercase HTTP method;
- `operationId`, or `null` when absent;
- tags, summary, description, and deprecated flag;
- merged path-item and operation parameters, with operation declarations
  overriding matching path declarations by `(name, in)`;
- request body and every declared media type;
- all response status/default entries and media types;
- operation security, explicitly distinguishing operation declaration,
  inherited root security, and no declaration;
- operation servers and supported extensions when present.

Group parameters under `path`, `query`, `header`, and `cookie`. Do not
reinterpret headers as query parameters or synthesize undeclared path
parameters.

### 5. Normalize Parameters And Bodies

For each parameter preserve:

- name and location;
- required flag and whether it was explicitly declared;
- description, deprecated, style, explode, allow-empty, and allow-reserved
  settings when present;
- schema or content declaration;
- examples and defaults where declared;
- provenance as explicit or local reference.

For request bodies preserve required flag, description, all content types,
schemas, examples, encodings, and local-reference provenance. Do not choose a
preferred media type.

### 6. Normalize Responses

Preserve every response key exactly as text, including `default`, ranges such
as `2XX`, and vendor-defined values. Preserve description, headers, content,
schemas, examples, links, and local-reference provenance where supported.

Do not infer success or error meaning from status-code families or response
descriptions.

### 7. Normalize Schemas And Components

Preserve component names exactly. Sort component maps lexically but do not
rename, singularize, pluralize, or otherwise canonicalize names.

Extract applicable schema information:

- type, format, title, and description;
- properties and required property names;
- arrays and `items`;
- enums and constants;
- defaults and examples;
- numeric minimum/maximum, exclusive limits, and multiples;
- string `minLength`, `maxLength`, and pattern;
- collection min/max and uniqueness constraints;
- nullable, read-only, write-only, and deprecated flags;
- composition through `allOf`, `oneOf`, `anyOf`, and `not`;
- additional properties and discriminators;
- local `$ref` provenance and resolved content.

Normalize reusable component parameters. Also retain reusable request bodies,
responses, headers, and examples when present so local references remain
traceable. Expose security schemes under the top-level `security` section.

For recursive local schemas, keep the `$ref`, mark the recursive edge, and
avoid infinite expansion. External references must not be fetched; retain the
reference and report it as unsupported.

### 8. Normalize Security

Preserve security scheme names and declared scheme fields without interpreting
authorization policy. Preserve root and operation security requirement arrays,
including an explicitly empty array.

Do not infer authentication requirements from descriptions, headers, or scheme
names.

### 9. Write Deterministically

Run:

```text
python .opencode/skills/parse-openapi/scripts/normalize_openapi.py <source> <output>
```

The script must not access the network or install packages. It writes YAML with
stable section, path, method, component, property, and diagnostic ordering. It
does not include timestamps, host-specific absolute paths, or generated IDs.

The normalized top-level structure is:

```yaml
source: {}
service: {}
servers: []
tags: []
operations: []
components:
  schemas: {}
  parameters: {}
security: {}
validation:
  warnings: []
  errors: []
```

### 10. Validate The Result

1. Parse the output as YAML.
2. Confirm all required top-level sections exist.
3. Confirm source path, SHA-256, format, and OpenAPI version are present.
4. Confirm operation order is path then fixed method order.
5. Confirm every source operation appears exactly once.
6. Confirm component names are unchanged.
7. Confirm local references retain their original `$ref` and resolution status.
8. Confirm missing fields were not invented.
9. Confirm warnings and errors are stable and source-located.
10. Confirm `<source>` is unchanged.
11. Confirm no Sparx artifact was read and no implementation code was created.

Report validation errors and unsupported constructs to the user. Never conceal
them by manually editing the normalized output.
