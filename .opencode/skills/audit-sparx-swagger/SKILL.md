---
name: audit-sparx-swagger
description: Use when auditing a microservice for verified inconsistencies between its Sparx Enterprise Architect documentation and its OpenAPI/Swagger contract, producing a structured per-service findings registry and an editable Word report. Read-only; never generates code.
---

# Audit Sparx vs Swagger

Read-only comparison. It reuses the existing analyzers (`parse-openapi`, `parse-sparx`, `interpret-sparx` for prose) and never
duplicates them. It does not touch the Java generation pipeline, `.factory/`, `service-spec`, reviewed decisions, Maven or Oracle.

## Per-service layout (never mix services)

```text
reports/inconsistencias/registros/<service>/work/            snapshots + snapshot-manifest.yml (written by snapshot_sources.py)
reports/inconsistencias/registros/<service>/findings.yml     structured registry (source of truth for the DOCX)
reports/inconsistencias/registros/<service>/supplemental.yml optional agent-authored semantic review
reports/inconsistencias/<service>_sparx_swagger.docx         deterministic render of findings.yml
```

## Steps

1. Snapshots (reuse of the analyzers, outputs only under `work/`, never `.factory/`):
   `python .opencode/skills/audit-sparx-swagger/scripts/snapshot_sources.py --service <service> --openapi input/contracts/<service>.yml --sparx input/sparx/PROYECT`
   It runs `normalize_openapi` (imported, output root = work dir), `resolve_target_authority.py` and
   `build_authoritative_endpoint_detail.py`, and records in `snapshot-manifest.yml` the OpenAPI sha256, the sha256 of every Sparx
   hierarchy (TOC) file and of every snapshot. Only the authoritative branch feeds the comparison; BKP/historical evidence never
   produces findings.
2. Deterministic comparison:
   `python .opencode/skills/audit-sparx-swagger/scripts/compare_sparx_swagger.py --service <service> --openapi <work>/openapi-spec.yml --detail <work>/sparx-authoritative-endpoint-detail.yml --authority <work>/sparx-target-authority.yml --snapshot-manifest <work>/snapshot-manifest.yml [--supplemental supplemental.yml] [--decisions <reviewed decisions, context only>] --output <registry>/findings.yml`
   It first re-verifies source currency (Swagger file AND Sparx export AND snapshots) and aborts when stale.
3. Semantic review (agent): read CONSIDERACIONES/prose and the pages of Sparx methods that did not match a route literally. Put
   `findings`, `unverified` and `discarded` in `supplemental.yml` following the classification rules below, then rerun step 2.
4. Visual evidence (fully automatic): `python .opencode/skills/audit-sparx-swagger/scripts/capture_evidence.py <registry>/findings.yml` (run after every comparison; it rewrites `visualEvidence` in `findings.yml` and the images under `<registry>/images/`). No capture specs or `supplemental.yml` are needed: fragments are derived from the structured evidence of each finding.
5. Render: `python .opencode/skills/audit-sparx-swagger/scripts/build_report_docx.py <registry>/findings.yml reports/inconsistencias/<service>_sparx_swagger.docx`.
6. Validate: `python .opencode/skills/audit-sparx-swagger/scripts/validate_report_docx.py --service <service> --registry <registry>/findings.yml --docx reports/inconsistencias/<service>_sparx_swagger.docx --render`.
   It re-verifies currency (including every cited Sparx page hash). Visual review is `not-executed` without a renderer; never claim it passed.

## Classification (exactly one per result)

- **contradiccion-verificada**: both sources make normative, incompatible statements about the same element (required flag, type of the same
  field, active/inactive lifecycle). Swagger evidence that is only an `example`, `description` or `summary` can never support one.
- **diferencia-documental**: an element or rule documented in one source and absent or structured differently in the other (field, parameter,
  status code, route prefix, behavior described only by an example).
- **No verificado** (separate list, categorized): `comportamiento-no-especificado` (neither source defines it),
  `contradiccion-interna-sparx` (Sparx disagrees with itself; never a Sparx/Swagger finding), `fuente-no-comparable`
  (for example the OUTPUT "Tipo" column types the SELECT source column, not the response contract), `verificacion-pendiente`.
  Matches and successful checks (equal headers, equal status codes, eliminated operations absent from Swagger) are never listed.
