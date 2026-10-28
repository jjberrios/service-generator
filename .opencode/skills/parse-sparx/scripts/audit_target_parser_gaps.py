#!/usr/bin/env python3
"""Audit bounded target Sparx HTML evidence against existing normalized artifacts."""

from __future__ import annotations

import hashlib
import mmap
import os
import re
import sys
import tempfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit


ROOT = Path.cwd().resolve()
SPARX_ROOT = Path("input/sparx/PROYECT")
INDEX_PATH = Path(".factory/sparx-index.yml")
SPARX_SPEC_PATH = Path(".factory/sparx-spec.yml")
TARGET_BEHAVIOR_PATH = Path(".factory/target-behavior-discovery.yml")
TARGET_FLOW_PATH = Path(".factory/target-flow-discovery.yml")
TARGET_UNITS_PATH = Path(".factory/target-sparx-units.yml")
STAGE2A_MANIFEST = Path(".factory/target-sparx-semantic-results/manifest.yml")
STAGE2B_MANIFEST = Path(".factory/target-behavior-semantic-results/manifest.yml")
FLOW_RESULTS_MANIFEST = Path(".factory/target-flow-semantic-results/manifest.yml")
OUTPUT_PATH = Path(".factory/sparx-parser-gap-audit.yml")
PAGE_PREFIX = "input/sparx/"
PAGE_SUFFIXES = (".htm", ".html")
PAGE_KEYS = {"sourcePage", "sourcePages", "fromPage", "toPage", "targetPage", "destinationPage",
             "owningSparxOperationPage", "page", "file", "sourcePageFile"}
ENTITY_NAMES = ("MAILINGINFORMATION", "GEDODBDD")
CONNECTOR_MARKERS = ("«soporta»", "soporta", "«invoca»", "invoca", "&desde", "&hasta",
                     "association", "associations", "flow", "connector", "relationship")
TEXT_MARKERS = ("notes", "note", "description", "documentation", "documentation text")
TABLE_PROPERTY_LABELS = {"name", "type", "notes", "stereotype", "guid", "id", "status", "package", "visibility", "alias"}


class AuditError(Exception):
    pass


