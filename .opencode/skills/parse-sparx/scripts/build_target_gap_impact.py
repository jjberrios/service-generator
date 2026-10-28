#!/usr/bin/env python3
"""Describe bounded Stage 2A reslice impact from a targeted Sparx gap index."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
FACTORY = ROOT / ".factory"
TARGET_INDEX = FACTORY / "sparx-target-gap-index.yml"
TARGET_UNITS = FACTORY / "target-sparx-units.yml"
SEMANTIC_MANIFEST = FACTORY / "sparx-semantic-units" / "manifest.yml"
OUTPUT = FACTORY / "sparx-target-gap-impact.yml"


class ImpactFailure(Exception):
    pass


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def encode(value: Any, yaml: Any) -> bytes:
    class StableDumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True

    return yaml.dump(value, Dumper=StableDumper, allow_unicode=True,
                     default_flow_style=False, sort_keys=False, width=120).encode("utf-8")


def load(path: Path, yaml: Any) -> tuple[Any, bytes]:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(FACTORY.resolve()):
        raise ImpactFailure(f"Missing or unsafe bounded impact input: {path.relative_to(ROOT).as_posix()}")
    payload = path.read_bytes()
    try:
        return yaml.safe_load(payload) or {}, payload
    except yaml.YAMLError as exc:
        raise ImpactFailure(f"Invalid YAML input: {path.relative_to(ROOT).as_posix()}") from exc


def main() -> int:
    try:
        import yaml
    except ImportError as exc:
        raise ImpactFailure("PyYAML is required; dependencies are never installed dynamically.") from exc

    target, target_bytes = load(TARGET_INDEX, yaml)
    target_units, target_units_bytes = load(TARGET_UNITS, yaml)
    semantic_manifest, semantic_manifest_bytes = load(SEMANTIC_MANIFEST, yaml)
    selected_pages = {str(page.get("file") or "") for page in target.get("pages") or []}
    declared_count = (target.get("source") or {}).get("fileCount")
    if not selected_pages or declared_count != len(selected_pages):
        raise ImpactFailure("Target index pages do not match its declared bounded page set.")
    page_by_file = {str(page["file"]): page for page in target["pages"]}
    affected_pages: list[dict[str, Any]] = []
    unaffected_pages: list[str] = []
    for page_file in sorted(selected_pages):
        page = page_by_file[page_file]
        notes = page.get("notes") or []
        maps = page.get("imageMaps") or []
        if not notes and not maps:
            unaffected_pages.append(page_file)
            continue
        affected_pages.append({
            "page": page_file,
            "newEvidence": {
                "notes": [{
                    "evidenceId": note.get("evidenceId"),
                    "textBlockEvidenceId": note.get("textBlockEvidenceId"),
                } for note in notes],
                "imageMap": [{
                    "evidenceId": image_map.get("evidenceId"),
                    "mapName": image_map.get("name") or image_map.get("id"),
                    "areas": [{
                        "evidenceId": area.get("evidenceId"),
                        "linkEvidenceId": area.get("linkEvidenceId"),
                        "shape": area.get("shape"),
                        "coords": area.get("coords"),
                    } for area in image_map.get("areas") or []],
                } for image_map in maps],
            },
            "affectedSemanticUnits": [],
        })
    affected_lookup = {item["page"]: item for item in affected_pages}

    selected_units: dict[str, dict[str, Any]] = {}
    for unit in target_units.get("units") or []:
        unit_id = str(unit.get("unitId") or "")
        if not unit_id:
            raise ImpactFailure("Target unit entry lacks a stable unitId.")
        entry = selected_units.get(unit_id)
        if entry is None:
            selected_units[unit_id] = {
                "unitId": unit_id,
                "semanticUnitIdentity": unit.get("semanticUnitIdentity"),
                "sourcePage": str(unit.get("sourcePage") or ""),
                "selectionTypes": sorted({str(unit.get("selectionType") or "unknown")}),
            }
        else:
            if (entry["semanticUnitIdentity"] != unit.get("semanticUnitIdentity")
                    or entry["sourcePage"] != str(unit.get("sourcePage") or "")):
                raise ImpactFailure(f"Conflicting target entries share unitId {unit_id}.")
            entry["selectionTypes"] = sorted(set(entry["selectionTypes"])
                                              | {str(unit.get("selectionType") or "unknown")})
    selected_affected = []
    selected_unaffected = []
    for unit in sorted(selected_units.values(), key=lambda item: item["unitId"]):
        source_page = unit["sourcePage"]
        target = affected_lookup.get(source_page)
        entry = {
            "unitId": unit.get("unitId"),
            "semanticUnitIdentity": unit.get("semanticUnitIdentity"),
            "sourcePage": source_page,
            "selectionTypes": unit.get("selectionTypes"),
        }
        if target:
            target["affectedSemanticUnits"].append(entry)
            selected_affected.append(entry)
        else:
            selected_unaffected.append(entry)

    # A page reslice may change partition boundaries and fingerprints for every
    # existing unit on that page; limit this scope to the approved 81 pages.
    stage2a_units = [
        {"unitId": unit.get("id"), "file": unit.get("file"), "sourcePage": unit.get("sourceFile")}
        for unit in semantic_manifest.get("units") or []
        if unit.get("sourceFile") in affected_lookup
    ]
    stage2a_units.sort(key=lambda item: (str(item.get("sourcePage")), str(item.get("unitId"))))
    affected_pages.sort(key=lambda item: item["page"])

    audit_reconciliation = target.get("auditReconciliation") or {}
    output = {
        "version": 1,
        "source": {
            "targetIndex": TARGET_INDEX.relative_to(ROOT).as_posix(),
            "targetIndexSha256": sha256(target_bytes),
            "targetUnits": TARGET_UNITS.relative_to(ROOT).as_posix(),
            "targetUnitsSha256": sha256(target_units_bytes),
            "semanticUnitsManifest": SEMANTIC_MANIFEST.relative_to(ROOT).as_posix(),
            "semanticUnitsManifestSha256": sha256(semantic_manifest_bytes),
            "audit": (target.get("source") or {}).get("targetAudit"),
            "auditSha256": (target.get("source") or {}).get("targetAuditSha256"),
        },
        "scope": {
            "boundedPages": len(selected_pages),
            "affectedPages": len(affected_pages),
            "unaffectedPages": len(unaffected_pages),
            "stage2BExecuted": False,
            "stage2AExecuted": False,
        },
        "affectedPages": affected_pages,
        "unaffectedPages": unaffected_pages,
        "stage2aPlan": {
            "pagesRequiringReslice": [item["page"] for item in affected_pages],
            "existingSemanticUnitsRequiringReslice": stage2a_units,
            "targetSelectedUnitsAffected": selected_affected,
            "alreadyUnaffected": {
                "pages": sorted({str(item.get("sourcePage")) for item in selected_unaffected}),
                "targetSelectedUnits": selected_unaffected,
            },
        },
        "auditReconciliation": {
            "notesGapPages": audit_reconciliation.get("noteGapPageCount", 0),
            "notesEvidenceExcerptsExpected": audit_reconciliation.get("expectedMissingNotes", 0),
            "notesEvidenceExcerptsAccounted": audit_reconciliation.get("expectedMissingNotesCaptured", 0),
            "imageMapPagesExpected": len(audit_reconciliation.get("expectedImageMapPages") or []),
            "imageMapPagesCaptured": len(audit_reconciliation.get("expectedImageMapPagesCaptured") or []),
            "imageMapAreasExpected": audit_reconciliation.get("expectedGeometryAreas", 0),
            "imageMapAreasCaptured": audit_reconciliation.get("expectedGeometryAreasCaptured", 0),
        },
        "stage2b": {"notExecuted": True},
    }
    payload = encode(output, yaml)
    if OUTPUT.is_symlink() or not OUTPUT.resolve().is_relative_to(FACTORY.resolve()):
        raise ImpactFailure("Impact output path is unsafe.")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=FACTORY, prefix=".sparx-gap-impact-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, OUTPUT)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print({
        "affectedPages": len(affected_pages),
        "unaffectedPages": len(unaffected_pages),
        "stage2aUnitsRequiringReslice": len(stage2a_units),
        "targetSelectedUnitsAffected": len(selected_affected),
        "sha256": sha256(payload),
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImpactFailure as exc:
        raise SystemExit(f"build_target_gap_impact.py: error: {exc}") from exc