- **Discarded candidates** (`discardedCandidates`, traceability only, not rendered): differences caused by distinct responsibilities, such as
  Swagger validation constraints (`minimum`, `enum`, `maxLength`) that Sparx does not document, internal Oracle columns, error envelope fields
  (`elementClass: constraint | internal-column | error-envelope`). A conflicting declared value would be a contradiction instead.

## Route and relation verification (before reporting a missing operation)

The comparer lists every method of the service in the authoritative branch (`sparx_methods.py`) and compares routes ignoring a leading
`/api`, a `/vN` segment and parameter names. One active equivalent method gives a documental `route-difference`, not a missing operation.
Only an inactive equivalent gives a lifecycle contradiction; several or unreadable candidates are `verificacion-pendiente`; no equivalent gives
`missing-in-sparx`. «Invoca» relations are resolved to the owning service: an invoker owned by another service (for example a BFF) is a caller,
never an alternative route of the audited service.

## Registry schema (v2)

Finding: `id`, `key`, `operation{method,path,operationId}`, `element`, `kind`, `category`, `sparx{text}`, `swagger{text}`, `inconsistency`,
`evidence{sparx:[{branch,element,guid,activity,page,pageSha256,linkdoc,evidenceId}], swagger:[{method,path,pointer}]}`, `severity`, optional
`humanDecisionContext`. Registry also holds `sourceCurrency`, `unverified[{operation,category,topic,reason}]`, `discardedCandidates`, `operationsAudited`.

## DOCX format

Calibri 11, all black, white background, A4 with 2 cm margins, no cover/header/footer/page numbers/logos/introductions. Starts directly with a bold
operation line, then bold subheadings "Contradicciones verificadas" / "Diferencias documentales" with one compact table per finding: first row
ID and Severidad, then Operación, Elemento afectado, Sparx, Swagger and Inconsistencia detectada across the full width (fixed layout, rows never
split). There is no "Evidencias" field and the document never shows GUIDs, JSON Pointers, page/linkdoc names, file paths or generated-file
references: each Sparx/Swagger/Inconsistencia text must be self-explanatory (name the Activity, table, field and literal values in prose).
Evidence stays only in `findings.yml` (`evidence.sparx` / `evidence.swagger`) for traceability and verification. A final "No verificado" list
(category + topic + reason, also free of internal references) appears only when needed.

## Visual evidence (authentic images only, derived automatically)

- **Swagger**: `evidence.swagger[].pointer` is resolved against the ORIGINAL OpenAPI file (`evidence_locator.Swagger`), following local `$ref` to locate the node (route, parameters, request/response schema properties, examples, the declared status codes). The verbatim lines are rendered in monospace; lines that
  are `$ref` references are replaced by a visible ellipsis, so no technical reference reaches the Word. Oversized nodes fall back to a shallow excerpt (key and direct children).
- **Sparx**: for every `evidence.sparx[]` item the original page/linkdoc is rendered in a real headless browser (Chrome/Edge via Playwright) and matched (`evidence_locator.plan_sparx`) using: the evidence row id (`evidenceId` -> row values), the `section`
  (table of a missing element), the method / end-event element, the field names of the finding's `element` inside the section the finding names (for example ResponseAuditType), and finally the distinctive vocabulary of the Sparx text of the finding (narrowed to the matching lines).
  The best-scoring evidence item wins; context-only relations are skipped. The screenshot is cropped to the matched rows (with the table header for context) or text; separate fragments are stitched with a visible divider.
- Existing `capture` specs inside evidence items are still honored (compatibility) but are never required.
- Grayscale only, never retouched, fitted inside the 17 cm text area (max 12 cm high); images needing less than 55 % of their natural size are rejected as illegible. A fragment whose text would contain internal references (GUID, pointers, page/file names) is not captured.
- If an authentic image cannot be obtained for a source (nothing matches, browser missing, source changed, illegible), that source stays text-only and the cause is recorded in `findings.yml` (`visualEvidence.<source>.reason`), never in the Word. No synthetic or redrawn images are produced.
- `findings.yml` keeps, per finding: structured `evidence`, and `visualEvidence.{sparx,swagger}` with `status`, `image`, `imageSha256`, `capturedText`, `derivedSpec` (what was derived and from which evidence item, `automatic`), `sourceFile`, `sourceSha256`, `fitScale`.
- The validator checks image count and labels, grayscale, margins, legibility, absence of internal references, image hashes, that Swagger fragments equal the current original lines AND are re-derived identically from the finding pointer, that Sparx captured text exists in the original page,
  that each image relates to its finding, and that the sources are unchanged.