class RawPageAuditParser(HTMLParser):
    """Collect only observable structural facts from one explicitly selected HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tag_counts: Counter[str] = Counter()
        self.tables: list[dict[str, Any]] = []
        self.table_stack: list[dict[str, Any]] = []
        self.current_row: list[dict[str, Any]] | None = None
        self.current_cell: dict[str, Any] | None = None
        self.images: list[dict[str, Any]] = []
        self.maps: list[dict[str, Any]] = []
        self.map_stack: list[dict[str, Any]] = []
        self.areas: list[dict[str, Any]] = []
        self.links: list[dict[str, Any]] = []
        self.link_capture: dict[str, Any] | None = None
        self.note_captures: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []
        self.div_depth = 0
        self.attribute_names: Counter[str] = Counter()
        self.tag_attribute_names: dict[str, Counter[str]] = {}
        self.unsupported_tags: Counter[str] = Counter()

    @staticmethod
    def attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(key).casefold(): str(value or "") for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = self.attrs(attrs)
        self.tag_counts[tag] += 1
        self.attribute_names.update(values.keys())
        self.tag_attribute_names.setdefault(tag, Counter()).update(values.keys())
        if tag in {"iframe", "object", "embed"}:
            self.unsupported_tags[tag] += 1
        if tag == "table":
            table = {"index": len(self.tables), "attributes": values, "rows": [], "hidden": False}
            table["hidden"] = bool(values.get("hidden") or values.get("aria-hidden", "").casefold() == "true"
                                   or "display:none" in values.get("style", "").replace(" ", "").casefold())
            self.tables.append(table)
            self.table_stack.append(table)
        elif tag == "tr" and self.table_stack:
            self.current_row = []
        elif tag in {"td", "th"} and self.table_stack and self.current_row is not None:
            self.current_cell = {"tag": tag, "attributes": values, "parts": []}
        elif tag == "map":
            current = {"name": values.get("name") or values.get("id"), "attributes": values}
            self.maps.append(current)
            self.map_stack.append(current)
        elif tag == "area":
            self.areas.append({"attributes": values,
                               "mapName": self.map_stack[-1].get("name") if self.map_stack else None})
            self.links.append({"tag": "area", "href": values.get("href", ""),
                               "text": values.get("alt") or values.get("title") or "",
                               "mapName": self.map_stack[-1].get("name") if self.map_stack else None,
                               "attributes": values})
        elif tag == "img":
            self.images.append({"src": values.get("src", ""), "alt": values.get("alt", ""),
                                "title": values.get("title", ""), "usemap": values.get("usemap", ""),
                                "attributes": values})
        elif tag == "a":
            self.link_capture = {"tag": "a", "href": values.get("href", ""),
                                 "textParts": [], "attributes": values}
        if tag == "div":
            self.div_depth += 1
            if any("objectdetailsnotes" in part for part in values.get("class", "").casefold().split()):
                self.note_captures.append({"class": values.get("class", ""), "attributes": values,
                                           "parts": [], "depth": self.div_depth})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell["parts"].append(data)
        if self.link_capture is not None:
            self.link_capture["textParts"].append(data)
        for capture in self.note_captures:
            capture["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"td", "th"} and self.current_cell is not None:
            self.current_cell["text"] = " ".join("".join(self.current_cell.pop("parts")).split())
            self.current_row.append(self.current_cell)
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            if self.table_stack:
                self.table_stack[-1]["rows"].append(self.current_row)
            self.current_row = None
        elif tag == "table" and self.table_stack:
            self.table_stack.pop()
            self.current_row = None
        elif tag == "map" and self.map_stack:
            self.map_stack.pop()
        elif tag == "a" and self.link_capture is not None:
            item = self.link_capture
            item["text"] = " ".join("".join(item.pop("textParts")).split())
            self.links.append(item)
            self.link_capture = None
        elif tag == "div":
            closing = [capture for capture in self.note_captures if capture.get("depth") == self.div_depth]
            self.note_captures = [capture for capture in self.note_captures if capture.get("depth") != self.div_depth]
            for capture in closing:
                capture.pop("depth", None)
                capture["text"] = " ".join("".join(capture.pop("parts")).split())
                self.notes.append(capture)
            self.div_depth = max(0, self.div_depth - 1)


def load_yaml(path: Path, yaml: Any) -> Any:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
        raise AuditError(f"Missing or unsafe bounded audit artifact: {path.as_posix()}")
    try:
        return yaml.safe_load(path.read_bytes()) or {}
    except yaml.YAMLError as exc:
        raise AuditError(f"Invalid YAML audit artifact: {path.as_posix()}") from exc


def encode_yaml(value: Any, yaml: Any) -> bytes:
    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True
    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=120).encode("utf-8")


def page_path(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith(PAGE_PREFIX) and value.lower().endswith(PAGE_SUFFIXES):
        return value.replace("\\", "/")
    return None


def collect_pages(node: Any, output: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key) in PAGE_KEYS:
                if isinstance(value, list):
                    for candidate in value:
                        normalized = page_path(candidate)
                        if normalized:
                            output.add(normalized)
                else:
                    normalized = page_path(value)
                    if normalized:
                        output.add(normalized)
            collect_pages(value, output)
    elif isinstance(node, list):
        for value in node:
            collect_pages(value, output)


def safe_index_records(index_path: Path, selected_pages: set[str], yaml: Any) -> dict[str, dict[str, Any]]:
    """Use one bounded exact-path lookup over index records; never deserialize all 7k pages."""
    if index_path.is_symlink() or not index_path.is_file():
        raise AuditError("Existing Stage 1 index is unavailable.")
    alternatives = b"|".join(re.escape(path.encode("utf-8")) for path in sorted(selected_pages))
    pattern = re.compile(rb"(?m)^  file: (" + alternatives + rb")[ \t]*\r?$")
    results: dict[str, dict[str, Any]] = {}
    with index_path.open("rb") as stream:
        if not stream.seekable() or index_path.stat().st_size == 0:
            raise AuditError("Sparx index is not suitable for bounded record lookup.")
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            for match in pattern.finditer(mapped):
                selected = match.group(1).decode("utf-8")
                line_start = mapped.rfind(b"\n", 0, match.start()) + 1
                start_marker = mapped.rfind(b"\n- id:", 0, line_start)
                start = 0 if start_marker < 0 and mapped[:3] == b"- id" else start_marker + 1
                if start < 0 or start >= line_start:
                    continue
                end_marker = mapped.find(b"\n- id:", match.end())
                end = len(mapped) if end_marker < 0 else end_marker + 1
                block = mapped[start:end]
                try:
                    record_value = yaml.safe_load(block)
                except yaml.YAMLError as exc:
                    raise AuditError(f"Could not parse bounded index record for {selected}") from exc
                record = record_value[0] if isinstance(record_value, list) and record_value else record_value
                if isinstance(record, dict) and record.get("file") == selected:
                    results[selected] = record
    return results


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def asset_target(current_page: str, raw: str) -> str | None:
    parsed = urlsplit(raw.strip())
    if (parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("#")
            or any(char in parsed.path for char in "<>\r\n\t")):
        return None
    base = Path(current_page).parent
    dest = PurePosixPath(os.path.normpath((base / unquote(parsed.path)).as_posix()).replace("\\", "/"))
    text = dest.as_posix()
    if text.startswith("../") or text == "..":
        return None
    return text


def page_stage2a(page: str, units: list[dict[str, Any]], unit_payloads: dict[str, Any],
                 result_units: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for selection in units:
        if selection.get("sourcePage") != page:
            continue
        unit_file = str(selection.get("file") or "")
        unit = unit_payloads.get(unit_file) or {}
        field_ranges = (unit.get("unit") or {}).get("fieldRanges") or {}
        result_records = [result for result in result_units.values() if result.get("unitId") == selection.get("unitId")]
        items.append({
            "unitId": selection.get("unitId"),
            "unitFile": unit_file,
            "selectionType": selection.get("selectionType"),
            "fieldRanges": {key: dict(value) for key, value in sorted(field_ranges.items())},
            "resultSummaries": [{key: result.get(key) for key in
                                 ("resultFile", "status", "semanticItemCount", "evidenceUsed", "evidenceUnused", "warnings", "ambiguities", "missingEvidence")}
                                for result in result_records],
        })
    return items


def stage_result_records(root: Path, manifest: dict[str, Any], yaml: Any) -> dict[str, dict[str, Any]]:
    result = {}
    for unit in manifest.get("units") or []:
        page = page_path(unit.get("sourcePage"))
        if page:
            result[str(unit.get("unitId"))] = {**unit, "sourcePage": page}
    return result


def index_summary(record: dict[str, Any] | None) -> dict[str, Any]:
    if not record:
        return {"present": False}
    return {
        "present": True,
        "evidenceKey": record.get("evidenceKey"),
        "notes": len(record.get("notes") or []),
        "textBlocks": len(record.get("textBlocks") or []),
        "properties": len(record.get("properties") or []),
        "tables": len(record.get("tables") or []),
        "operations": len(record.get("operations") or []),
        "links": len(record.get("links") or []),
        "areaLinks": sum(1 for item in record.get("links") or [] if item.get("sourceTag") == "area" or item.get("tag") == "area"),
        "imageReferences": len(record.get("imageReferences") or []),
        "diagrams": len(record.get("diagrams") or []),
        "visualMetadata": len(record.get("visualMetadata") or []),
        "unsupportedTags": [item.get("tag") for item in record.get("warnings", [])
                            if item.get("code") == "html_active_structure_ignored"],
    }


def main() -> int:
    try:
        import yaml
    except ImportError as exc:
        print(f"audit_target_parser_gaps.py: PyYAML is required: {exc}", file=sys.stderr)
        return 2
    try:
        spec = load_yaml(ROOT / ".factory/sparx-spec.yml", yaml)
        behavior = load_yaml(ROOT / ".factory/target-behavior-discovery.yml", yaml)
        flow = load_yaml(ROOT / ".factory/target-flow-discovery.yml", yaml)
        selection = load_yaml(ROOT / ".factory/target-sparx-units.yml", yaml)
        stage2a = load_yaml(ROOT / ".factory/target-sparx-semantic-results/manifest.yml", yaml)
        stage2b = load_yaml(ROOT / ".factory/target-behavior-semantic-results/manifest.yml", yaml)
        flow_results = load_yaml(ROOT / ".factory/target-flow-semantic-results/manifest.yml", yaml)

        active_operations = list((spec.get("active") or {}).get("operations") or [])
        operations = []
        page_set: set[str] = set()
        for operation in active_operations:
            operation_pages: set[str] = set()
            collect_pages(operation, operation_pages)
            flow_matches = []
            for invocation in flow.get("flowInvocations") or []:
                if (invocation.get("operation") or {}).get("operationId") == operation.get("operationId"):
                    related = set()
                    collect_pages(invocation, related)
                    operation_pages.update(related)
                    flow_matches.append(sorted(related))
            page_set.update(operation_pages)
            operations.append({
                "operationId": operation.get("operationId"),
                "method": operation.get("method"),
                "path": operation.get("path"),
                "sourcePages": sorted(operation_pages),
                "flowDiscoveryPageSets": flow_matches,
            })

        target = behavior.get("target") or {}
        collect_pages(target, page_set)
        for row in flow.get("boundedDestinationPages") or []:
            item = page_path(row.get("page"))
            if item:
                page_set.add(item)
        collect_pages(flow.get("flowInvocations") or [], page_set)
        for unit in selection.get("units") or []:
            item = page_path(unit.get("sourcePage"))
            if item:
                page_set.add(item)
        for manifest in (stage2a, stage2b, flow_results):
            collect_pages(manifest, page_set)
        collect_pages((spec.get("traceability") or {}).get("sourceUnits") or [], page_set)
        reviewed = (spec.get("traceability") or {}).get("reviewedDecisions") or []
        collect_pages(reviewed, page_set)

        bounded_index = safe_index_records(ROOT / ".factory/sparx-index.yml", page_set, yaml)
        target_root = ROOT / SPARX_ROOT
        audit_rows = []
        local_assets: dict[str, set[str]] = {}
        direct_link_candidates: dict[str, set[str]] = {}
        parser_gaps = []
        data_rows = {name: [] for name in ENTITY_NAMES}
        stage2a_units = list(selection.get("units") or [])
        unit_payloads = {}
        for unit in stage2a_units:
            unit_path = str(unit.get("file") or "")
            if unit_path:
                unit_payloads[unit_path] = load_yaml(ROOT / unit_path, yaml)
        stage2a_results = stage_result_records(ROOT, stage2a, yaml)
        stage2b_results = stage_result_records(ROOT, stage2b, yaml)
        flow_results_units = stage_result_records(ROOT, flow_results, yaml)

        missing_original = []
        for page in sorted(page_set):
            relative_export = page.removeprefix(SPARX_ROOT.as_posix() + "/")
            original = target_root / PurePosixPath(relative_export)
            if not original.is_file():
                missing_original.append(page)
                continue
            raw = original.read_bytes()
            parser = RawPageAuditParser()
            try:
                parser.feed(raw.decode("utf-8", errors="replace"))
                parser.close()
            except Exception as exc:
                parser_gaps.append({"type": "raw-html-parse-failure", "sourcePage": page,
                                    "evidence": str(exc), "currentlyCaptured": False,
                                    "impact": "Original-page structure could not be fully compared by this bounded audit."})
            raw_table_rows = [row for table in parser.tables for row in table.get("rows", [])]
            raw_cell_texts = [cell.get("text", "") for row in raw_table_rows for cell in row]
            page_text = " ".join(raw_cell_texts + [item.get("text", "") for item in parser.links]
                                 + [item.get("text", "") for item in parser.notes])
            raw_entity_mentions = {}
            for entity in ENTITY_NAMES:
                matching_rows = []
                for table in parser.tables:
                    for row_index, row in enumerate(table.get("rows", [])):
                        values = [cell.get("text", "") for cell in row]
                        if any(entity.casefold() in text.casefold() for text in values):
                            matching_rows.append({"tableIndex": table["index"], "rowIndex": row_index, "cells": values})
                if matching_rows:
                    raw_entity_mentions[entity] = matching_rows
                    data_rows[entity].extend({"sourcePage": page, **item} for item in matching_rows)
            index_record = bounded_index.get(page)
            index_counts = index_summary(index_record)
            raw_notes = [item.get("text", "") for item in parser.notes if item.get("text")]
            raw_note_fields = []
            for table in parser.tables:
                for row in table.get("rows", []):
                    cells = [cell.get("text", "") for cell in row]
                    if len(cells) > 1 and cells[0].strip().casefold() == "notes" and cells[1].strip():
                        raw_note_fields.append(normalize_text(cells[1]))
            normalized_notes = {normalize_text(text) for text in (index_record or {}).get("notes", [])}
            for prop in (index_record or {}).get("properties", []) or []:
                if isinstance(prop, dict) and str(prop.get("name", "")).strip().casefold() == "notes":
                    normalized_notes.add(normalize_text(str(prop.get("value", ""))))
            normalized_notes.update(normalize_text(item.get("text", "")) for item in (index_record or {}).get("textBlocks", [])
                                    if isinstance(item, dict))
            notes_missing = [text[:500] for text in raw_notes + raw_note_fields
                             if normalize_text(text) and normalize_text(text) not in normalized_notes]
            raw_areas = parser.areas
            normalized_area_links = [item for item in ((index_record or {}).get("links") or [])
                                     if item.get("sourceTag") == "area" or item.get("tag") == "area"]
            area_metadata_lost = [{
                "mapName": item.get("mapName"),
                "href": (item.get("attributes") or {}).get("href"),
                "shape": (item.get("attributes") or {}).get("shape"),
                "coords": (item.get("attributes") or {}).get("coords"),
            } for item in raw_areas if (item.get("attributes") or {}).get("coords") or (item.get("attributes") or {}).get("shape")]
            if notes_missing:
                parser_gaps.append({"type": "notes-not-preserved-in-index", "sourcePage": page,
                                    "evidence": notes_missing, "currentlyCaptured": False,
                                    "impact": "Notes text visible in the original bounded page is absent from normalized notes; operation/data behavior may be present and needs targeted semantic review."})
            if len(parser.tables) != index_counts.get("tables", 0):
                parser_gaps.append({"type": "table-count-mismatch", "sourcePage": page,
                                    "evidence": {"originalTables": len(parser.tables), "normalizedTables": index_counts.get("tables", 0)},
                                    "currentlyCaptured": False,
                                    "impact": "One or more target-page tables may not be represented in the current Stage 1 index."})
            if len(parser.images) != index_counts.get("imageReferences", 0):
                parser_gaps.append({"type": "image-reference-count-mismatch", "sourcePage": page,
                                    "evidence": {"originalImages": len(parser.images), "normalizedImageReferences": index_counts.get("imageReferences", 0)},
                                    "currentlyCaptured": False,
                                    "impact": "A target page image reference may be missing from Stage 1 normalization."})
            if raw_areas and index_counts.get("areaLinks", 0) < len(raw_areas):
                parser_gaps.append({"type": "image-map-area-links-missing", "sourcePage": page,
                                    "evidence": {"originalAreaCount": len(raw_areas), "normalizedAreaLinks": index_counts.get("areaLinks", 0)},
                                    "currentlyCaptured": False,
                                    "impact": "Diagram hotspot destinations may be missing from the target index."})
            if area_metadata_lost:
                parser_gaps.append({"type": "image-map-geometry-not-normalized", "sourcePage": page,
                                    "evidence": area_metadata_lost,
                                    "currentlyCaptured": "Hotspot href/text/mapName are represented as link evidence; area shape/coordinates are not present on normalized area link records.",
                                    "impact": "The parser does not preserve exact diagram hotspot geometry; visual object-to-hotspot mapping may be unavailable without coordinates."})

            referenced_assets = []
            for image in parser.images:
                target = asset_target(page, str(image.get("src") or ""))
                if target:
                    exists = (ROOT / target).is_file()
                    referenced_assets.append({"kind": "image", "path": target, "exists": exists,
                                              "usemap": image.get("usemap") or None})
                    if exists:
                        local_assets.setdefault(target, set()).add(page)
            for link in parser.links:
                href = str(link.get("href") or "")
                target = asset_target(page, href)
                if not target:
                    continue
                if target.lower().endswith(PAGE_SUFFIXES) and target.startswith(PAGE_PREFIX):
                    if target not in page_set and (ROOT / target).is_file():
                        direct_link_candidates.setdefault(target, set()).add(page)
                elif not target.lower().endswith(PAGE_SUFFIXES):
                    exists = (ROOT / target).is_file()
                    referenced_assets.append({"kind": "local-link-asset", "path": target, "exists": exists,
                                              "sourceTag": link.get("tag"), "mapName": link.get("mapName")})
                    if exists:
                        local_assets.setdefault(target, set()).add(page)

            target_units_on_page = [item for item in stage2a_units if item.get("sourcePage") == page]
            stage2a_result_on_page = [item for item in stage2a_results.values() if item.get("sourcePage") == page]
            stage2b_on_page = [item for item in stage2b_results.values() if item.get("sourcePage") == page]
            flow_on_page = [item for item in flow_results_units.values() if item.get("sourcePage") == page]
            uncaptured_by_index = []
            if index_record:
                if (raw_notes or raw_note_fields) and not (index_record.get("notes") or index_record.get("properties")):
                    uncaptured_by_index.append("notes")
                if raw_entity_mentions and not (index_record.get("tables") or []):
                    uncaptured_by_index.append("table/data-object rows")
                if raw_areas and not index_counts.get("areaLinks"):
                    uncaptured_by_index.append("image-map hotspot links")
            else:
                uncaptured_by_index.append("entire Stage 1 page record")
            audit_rows.append({
                "sourcePage": page,
                "originalSha256": hashlib.sha256(raw).hexdigest(),
                "originalEvidence": {
                    "headings": parser.tag_counts["h1"] + parser.tag_counts["h2"] + parser.tag_counts["h3"] + parser.tag_counts["h4"] + parser.tag_counts["h5"] + parser.tag_counts["h6"],
                    "notesBlocks": len(raw_notes),
                    "notesPropertyRows": len(raw_note_fields),
                    "notesExcerpts": [text[:500] for text in raw_notes],
                    "tables": len(parser.tables),
                    "tableRows": len(raw_table_rows),
                    "taggedPropertyLikeTables": sum(1 for table in parser.tables
                                                     if set((cell.get("text", "").strip().casefold() for row in table.get("rows", [])[:1] for cell in row))
                                                     & TABLE_PROPERTY_LABELS),
                    "anchors": parser.tag_counts["a"],
                    "images": len(parser.images),
                    "imageMaps": len(parser.maps),
                    "imageMapAreas": len(raw_areas),
                    "unsupportedActiveTags": dict(sorted(parser.unsupported_tags.items())),
                    "entityMentionRows": raw_entity_mentions,
                    "connectorLabelRows": [{"tableIndex": table["index"], "rowIndex": row_index,
                                             "cells": [cell.get("text", "") for cell in row]}
                                            for table in parser.tables
                                            for row_index, row in enumerate(table.get("rows", []))
                                            if any(marker in " ".join(cell.get("text", "") for cell in row).casefold()
                                                   for marker in CONNECTOR_MARKERS)],
                },
                "normalizedEvidence": index_counts,
                "stage2A": {"units": page_stage2a(page, stage2a_units, unit_payloads, stage2a_results)},
                "targetStage2B": [{key: item.get(key) for key in
                                   ("unitId", "resultFile", "status", "semanticItemCount", "evidenceUsed", "evidenceUnused", "warnings", "ambiguities", "missingEvidence")}
                                  for item in stage2b_on_page],
                "targetFlowSemanticResults": [{key: item.get(key) for key in
                                               ("unitId", "resultFile", "status", "semanticItemCount", "evidenceUsed", "evidenceUnused", "warnings", "ambiguities", "missingEvidence")}
                                              for item in flow_on_page],
                "missingFromNormalization": uncaptured_by_index +
                    (["image-map area coordinates and shapes"] if area_metadata_lost else []) +
                    (["specific Notes text in selected Stage 2A semantic items"] if notes_missing and not any(target_units_on_page) else []),
                "additionalLinkedAssets": sorted(referenced_assets, key=lambda item: (item["path"], item["kind"])),
            })

        operation_coverage = []
        for operation in operations:
            pages = operation["sourcePages"]
            page_rows = [row for row in audit_rows if row["sourcePage"] in pages]
            operation_missing = sorted({gap for row in page_rows for gap in row["missingFromNormalization"]})
            raw_summary = {key: sum((row["originalEvidence"].get(key) or 0) for row in page_rows)
                           for key in ("notesBlocks", "tables", "tableRows", "anchors", "images", "imageMaps", "imageMapAreas")}
            normalized_summary = {key: sum((row["normalizedEvidence"].get(key) or 0) for row in page_rows)
                                  for key in ("notes", "textBlocks", "properties", "tables", "operations", "links", "imageReferences", "diagrams")}
            available_text_or_relationship_evidence = bool(raw_summary["notesBlocks"] or raw_summary["tables"] or raw_summary["anchors"])
            operation_coverage.append({
                "operationId": operation["operationId"],
                "method": operation["method"],
                "path": operation["path"],
                "sourcePagesInspected": pages,
                "originalEvidence": raw_summary,
                "normalizedEvidence": normalized_summary,
                "missingFromNormalization": operation_missing,
                "additionalLinkedAssets": sorted({asset["path"] for row in page_rows for asset in row["additionalLinkedAssets"]}),
                "potentiallyMateriallyExplainsBehaviorGaps": available_text_or_relationship_evidence,
                "scopeNote": "Evidence-type presence is reported without interpreting business semantics.",
            })

        all_original_entity_rows = {name: rows for name, rows in data_rows.items()}
        target_spec_behavior = (spec.get("active") or {}).get("operations") or []
        spec_missing = (spec.get("unresolved") or {}).get("missingEvidence") or []
        persistence_normalized_count = len(spec.get("persistence") or [])
        integration_normalized_count = len(spec.get("integrations") or [])
        diagrams = [{"sourcePage": row["sourcePage"], "maps": row["originalEvidence"]["imageMaps"],
                     "areas": row["originalEvidence"]["imageMapAreas"],
                     "images": row["originalEvidence"]["images"],
                     "normalizedDiagrams": row["normalizedEvidence"].get("diagrams", 0),
                     "normalizedAreaLinks": row["normalizedEvidence"].get("areaLinks", 0)}
                    for row in audit_rows if row["originalEvidence"]["images"] or row["originalEvidence"]["imageMaps"]]
        all_area_geometry_gaps = [gap for gap in parser_gaps if gap["type"] == "image-map-geometry-not-normalized"]
        missing_data_links = []
        for entity, rows in all_original_entity_rows.items():
            if rows and persistence_normalized_count == 0:
                missing_data_links.append(f"Original HTML contains {entity} table/relationship mentions, while sparx-spec persistence behavior remains empty.")
        recommendation = {
            "parserChangesRequired": bool(parser_gaps),
            "targetedReindexRequired": bool(parser_gaps),
            "targetedStage2ARequired": bool(any(row["originalEvidence"]["notesBlocks"] or row["originalEvidence"]["tables"] for row in audit_rows)),
            "targetedStage2BRequired": bool(any(row["originalEvidence"]["notesBlocks"] or row["originalEvidence"]["tableRows"] for row in audit_rows)),
            "globalSparxReprocessingNecessary": False,
            "reasons": [
                "The current index_sparx.py CLI accepts only the export root and output path; targeted reindexing is not currently exposed as a CLI mode.",
                "Any follow-up semantic interpretation should remain scoped to active mailing-info operations and only evidence newly preserved by targeted indexing.",
            ],
        }
        warnings = []
        if len(bounded_index) != len(page_set):
            warnings.append(f"Stage 1 index had records for {len(bounded_index)} of {len(page_set)} bounded pages.")
        if missing_original:
            warnings.append(f"{len(missing_original)} bounded original pages were unavailable on disk.")
        if direct_link_candidates:
            warnings.append(f"{len(direct_link_candidates)} local linked page candidates fell outside the existing bounded plan and were not loaded.")
        errors = []
        if missing_original:
            errors.extend({"code": "bounded_source_missing", "sourcePage": page} for page in missing_original)

        report = {
            "target": {
                "service": "dom-document-mailing-info",
                "operations": [{"operationId": op.get("operationId"), "method": op.get("method"), "path": op.get("path")} for op in target_spec_behavior],
                "boundedOriginalPages": sorted(page_set),
                "boundedOriginalPageCount": len(page_set),
                "pageSetSourceArtifacts": [TARGET_BEHAVIOR_PATH.as_posix(), TARGET_FLOW_PATH.as_posix(),
                                           TARGET_UNITS_PATH.as_posix(), STAGE2A_MANIFEST.as_posix(),
                                           STAGE2B_MANIFEST.as_posix(), FLOW_RESULTS_MANIFEST.as_posix(),
                                           ".factory/sparx-spec.yml"],
            },
            "coverage": {"operations": operation_coverage, "pages": audit_rows},
            "parserGaps": parser_gaps,
            "additionalLinkedPageCandidatesNotLoaded": [
                {"targetPage": candidate, "linkedFromPages": sorted(sources)}
                for candidate, sources in sorted(direct_link_candidates.items())
            ],
            "persistenceCoverage": {
                "mailingInformation": {"originalMentions": all_original_entity_rows["MAILINGINFORMATION"],
                                        "stage1IndexedPages": sorted(page for page, rec in bounded_index.items()
                                                                      if "MAILINGINFORMATION" in str(rec).upper()),
                                        "sparxSpecPersistenceEntries": persistence_normalized_count,
                                        "strictBehaviorClaimsAdded": 0,
                                        "gap": "Original mentions are retained as evidence only; operation-to-table action/field semantics remain unresolved."},
                "gedodbd": {"originalMentions": all_original_entity_rows["GEDODBDD"],
                            "stage1IndexedPages": sorted(page for page, rec in bounded_index.items()
                                                          if "GEDODBDD" in str(rec).upper()),
                            "sparxSpecPersistenceEntries": persistence_normalized_count,
                            "gap": "Original Artifact references are retained as evidence only; a data-store relationship or persistence action is not inferred."},
                "unresolvedPersistenceGapsCarriedForward": missing_data_links,
            },
            "diagramCoverage": {
                "pages": diagrams,
                "imageMaps": sum(item["originalEvidence"]["imageMaps"] for item in audit_rows),
                "areas": sum(item["originalEvidence"]["imageMapAreas"] for item in audit_rows),
                "assets": sorted({asset["path"] for row in audit_rows for asset in row["additionalLinkedAssets"]}),
                "missingRelationships": [gap for gap in parser_gaps if gap["type"].startswith("image-map")],
                "geometryGapCount": len(all_area_geometry_gaps),
            },
            "recommendation": recommendation,
            "validation": {"warnings": warnings, "errors": errors,
                           "indexPagesScannedInThisAudit": len(page_set),
                           "rawPagesReadInThisAudit": len(audit_rows),
                           "globalIndexOrExportRescan": False},
        }
        payload = encode_yaml(report, yaml)
        output_path = ROOT / OUTPUT_PATH
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=output_path.parent, prefix=".sparx-gap-audit-", delete=False) as stream:
                temp = Path(stream.name)
                stream.write(payload)
            os.replace(temp, output_path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        print({"boundedPages": len(page_set), "rawPagesRead": len(audit_rows),
               "parserGaps": len(parser_gaps), "warnings": len(warnings), "errors": len(errors),
               "sha256": hashlib.sha256(payload).hexdigest()})
        return 0 if not errors else 1
    except (AuditError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"audit_target_parser_gaps.py: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
