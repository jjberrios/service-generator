#!/usr/bin/env python3
"""Select target Sparx units and a minimum Stage 2B plan without interpreting them."""

from __future__ import annotations

import argparse
import hashlib
import re
import re
import sys
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Any


FACTORY = Path(".factory")
SEMANTIC_FIELDS = ("headings", "properties", "textBlocks", "tables", "operations", "activities",
                   "processes", "links", "diagrams", "imageReferences", "imageMaps", "notes", "anchors")


class SelectionFailure(Exception):
    pass


def yaml_support() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise SelectionFailure("PyYAML must already be installed.") from exc
    return yaml


def safe_yaml(path: Path, yaml: Any, root: Path) -> Any:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise SelectionFailure(f"Unsafe or missing input: {path}")
    try:
        value = yaml.safe_load(path.read_bytes())
    except (OSError, yaml.YAMLError) as exc:
        raise SelectionFailure(f"Invalid YAML: {path}") from exc
    return value if value is not None else {}


def norm(value: Any) -> str:
    return " ".join(re.findall(r"[\w{}-]+", str(value).casefold()))


def make_hints(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    service = spec.get("service") or {}
    ops = []
    hints = []
    title = str(service.get("title") or service.get("name") or "").strip()
    for operation in spec.get("operations") or []:
        contract = operation.get("contract") or {}
        entry = {"method": str(operation.get("method") or "").upper(),
                  "path": str(operation.get("path") or ""),
                  "operationId": str(operation.get("operationId") or ""),
                  "summary": str(operation.get("summary") or contract.get("summary") or ""),
                  "tags": list(operation.get("tags") or contract.get("tags") or [])}
        ops.append(entry)
        for kind in ("path", "operationId", "summary"):
            if entry[kind]:
                hints.append({"kind": kind, "value": entry[kind], "method": entry["method"], "path": entry["path"]})
        for tag in entry["tags"]:
            hints.append({"kind": "tag", "value": str(tag), "method": entry["method"], "path": entry["path"]})
    hints.sort(key=lambda h: (h.get("path", ""), h.get("method", ""), h["kind"], h["value"]))
    return sorted(ops, key=lambda o: (o["path"], o["method"], o["operationId"])), hints


def observations(unit: dict[str, Any]) -> list[tuple[str, str, str]]:
    result = []
    for field in ("headings", "textBlocks", "tables", "operations", "activities", "processes",
                  "imageMaps", "notes"):
        for item in (unit.get("evidence") or {}).get(field) or []:
            if isinstance(item, dict):
                text = norm(" ".join(str(value) for key, value in item.items()
                                      if key != "evidenceId" and isinstance(value, (str, int))))
                result.append((field, text, str(item.get("evidenceId") or "")))
                for area in item.get("areas") or []:
                    if isinstance(area, dict):
                        area_text = norm(" ".join(str(value) for key, value in area.items()
                                                   if key not in {"evidenceId", "attributes", "coords", "shape"}
                                                   and isinstance(value, (str, int))))
                        result.append(("imageMaps", area_text, str(area.get("evidenceId") or "")))
    return result


def score_unit(unit: dict[str, Any], title: str, hints: list[dict[str, Any]]) -> tuple[int, list[str], bool]:
    observed = observations(unit)
    score = 0
    matched: list[str] = []
    direct = False
    info = unit.get("unit") or {}
    metadata = unit.get("pageMetadata") or {}
    observed_title = norm(info.get("title") or metadata.get("elementName") or metadata.get("objectTitle"))
    normalized_service = norm(title)
    title_evidence = any(normalized_service in text for _, text, evidence_id in observed if evidence_id)
    if normalized_service and observed_title == normalized_service and title_evidence:
        score += 10
        matched.append("service-title:" + title)
        direct = True
    for hint in hints:
        value = norm(hint["value"])
        if not value:
            continue
        weight = {"path": 14, "operationId": 12, "summary": 5, "tag": 2}.get(hint["kind"], 1)
        exact = [(field, text, evidence_id) for field, text, evidence_id in observed
                 if evidence_id and value in text]
        if exact:
            score += weight
            matched.append(f"{hint['kind']}:{hint['value']}")
            if hint["kind"] in {"path", "operationId"}:
                direct = True
        elif hint["kind"] in {"path", "operationId"}:
            tokens = [part for part in value.split() if len(part) > 3]
            hits = [(field, text, evidence_id) for field, text, evidence_id in observed
                    if evidence_id and field in {"headings", "operations", "activities", "processes"}
                    and sum(token in text for token in tokens) >= 2]
            if tokens and hits:
                score += min(weight - 1, 2 * len(hits))
                matched.append(f"{hint['kind']}:partial-token-match")
    return score, sorted(set(matched)), direct


def matching_evidence(unit: dict[str, Any], title: str, hints: list[dict[str, Any]]) -> list[str]:
    matched: set[str] = set()
    for field, items in (unit.get("evidence") or {}).items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            observed = norm(" ".join(str(value) for value in item.values() if isinstance(value, (str, int))))
            exact = [h for h in hints if norm(h["value"]) and norm(h["value"]) in observed]
            partial_path = any(
                hint["kind"] in {"path", "operationId"}
                and sum(token in observed for token in norm(hint["value"]).split() if len(token) > 3) >= 2
                for hint in hints
            )
            title_match = norm(title) and norm(title) in observed
            if exact or title_match or partial_path:
                if item.get("evidenceId"):
                    matched.add(str(item["evidenceId"]))
            if field == "imageMaps":
                for area in item.get("areas") or []:
                    if not isinstance(area, dict):
                        continue
                    area_text = norm(" ".join(str(value) for key, value in area.items()
                                               if key not in {"evidenceId", "attributes", "coords", "shape"}
                                               and isinstance(value, (str, int))))
                    area_exact = any(norm(hint["value"]) and norm(hint["value"]) in area_text
                                     for hint in hints)
                    if area_exact or (norm(title) and norm(title) in area_text):
                        if area.get("evidenceId"):
                            matched.add(str(area["evidenceId"]))
    return sorted(matched)


def add_edge(graph: dict[str, list[dict[str, Any]]], a: str, b: str, relation: str,
             evidence: list[str], record: dict[str, Any]) -> None:
    if a == b:
        return
    graph[a].append({"to": b, "relationship": relation, "evidence": evidence, "record": record})


def build_graph(units: list[dict[str, Any]], by_file: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    graph: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # Multiple slicer parts from one exact source page form an explicit page partition.
    for source_file, parts in by_file.items():
        if len(parts) > 1:
            for part in parts:
                for other in parts:
                    if part["identity"] != other["identity"]:
                        add_edge(graph, part["identity"], other["identity"], "same-source-page-partition",
                                 [str((part["unit"].get("unit") or {}).get("evidenceKey") or "")],
                                 {"sourcePage": source_file, "evidenceKey": (part["unit"].get("unit") or {}).get("evidenceKey")})
    by_source = {file: parts[0] for file, parts in by_file.items()}
    for wrapped in units:
        unit = wrapped["unit"]
        identity = wrapped["identity"]
        context = unit.get("context") or {}
        for relation_name in ("structuralParents", "structuralChildren"):
            for relation in context.get(relation_name) or []:
                target_file = relation.get("parent") if relation_name == "structuralParents" else relation.get("child")
                target = by_source.get(str(target_file))
                if target:
                    add_edge(graph, identity, target["identity"], "explicit-structural-" + str(relation.get("type") or "relationship"),
                             [str((unit.get("unit") or {}).get("evidenceKey") or "")], relation)
        for link in (unit.get("evidence") or {}).get("links") or []:
            if link.get("kind") != "internal-page" or not link.get("resolved") or not link.get("target"):
                continue
            target = by_source.get(str(link["target"]))
            if target:
                add_edge(graph, identity, target["identity"], "explicit-internal-sparx-link",
                         [str(link.get("evidenceId") or "")], {k: link.get(k) for k in
                         ("evidenceId", "text", "target", "kind", "resolved")})
        for field in ("processes", "diagrams"):
            for reference in (unit.get("evidence") or {}).get(field) or []:
                if not isinstance(reference, dict):
                    continue
                target_file = str(reference.get("target") or reference.get("page") or "")
                target = by_source.get(target_file)
                if target:
                    add_edge(graph, identity, target["identity"], f"explicit-{field[:-1]}-reference",
                             [str(reference.get("evidenceId") or "")],
                             {k: reference.get(k) for k in ("evidenceId", "target", "page", "name", "title")})
    for edges in graph.values():
        edges.sort(key=lambda e: (e["to"], e["relationship"], str(e["record"])))
    return graph


def read_prior_results(factory: Path, units_by_id: dict[str, dict[str, Any]], yaml: Any,
                       manifest_path: Path | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    manifest = safe_yaml(manifest_path or (factory / "sparx-semantic-results/manifest.yml"), yaml, factory)
    results: dict[str, dict[str, Any]] = {}
    assessment = {"reusable": 0, "reuse-unproven": 0, "needs-interpretation": 0}
    for entry in manifest.get("units", []):
        rel = PurePosixPath(str(entry.get("resultFile") or ""))
        if rel.is_absolute() or ".." in rel.parts:
            raise SelectionFailure("Unsafe result path in manifest.")
        path = factory.parent / Path(*rel.parts)
        result = safe_yaml(path, yaml, factory.parent)
        if entry.get("sha256") and hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise SelectionFailure(f"Prior result hash mismatch: {path}")
        source = result.get("source") or {}
        uid = str(source.get("unitId") or "")
        current = units_by_id.get(uid)
        if current:
            results[uid] = result
    return results, assessment


def resolve_factory_input(factory: Path, root: Path, value: Path) -> Path:
    if value.is_absolute():
        return value
    if value.parts and value.parts[0] == ".factory":
        return root / value
    return factory / value


def targeted_overlay(factory: Path, root: Path, args: argparse.Namespace, yaml: Any) -> tuple[
    dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    impact_path = resolve_factory_input(factory, root, args.target_gap_impact)
    index_path = resolve_factory_input(factory, root, args.target_gap_index)
    enriched_manifest_path = resolve_factory_input(factory, root, args.target_gap_manifest)
    global_manifest_path = factory / "sparx-semantic-units" / "manifest.yml"
    old_target_plan_path = factory / "target-sparx-units.yml"
    impact = safe_yaml(impact_path, yaml, factory)
    index = safe_yaml(index_path, yaml, factory)
    enriched = safe_yaml(enriched_manifest_path, yaml, factory)
    old_global = safe_yaml(global_manifest_path, yaml, factory)
    old_target_plan = safe_yaml(old_target_plan_path, yaml, factory)
    hashes = {
        "targetGapImpactSha256": hashlib.sha256(impact_path.read_bytes()).hexdigest(),
        "targetGapIndexSha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "targetGapManifestSha256": hashlib.sha256(enriched_manifest_path.read_bytes()).hexdigest(),
        "globalManifestSha256": hashlib.sha256(global_manifest_path.read_bytes()).hexdigest(),
        "oldTargetPlanSha256": hashlib.sha256(old_target_plan_path.read_bytes()).hexdigest(),
    }
    source = impact.get("source") or {}
    if (hashes["targetGapIndexSha256"] != source.get("targetIndexSha256")
            or hashes["globalManifestSha256"] != source.get("semanticUnitsManifestSha256")
            or hashes["oldTargetPlanSha256"] != source.get("targetUnitsSha256")):
        raise SelectionFailure("Target overlay inputs do not match the authoritative Phase 8.1 impact fingerprints.")
    affected = {str(item.get("page") or "") for item in impact.get("affectedPages") or []}
    unaffected = {str(item) for item in impact.get("unaffectedPages") or []}
    index_pages = {str(page.get("file") or "") for page in index.get("pages") or []}
    if len(affected) != 60 or len(unaffected) != 21 or len(index_pages) != 81 or affected | unaffected != index_pages:
        raise SelectionFailure("Target overlay does not match the bounded 60 affected / 21 unaffected / 81 total pages.")
    enriched_scope = enriched.get("targetedScope") or {}
    if (enriched_scope.get("mode") != "phase-8.2-affected-pages-only"
            or enriched_scope.get("affectedPages") != 60
            or (enriched.get("source") or {}).get("contextFile") != ".factory/sparx-target-gap-index.yml"
            or (enriched.get("source") or {}).get("contextFingerprint") != hashes["targetGapIndexSha256"]):
        raise SelectionFailure("Targeted Stage 2A manifest does not declare the approved source and 60-page scope.")
    enriched_units = enriched.get("units") or []
    enriched_pages = {str(item.get("sourceFile") or "") for item in enriched_units}
    if enriched_pages != affected:
        raise SelectionFailure("Enriched Stage 2A units do not cover exactly the 60 affected pages.")
    old_unaffected_units = [item for item in old_global.get("units") or []
                            if str(item.get("sourceFile") or "") in unaffected]
    available_unaffected = {str(item.get("sourceFile") or "") for item in old_unaffected_units}
    merged_entries = list(enriched_units) + old_unaffected_units
    merged_pages = enriched_pages | available_unaffected
    if any(str(item.get("sourceFile") or "") in affected for item in old_unaffected_units):
        raise SelectionFailure("Stale affected units entered the unaffected-page overlay.")

    service_path = resolve_factory_input(factory, root, args.service_spec)
    service_spec = safe_yaml(service_path, yaml, factory)
    target_service = str((service_spec.get("service") or {}).get("name") or "")
    if target_service != "dom-document-mailing-info":
        raise SelectionFailure("The authoritative service specification does not identify the requested target service.")
    signatures = {(str(item.get("method") or "").upper(), str(item.get("path") or ""))
                  for item in service_spec.get("operations") or []}
    required = {("GET", "/api/v1/mailing/info"), ("POST", "/api/v1/mailing/info"),
                ("PATCH", "/api/v1/mailing/info/{id}")}
    if signatures != required:
        raise SelectionFailure("Service-spec retrieval operations differ from the approved active operation set.")
    result_manifest_path = resolve_factory_input(factory, root, args.prior_results_manifest)
    results_manifest = safe_yaml(result_manifest_path, yaml, factory)
    result_source = results_manifest.get("source") or {}
    if (result_source.get("targetPlan") != ".factory/target-sparx-units.yml"
            or result_source.get("targetPlanSha256") != hashes["oldTargetPlanSha256"]
            or result_source.get("semanticUnitsManifestSha256") != hashes["globalManifestSha256"]):
        raise SelectionFailure("Prior Stage 2B results do not match the preserved pre-enrichment target/unit manifests.")
    hashes.update({
        "serviceSpecSha256": hashlib.sha256(service_path.read_bytes()).hexdigest(),
        "priorStage2BManifestSha256": hashlib.sha256(result_manifest_path.read_bytes()).hexdigest(),
        "priorTargetPlanPath": old_target_plan_path.relative_to(root).as_posix(),
        "globalStage2APagesUsedForUnaffected": len(available_unaffected),
        "unaffectedTargetPagesWithoutCurrentStage2A": sorted(unaffected - available_unaffected),
    })
    return ({"impact": impact, "index": index, "enrichedManifest": enriched,
             "oldGlobalManifest": old_global, "oldTargetPlan": old_target_plan,
             "serviceSpec": service_spec, "resultsManifest": results_manifest,
             "availableUnaffectedPages": available_unaffected, "affectedPages": affected,
             "unaffectedPages": unaffected, "sourceHashes": hashes},
            merged_entries, old_target_plan, results_manifest, service_spec, index)


def note_map_candidates(unit: dict[str, Any], target_index: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = unit.get("evidence") or {}
    notes = evidence.get("notes") or []
    maps = evidence.get("imageMaps") or []
    note_text_by_id = {str(item.get("evidenceId")): str(item.get("text") or "")
                       for item in evidence.get("textBlocks") or [] if isinstance(item, dict)}
    index_page = next((page for page in target_index.get("pages") or []
                       if page.get("file") == (unit.get("unit") or {}).get("file")), {})
    all_notes = {str(note.get("evidenceId")): note for note in index_page.get("notes") or []}
    index_note_text = {str(block.get("evidenceId")): str(block.get("text") or "")
                       for block in index_page.get("textBlocks") or [] if isinstance(block, dict)}
    note_items = []
    for note_ref in notes:
        note = all_notes.get(str(note_ref.get("evidenceId")), note_ref)
        text_block_id = str(note.get("textBlockEvidenceId") or "")
        note_items.append({"evidenceId": note.get("evidenceId"),
                           "textBlockEvidenceId": text_block_id,
                           "text": note_text_by_id.get(text_block_id) or index_note_text.get(text_block_id, "")})
    map_items = [{"evidenceId": image_map.get("evidenceId"),
                  "areas": [{key: area.get(key) for key in
                            ("evidenceId", "linkEvidenceId", "href", "title", "alt", "linkedPageIdentity")}
                            for area in image_map.get("areas") or []]}
                 for image_map in maps]
    signals: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_matches(source_type: str, evidence_id: str, text: str, include_explicit_link: bool = False) -> None:
        normalized = norm(text)
        tests = {
            "operation-specific processing": [*[(op.get("operationId") or "") for op in operations],
                                               *[(op.get("path") or "") for op in operations],
                                               "operation", "endpoint", "método", "method"],
            "conditions": ["if", "when", "si", "cuando", "condicion", "condición", "validar", "validate"],
            "flow relationships": ["flujo", "flow", "invoca", "soporta", "association", "relationship"],
            "request/response mappings": ["request", "response", "solicitud", "respuesta", "mapping", "mapeo", "payload"],
            "persistence": ["persist", "database", "base de datos", "tabla", "query", "consulta",
                            "MAILINGINFORMATION", "GEDODBDD"],
            "MAILINGINFORMATION": ["MAILINGINFORMATION"],
            "GEDODBDD": ["GEDODBDD"],
            "integration behavior": ["integration", "integración", "integracion", "invoca", "endpoint",
                                     "microservicio", "service", "orquest"],
            "errors/outcomes": ["error", "exception", "fallo", "failure", "resultado", "outcome", "status"],
        }
        for category, cues in tests.items():
            hits = sorted({str(cue) for cue in cues if cue and norm(cue) in normalized})
            if category == "flow relationships" and include_explicit_link:
                hits.append("explicit image-map href/link target")
            if hits:
                signals[category].append({"sourceType": source_type, "evidenceId": evidence_id,
                                          "literalSignals": sorted(set(hits))})

    for note in note_items:
        add_matches("notes", str(note.get("evidenceId") or ""), str(note.get("text") or ""))
    for image_map in maps:
        for area in image_map.get("areas") or []:
            text = " ".join(str(area.get(key) or "") for key in
                            ("href", "title", "alt", "linkedPageIdentity"))
            add_matches("image-map", str(area.get("evidenceId") or ""), text,
                        bool(area.get("href") or area.get("linkedPageIdentity")))
    candidate_relevance = [
        {"category": category, "evidence": sorted(items, key=lambda item: (item["sourceType"], item["evidenceId"]))}
        for category, items in sorted(signals.items())
    ]
    all_categories = ["operation-specific processing", "conditions", "flow relationships",
                      "request/response mappings", "persistence", "MAILINGINFORMATION", "GEDODBDD",
                      "integration behavior", "errors/outcomes"]
    return {
        "notesEvidence": [{key: value for key, value in item.items() if key != "text"}
                          for item in note_items],
        "imageMapEvidence": map_items,
        "candidateRelevance": candidate_relevance,
        "categoriesWithoutLiteralOrStructuralCandidate": sorted(set(all_categories) - set(signals)),
        "interpretationPerformed": False,
        "candidateBasis": "literal text matches and explicit indexed map links only; geometry, color, and visual proximity excluded",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factory", type=Path, default=FACTORY)
    parser.add_argument("--output", type=Path, default=FACTORY / "target-sparx-units.yml")
    parser.add_argument("--expansion-depth", type=int, default=1)
    parser.add_argument("--target-gap-impact", type=Path)
    parser.add_argument("--target-gap-index", type=Path)
    parser.add_argument("--target-gap-manifest", type=Path)
    parser.add_argument("--service-spec", type=Path)
    parser.add_argument("--prior-results-manifest", type=Path)
    parser.add_argument("--authority", type=Path,
                        help="sparx-target-authority.yml; units from non-authoritative branches are excluded from selection")
    args = parser.parse_args()
    try:
        if not 0 <= args.expansion_depth <= 2:
            raise SelectionFailure("Expansion depth must be between 0 and 2.")
        factory = args.factory.resolve(strict=True)
        output = args.output.absolute()
        if output.is_symlink() or output.parent.resolve(strict=True) != factory:
            raise SelectionFailure("Output must be a regular file directly under .factory/.")
        yaml = yaml_support()
        target_flags = [args.target_gap_impact, args.target_gap_index, args.target_gap_manifest, args.service_spec]
        targeted_mode = any(value is not None for value in target_flags)
        if targeted_mode and not all(value is not None for value in target_flags):
            raise SelectionFailure("Target gap selection requires impact, index, enriched manifest, and service spec.")
        if targeted_mode:
            if output.name != "target-sparx-gap-units.yml":
                raise SelectionFailure("Target gap selection must write .factory/target-sparx-gap-units.yml.")
            overlay, entries, old_target_plan, _, spec, target_index = targeted_overlay(
                factory, factory.parent, args, yaml
            )
            manifest = {"units": entries}
            prior_results_path = resolve_factory_input(
                factory, factory.parent,
                args.prior_results_manifest or Path(".factory/target-sparx-semantic-results/manifest.yml"),
            )
        else:
            spec_path = resolve_factory_input(factory, factory.parent, args.service_spec or Path("openapi-spec.yml"))
            spec = safe_yaml(spec_path, yaml, factory)
            manifest = safe_yaml(factory / "sparx-semantic-units/manifest.yml", yaml, factory)
            old_target_plan = {}
            overlay = None
            target_index = {}
            prior_results_path = resolve_factory_input(
                factory, factory.parent,
                args.prior_results_manifest or Path(".factory/sparx-semantic-results/manifest.yml"),
            )
        decisions = safe_yaml(factory / "sparx-reviewed-decisions.yml", yaml, factory)
        title = str((spec.get("service") or {}).get("title") or (spec.get("service") or {}).get("name") or "")
        operations, hints = make_hints(spec)

        units: list[dict[str, Any]] = []
        by_id: dict[str, dict[str, Any]] = {}
        by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in sorted(manifest.get("units", []), key=lambda e: str(e.get("file", ""))):
            rel = PurePosixPath(str(entry.get("file") or ""))
            if rel.is_absolute() or ".." in rel.parts:
                raise SelectionFailure("Unsafe semantic unit path in manifest.")
            path = factory.parent / Path(*rel.parts)
            unit = safe_yaml(path, yaml, factory.parent)
            if entry.get("sha256") and hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise SelectionFailure(f"Semantic unit hash mismatch: {path}")
            info = unit.get("unit") or {}
            identity = str(unit.get("semanticUnitIdentity") or entry.get("semanticUnitIdentity") or "")
            if not identity or identity != str(entry.get("semanticUnitIdentity") or ""):
                raise SelectionFailure(f"Unit identity missing or inconsistent: {path}")
            if unit.get("semanticInputFingerprint") != entry.get("semanticInputFingerprint"):
                raise SelectionFailure(f"Semantic fingerprint missing or inconsistent: {path}")
            wrapped = {"identity": identity, "unitId": str(info.get("id") or entry.get("id") or ""),
                       "path": str(rel), "unit": unit, "entry": entry}
            units.append(wrapped)
            by_id[wrapped["unitId"]] = wrapped
            by_file[str(info.get("file") or entry.get("sourceFile") or "")].append(wrapped)

        non_authoritative_excluded: list[dict[str, str]] = []
        if args.authority:
            authority = yaml.safe_load(args.authority.read_bytes())
            blocked = [(b["pagePathPrefix"], b) for b in authority.get("branches", [])
                       if b.get("pagePathPrefix") and b.get("authorityClass") != "authoritative-candidate"]
            kept = []
            for wrapped in units:
                page_file = str((wrapped["unit"].get("unit") or {}).get("file") or "")
                hit = next((b for prefix, b in blocked if prefix and f"/{prefix.strip('/')}/" in f"/{page_file}"), None)
                if hit:
                    non_authoritative_excluded.append({"semanticUnitIdentity": wrapped["identity"], "file": page_file,
                                                       "branchRootId": hit["branchRootId"], "authorityClass": hit["authorityClass"]})
                else:
                    kept.append(wrapped)
            units = kept
            by_id = {w["unitId"]: w for w in units}
            by_file = defaultdict(list)
            for w in units:
                by_file[str((w["unit"].get("unit") or {}).get("file") or "")].append(w)
        result_by_id, _ = read_prior_results(factory, by_id, yaml, prior_results_path)
        scores = {}
        direct = set()
        ambiguous = set()
        matched_by_id = {}
        for wrapped in units:
            score, matched, strong = score_unit(wrapped["unit"], title, hints)
            scores[wrapped["identity"]] = score
            matched_by_id[wrapped["identity"]] = matched
            if strong and score >= 8:
                direct.add(wrapped["identity"])
            elif any("partial-token-match" in marker or marker.startswith("summary:")
                     for marker in matched):
                ambiguous.add(wrapped["identity"])

        graph = build_graph(units, by_file)
        # BFS from direct matches; retain shortest deterministic justification.
        expanded: dict[str, dict[str, Any]] = {}
        queue = deque((root, root, 0, []) for root in sorted(direct))
        visited_depth = {(root, root): 0 for root in direct}
        while queue:
            current, origin, depth, chain = queue.popleft()
            if depth >= args.expansion_depth:
                continue
            for edge in graph.get(current, []):
                target = edge["to"]
                next_depth = depth + 1
                if target in direct:
                    continue
                candidate = {"from": origin, "relationship": edge["relationship"], "depth": next_depth,
                             "evidence": edge["evidence"], "relationshipRecord": edge["record"],
                             "path": chain + [{"from": current, **{k: edge[k] for k in ("relationship", "evidence", "record")}}]}
                previous = expanded.get(target)
                candidate_key = (next_depth, origin, edge["relationship"], str(edge["record"]))
                if previous is None or candidate_key < previous["_sort"]:
                    candidate["_sort"] = candidate_key
                    expanded[target] = candidate
                state = (target, origin)
                if next_depth < visited_depth.get(state, 99):
                    visited_depth[state] = next_depth
                    queue.append((target, origin, next_depth, candidate["path"]))

        ambiguous.difference_update(expanded)
        decisions_by_evidence: dict[str, dict[str, Any]] = {}
        reviewed = []
        for decision in decisions.get("decisions", []):
            target = decision.get("target") or {}
            if (decision.get("humanReviewed") and str(target.get("service", "")).casefold() == title.casefold()
                    and str(target.get("path") or "") and str(target.get("method") or "")):
                reviewed.append(decision)
                for evidence_id in decision.get("evidenceIds", []):
                    decisions_by_evidence[str(evidence_id)] = decision

        direct_records, expanded_records, ambiguous_records, inactive_records = [], [], [], []
        unresolved_included = []
        validation_warnings, validation_errors = [], []
        unresolved_excluded = 0
        plan = {"reusable": [], "reuse-unproven": [], "needs-interpretation": [],
                "alreadyCurrentAndSufficient": []}
        output_units = []
        for wrapped in units:
            identity = wrapped["identity"]
            selection_type = ("direct" if identity in direct else "expanded" if identity in expanded
                              else "ambiguous" if identity in ambiguous else None)
            result = result_by_id.get(wrapped["unitId"])
            current_unit = wrapped["unit"]
            if selection_type is None:
                if result and (result.get("unresolved") or {}).get("ambiguities"):
                    unresolved_excluded += len((result.get("unresolved") or {}).get("ambiguities") or [])
                continue
            expansion_info = None
            if selection_type == "expanded":
                expansion_info = {k: value for k, value in expanded[identity].items() if k != "_sort"}
            ids = matching_evidence(current_unit, title, hints) if selection_type != "expanded" else []
            inactive_evidence = set(decisions_by_evidence)
            if selection_type == "direct":
                ids = [evidence_id for evidence_id in ids if evidence_id not in inactive_evidence]
            if selection_type == "expanded":
                ids = sorted({str(item.get("evidenceId")) for values in (current_unit.get("evidence") or {}).values()
                              if isinstance(values, list) for item in values
                              if isinstance(item, dict) and item.get("evidenceId")})
            record = {"semanticUnitIdentity": identity, "unitId": wrapped["unitId"], "file": wrapped["path"],
                      "sourcePage": (current_unit.get("unit") or {}).get("file"), "selectionType": selection_type,
                      "semanticInputFingerprint": current_unit.get("semanticInputFingerprint"),
                      "matchedHints": matched_by_id.get(identity, []), "matchedEvidenceIds": ids,
                      "selectionReasons": [{"score": scores.get(identity, 0), "kind": selection_type}],
                      "expansion": expansion_info}
            for issue in (current_unit.get("validation") or {}).get("warnings") or []:
                validation_warnings.append({"unitId": wrapped["unitId"], "issue": issue})
            for issue in (current_unit.get("validation") or {}).get("errors") or []:
                validation_errors.append({"unitId": wrapped["unitId"], "issue": issue})
            # Only an exact reviewed evidence reference can move an item to inactive.
            if selection_type == "direct":
                direct_records.append(record)
            elif selection_type == "expanded":
                expanded_records.append(record)
            else:
                ambiguous_records.append(record)

            if selection_type == "direct":
                full_page_evidence = {str(item.get("evidenceId")) for values in
                                      (current_unit.get("evidence") or {}).values() if isinstance(values, list)
                                      for item in values if isinstance(item, dict) and item.get("evidenceId")}
                inactive_ids = sorted(full_page_evidence.intersection(inactive_evidence))
                if inactive_ids:
                    decision = decisions_by_evidence[inactive_ids[0]]
                    inactive_records.append({"semanticUnitIdentity": identity, "unitId": wrapped["unitId"],
                                             "semanticInputFingerprint": current_unit.get("semanticInputFingerprint"),
                                             "sourcePage": record["sourcePage"], "selectionType": "inactive-item",
                                             "matchedEvidenceIds": inactive_ids, "reviewedDecision": decision,
                                             "lifecycle": {"state": decision["target"].get("lifecycleState"),
                                                           "disposition": "inactive", "evidenceIds": inactive_ids}})

            result_identity = str((result.get("source") or {}).get("semanticUnitIdentity") or "") if result else ""
            result_fingerprint = str(result.get("semanticInputFingerprint") or
                                     (result.get("source") or {}).get("semanticInputFingerprint") or "") if result else ""
            result_branch = ((result or {}).get("source") or {}).get("authorityBranch") if result else None
            exact_current_result = bool(result and result_identity == identity
                                        and result_fingerprint == current_unit.get("semanticInputFingerprint")
                                        and result_branch == current_unit.get("authorityBranch"))
            if exact_current_result:
                unresolved = result.get("unresolved") or {}
                for key in ("ambiguities", "missingEvidence", "warnings", "coveragePending"):
                    for item in unresolved.get(key) or []:
                        unresolved_included.append({"unitId": wrapped["unitId"], "semanticUnitIdentity": identity,
                                                    "kind": key, "item": item})
            if selection_type in {"direct", "expanded", "ambiguous"}:
                if exact_current_result:
                    plan["reusable"].append(wrapped["unitId"])
                    unresolved = result.get("unresolved") or {}
                    if (not any(unresolved.get(key) for key in ("ambiguities", "missingEvidence"))
                            and result.get("status") in {"interpreted", "reinterpreted"}):
                        plan["alreadyCurrentAndSufficient"].append(wrapped["unitId"])
                elif result:
                    plan["reuse-unproven"].append(wrapped["unitId"])
                else:
                    plan["needs-interpretation"].append(wrapped["unitId"])
        
        active_records = direct_records + expanded_records + ambiguous_records
        output_units = active_records + inactive_records
        output_units.sort(key=lambda r: (r["sourcePage"] or "", r["selectionType"], r["semanticUnitIdentity"]))
        selected_evidence = sum(len(record["matchedEvidenceIds"]) for record in output_units)
        total_unresolved = sum(len((r.get("unresolved") or {}).get(key) or []) for r in result_by_id.values()
                               for key in ("ambiguities", "missingEvidence", "warnings", "coveragePending"))
        selection = {"directUnits": [r["unitId"] for r in direct_records],
                     "expandedUnits": [r["unitId"] for r in expanded_records],
                     "ambiguousUnits": [r["unitId"] for r in ambiguous_records],
                     "inactiveUnits": [r["unitId"] for r in inactive_records]}
        stats = {"totalUnits": len(units), "directUnits": len(direct_records),
                 "expandedUnits": len(expanded_records), "ambiguousUnits": len(ambiguous_records),
                 "inactiveUnits": len(inactive_records), "totalTargetUnitsRequiringSemanticConsideration": len(active_records),
                 "selectedEvidenceItems": selected_evidence, "unresolvedIncluded": len(unresolved_included),
                 "unresolvedExcluded": max(0, total_unresolved - len(unresolved_included)),
                  "stage2BPlan": {key: len(value) for key, value in plan.items()},
                   "stage2BMinimumUnits": len(plan["reuse-unproven"]) + len(plan["needs-interpretation"])}
        phase_8_2 = None
        if targeted_mode and overlay is not None:
            old_selection = old_target_plan.get("units") or []
            old_identities = {str(item.get("semanticUnitIdentity") or "") for item in old_selection
                              if item.get("semanticUnitIdentity")}
            old_stage2a_by_identity = {
                str(item.get("semanticUnitIdentity") or ""): str(item.get("semanticInputFingerprint") or "")
                for item in (overlay["oldGlobalManifest"].get("units") or [])
                if item.get("semanticUnitIdentity")
            }
            reslice_comparison = (overlay["enrichedManifest"].get("comparison") or {})
            comparison_old = {str(item.get("oldSemanticUnitIdentity") or ""): item
                              for item in reslice_comparison.get("oldUnits") or []}
            comparison_new = {str(item.get("newSemanticUnitIdentity") or ""): item
                              for item in reslice_comparison.get("newUnits") or []}
            old_result_by_identity = {
                str((result.get("source") or {}).get("semanticUnitIdentity") or ""): result
                for result in result_by_id.values()
                if (result.get("source") or {}).get("semanticUnitIdentity")
            }
            selected_by_identity: dict[str, dict[str, Any]] = {}
            for item in output_units:
                selected_by_identity.setdefault(str(item["semanticUnitIdentity"]), item)
            new_selected_identities = set(selected_by_identity)
            newly_selected = sorted(new_selected_identities - old_identities)
            new_or_changed = []
            fingerprint_changed = []
            prior_stage2b_mismatches = []
            for identity in sorted(new_selected_identities):
                selected = selected_by_identity[identity]
                wrapped = next((item for item in units if item["identity"] == identity), None)
                if wrapped is None:
                    continue
                previous_result = result_by_id.get(wrapped["unitId"])
                previous_source = (previous_result or {}).get("source") or {}
                previous_fingerprint = str((previous_result or {}).get("semanticInputFingerprint") or
                                            previous_source.get("semanticInputFingerprint") or "")
                previous_identity = str(previous_source.get("semanticUnitIdentity") or "")
                current_fingerprint = str(wrapped["unit"].get("semanticInputFingerprint") or "")
                predecessor_records = (comparison_new.get(identity) or {}).get("predecessorUnits") or []
                prior_identities = {str(predecessor.get("semanticUnitIdentity") or "")
                                    for predecessor in predecessor_records
                                    if predecessor.get("semanticUnitIdentity")}
                if identity in old_stage2a_by_identity:
                    prior_identities.add(identity)
                previous_fingerprints = {
                    old_stage2a_by_identity.get(old_identity, "") or str(
                        (comparison_old.get(old_identity) or {}).get("oldSemanticInputFingerprint") or
                        (old_result_by_identity.get(old_identity) or {}).get("semanticInputFingerprint") or
                        ((old_result_by_identity.get(old_identity) or {}).get("source") or {}).get("semanticInputFingerprint") or "")
                    for old_identity in prior_identities
                }
                previous_fingerprints.discard("")
                if previous_result and previous_identity and previous_fingerprint:
                    previous_fingerprints.add(previous_fingerprint)
                fingerprint_changed_here = bool(previous_fingerprints and
                                                any(value != current_fingerprint for value in previous_fingerprints))
                prior_stage2b_mismatch = bool(previous_result and
                                              (previous_identity != identity or previous_fingerprint != current_fingerprint))
                is_new = identity in newly_selected
                if not is_new and not fingerprint_changed_here and not prior_stage2b_mismatch:
                    continue
                impact = note_map_candidates(wrapped["unit"], target_index, operations)
                note_ids = sorted({str(item.get("evidenceId")) for item in
                                   (wrapped["unit"].get("evidence") or {}).get("notes") or []
                                   if item.get("evidenceId")})
                map_ids = sorted({str(evidence_id) for image_map in
                                  (wrapped["unit"].get("evidence") or {}).get("imageMaps") or []
                                  for evidence_id in ([image_map.get("evidenceId")] +
                                                      [area.get("evidenceId") for area in image_map.get("areas") or []])
                                  if evidence_id})
                has_notes = bool(note_ids)
                has_map = bool(map_ids)
                cause = ("both" if has_notes and has_map else "notes" if has_notes
                         else "image-map" if has_map else "other structural changes")
                row = {
                    "semanticUnitIdentity": identity,
                    "unitId": wrapped["unitId"],
                    "sourcePage": (wrapped["unit"].get("unit") or {}).get("file"),
                    "selectionNewComparedWithPreviousPlan": is_new,
                    "semanticInputFingerprintChangedFromPriorStage2AUnit": fingerprint_changed_here,
                    "priorStage2BResultFingerprintMismatch": prior_stage2b_mismatch,
                    "previousSemanticInputFingerprints": sorted(previous_fingerprints),
                    "currentSemanticInputFingerprint": current_fingerprint,
                    "changeCause": cause,
                    "notesEvidenceIds": note_ids,
                    "imageMapEvidenceIds": map_ids,
                    "candidateEvidenceRelevance": impact,
                }
                new_or_changed.append(row)
                if fingerprint_changed_here:
                    fingerprint_changed.append(row)
                if prior_stage2b_mismatch:
                    prior_stage2b_mismatches.append(row)

            inactive_get_records = [item for item in inactive_records
                                    if (item.get("lifecycle") or {}).get("state") == "ELIMINADO"
                                    and (item.get("lifecycle") or {}).get("disposition") == "inactive"
                                    and (item.get("reviewedDecision") or {}).get("target", {}).get("method") == "GET"
                                    and (item.get("reviewedDecision") or {}).get("target", {}).get("path") ==
                                    "/api/v1/mailing/info/{id}"]
            active_get_by_id = any(operation.get("method") == "GET" and
                                   operation.get("path") == "/api/v1/mailing/info/{id}"
                                   for operation in operations)
            relevance_categories = ["operation-specific processing", "conditions", "flow relationships",
                                    "request/response mappings", "persistence", "MAILINGINFORMATION", "GEDODBDD",
                                    "integration behavior", "errors/outcomes"]
            category_units: dict[str, set[str]] = {category: set() for category in relevance_categories}
            category_evidence: dict[str, set[str]] = {category: set() for category in relevance_categories}
            for impact_row in new_or_changed:
                for candidate in impact_row["candidateEvidenceRelevance"].get("candidateRelevance") or []:
                    category = str(candidate.get("category") or "")
                    if category not in category_units:
                        continue
                    category_units[category].add(impact_row["semanticUnitIdentity"])
                    category_evidence[category].update(str(item.get("evidenceId") or "")
                                                       for item in candidate.get("evidence") or []
                                                       if item.get("evidenceId"))
            candidate_category_summary = [{
                "category": category,
                "candidateUnitCount": len(category_units[category]),
                "candidateEvidenceCount": len(category_evidence[category]),
                "interpretationPerformed": False,
            } for category in relevance_categories]
            phase_8_2 = {
                "sourceHashes": overlay["sourceHashes"],
                "scope": {
                    "boundedPages": 81,
                    "affectedPagesResliced": len(overlay["affectedPages"]),
                    "unaffectedPagesUsedWithoutReslicing": len(overlay["availableUnaffectedPages"]),
                    "unaffectedPagesWithoutCurrentUnits": overlay["sourceHashes"]["unaffectedTargetPagesWithoutCurrentStage2A"],
                    "pagesOutsideBoundedSetProcessed": 0,
                    "outOfScopePageReferencesTraversed": 0,
                },
                "selectionComparison": {
                    "previousUniqueTargetUnits": len(old_identities),
                    "currentUniqueTargetUnits": len(new_selected_identities),
                    "newlySelectedTargetUnits": [selected_by_identity[item] for item in newly_selected],
                    "newlySelectedCount": len(newly_selected),
                    "fingerprintChangedTargetUnits": fingerprint_changed,
                    "fingerprintChangedCount": len(fingerprint_changed),
                    "priorStage2BResultsRejectedForChangedInput": prior_stage2b_mismatches,
                    "priorStage2BResultMismatchCount": len(prior_stage2b_mismatches),
                    "unitsWithNotesDrivenChanges": [item for item in new_or_changed if item["changeCause"] == "notes"],
                    "unitsWithImageMapDrivenChanges": [item for item in new_or_changed if item["changeCause"] == "image-map"],
                    "unitsWithBothEvidenceTypes": [item for item in new_or_changed if item["changeCause"] == "both"],
                    "unitsWithOtherStructuralChanges": [item for item in new_or_changed
                                                         if item["changeCause"] == "other structural changes"],
                    "notesAndImageMapImpact": new_or_changed,
                    "candidateCategorySummary": candidate_category_summary,
                    "targetUnitLineage": [item for item in reslice_comparison.get("newUnits") or []
                                           if item.get("newSemanticUnitIdentity") in new_selected_identities],
                },
                "stage2BPlan": {
                    "reusable": plan["reusable"],
                    "reuseUnproven": plan["reuse-unproven"],
                    "needsInterpretation": plan["needs-interpretation"],
                    "alreadyCurrentAndSufficient": plan["alreadyCurrentAndSufficient"],
                    "minimumUnitsRequiringStage2B": stats["stage2BMinimumUnits"],
                    "alreadyCurrentAndSufficientIsCoverageBasedNotAClaimOfFunctionalCompleteness": True,
                },
                "inactiveOperationValidation": {
                    "reviewedGetByIdPreservedInactiveEliminado": bool(inactive_get_records),
                    "inactiveRecords": inactive_get_records,
                    "activeContractContainsInactiveGetById": active_get_by_id,
                },
                "openApiUse": "retrieval-hints-only",
                "semanticInterpretationPerformed": False,
                "stage2BExecuted": False,
            }
        output_doc = {"version": 1, "configuration": {"expansionDepth": args.expansion_depth,
                       "maximumExpansionDepth": 2, "matching": "deterministic-text-hints"},
                      "target": {"service": title, "operations": operations,
                                 "paths": sorted({operation["path"] for operation in operations})},
                       "selection": selection, "statistics": stats, "units": output_units,
                       "reviewedDecisions": reviewed, "unresolved": unresolved_included,
                       "stage2BPlan": plan,
                       "validation": {"warnings": validation_warnings, "errors": validation_errors}}
        if args.authority:
            output_doc["authorityFilter"] = {"file": args.authority.as_posix(), "nonAuthoritativeExcluded": non_authoritative_excluded}
        if phase_8_2 is not None:
            output_doc["phase8_2"] = phase_8_2
        output.write_bytes(yaml.safe_dump(output_doc, allow_unicode=True, sort_keys=False, width=120).encode("utf-8"))
        print(stats)
        return 0
    except (SelectionFailure, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"select_target_units.py: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
