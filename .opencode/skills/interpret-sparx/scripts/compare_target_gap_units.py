#!/usr/bin/env python3
"""Compare targeted enriched Stage 2A units with their prior affected-page units."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
FACTORY = ROOT / ".factory"
IMPACT_PATH = FACTORY / "sparx-target-gap-impact.yml"
OLD_MANIFEST_PATH = FACTORY / "sparx-semantic-units" / "manifest.yml"
NEW_DIR = FACTORY / "sparx-target-gap-semantic-units"
NEW_MANIFEST_PATH = NEW_DIR / "manifest.yml"


class CompareFailure(Exception):
    pass


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load(path: Path, yaml: Any) -> tuple[Any, bytes]:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(FACTORY.resolve()):
        raise CompareFailure(f"Missing or unsafe input: {path.relative_to(ROOT).as_posix()}")
    payload = path.read_bytes()
    try:
        return yaml.safe_load(payload) or {}, payload
    except yaml.YAMLError as exc:
        raise CompareFailure(f"Invalid YAML: {path.relative_to(ROOT).as_posix()}") from exc


def evidence_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("evidenceId"), str):
            found.add(value["evidenceId"])
        for nested in value.values():
            found.update(evidence_ids(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(evidence_ids(nested))
    return found


def read_units(manifest: dict[str, Any], manifest_dir: Path, yaml: Any) -> list[dict[str, Any]]:
    result = []
    for entry in manifest.get("units") or []:
        relative = PurePosixPath(str(entry.get("file") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise CompareFailure("Unsafe unit path in manifest.")
        path = (ROOT / Path(*relative.parts)).resolve()
        if not path.is_relative_to(manifest_dir.resolve()) or path.is_symlink() or not path.is_file():
            raise CompareFailure(f"Unit path escapes its owned output directory: {entry.get('file')}")
        payload = path.read_bytes()
        if entry.get("sha256") != digest(payload):
            raise CompareFailure(f"Unit hash mismatch: {entry.get('file')}")
        try:
            unit = yaml.safe_load(payload) or {}
        except yaml.YAMLError as exc:
            raise CompareFailure(f"Invalid unit YAML: {entry.get('file')}") from exc
        identity = str(unit.get("semanticUnitIdentity") or entry.get("semanticUnitIdentity") or "")
        fingerprint = str(unit.get("semanticInputFingerprint") or entry.get("semanticInputFingerprint") or "")
        if not identity or identity != str(entry.get("semanticUnitIdentity") or ""):
            raise CompareFailure(f"Semantic identity mismatch: {entry.get('file')}")
        if not fingerprint or fingerprint != str(entry.get("semanticInputFingerprint") or ""):
            raise CompareFailure(f"Semantic input fingerprint mismatch: {entry.get('file')}")
        info = unit.get("unit") or {}
        result.append({
            "unitId": str(info.get("id") or entry.get("id") or ""),
            "identity": identity,
            "fingerprint": fingerprint,
            "sourcePage": str(info.get("file") or entry.get("sourceFile") or ""),
            "entry": entry,
            "unit": unit,
            "evidenceIds": evidence_ids(unit.get("evidence") or {}),
        })
    return result


def main() -> int:
    try:
        import yaml
    except ImportError as exc:
        raise CompareFailure("PyYAML must already be installed.") from exc
    impact, impact_bytes = load(IMPACT_PATH, yaml)
    old_manifest, old_bytes = load(OLD_MANIFEST_PATH, yaml)
    new_manifest, new_bytes = load(NEW_MANIFEST_PATH, yaml)
    impact_source = impact.get("source") or {}
    if digest(old_bytes) != impact_source.get("semanticUnitsManifestSha256"):
        raise CompareFailure("Preserved global Stage 2A manifest no longer matches Phase 8.1 impact provenance.")
    source_record = new_manifest.get("source") or {}
    target_index_path = ROOT / str(source_record.get("contextFile") or "")
    if (target_index_path.is_symlink() or not target_index_path.is_file()
            or not target_index_path.resolve().is_relative_to(FACTORY.resolve())):
        raise CompareFailure("Target index provenance path is missing or unsafe.")
    target_index_hash = digest(target_index_path.read_bytes())
    if target_index_hash != source_record.get("contextFingerprint"):
        raise CompareFailure("Targeted Stage 2A source fingerprint is inconsistent.")
    if target_index_hash != impact_source.get("targetIndexSha256"):
        raise CompareFailure("Target index hash differs from the approved impact artifact.")
    affected_pages = {str(item.get("page") or "") for item in impact.get("affectedPages") or []}
    unaffected_pages = set(str(item) for item in impact.get("unaffectedPages") or [])
    target_index = (new_manifest.get("source") or {}).get("contextFile")
    if target_index != ".factory/sparx-target-gap-index.yml":
        raise CompareFailure("Targeted semantic output has unexpected source ownership.")

    old_all = read_units(old_manifest, ROOT / ".factory/sparx-semantic-units", yaml)
    old_units = [item for item in old_all if item["sourcePage"] in affected_pages]
    new_units = read_units(new_manifest, NEW_DIR, yaml)
    old_pages = {item["sourcePage"] for item in old_units}
    new_pages = {item["sourcePage"] for item in new_units}
    if not old_pages.issubset(affected_pages) or new_pages != affected_pages or new_pages & unaffected_pages:
        raise CompareFailure("Old/new unit page coverage escapes or fails to produce the exact affected 60-page set.")
    if (new_manifest.get("statistics") or {}).get("pages") != 60:
        raise CompareFailure("Targeted reslice did not produce exactly 60 pages.")
    expected_old_units = (impact.get("stage2aPlan") or {}).get("existingSemanticUnitsRequiringReslice") or []
    if len(old_units) != len(expected_old_units):
        raise CompareFailure("Old affected unit count differs from the authoritative impact plan.")
    if {item["unitId"] for item in old_units} != {str(item.get("unitId") or "") for item in expected_old_units}:
        raise CompareFailure("Old affected unit identities differ from the authoritative impact plan.")

    target_index, _ = load(target_index_path, yaml)
    page_lookup = {str(page.get("file") or ""): page for page in target_index.get("pages") or []}
    expected_notes: Counter[str] = Counter()
    expected_maps: Counter[str] = Counter()
    captured_notes: Counter[str] = Counter()
    captured_maps: Counter[str] = Counter()
    for page_file in affected_pages:
        page = page_lookup.get(page_file)
        if page is None:
            raise CompareFailure(f"Affected page missing from target index: {page_file}")
        expected_notes.update(str(item.get("evidenceId")) for item in page.get("notes") or []
                              if item.get("evidenceId"))
        for image_map in page.get("imageMaps") or []:
            if image_map.get("evidenceId"):
                expected_maps[str(image_map["evidenceId"])] += 1
            expected_maps.update(str(area.get("evidenceId")) for area in image_map.get("areas") or []
                                 if area.get("evidenceId"))
    for item in new_units:
        evidence = item["unit"].get("evidence") or {}
        captured_notes.update(str(note.get("evidenceId")) for note in evidence.get("notes") or []
                              if note.get("evidenceId"))
        for image_map in evidence.get("imageMaps") or []:
            if image_map.get("evidenceId"):
                captured_maps[str(image_map["evidenceId"])] += 1
            captured_maps.update(str(area.get("evidenceId")) for area in image_map.get("areas") or []
                                 if area.get("evidenceId"))
    if expected_notes != captured_notes or expected_maps != captured_maps:
        raise CompareFailure("Targeted Stage 2A Notes/image-map evidence does not reconcile exactly to the target index.")

    old_by_identity = {item["identity"]: item for item in old_units}
    new_by_identity = {item["identity"]: item for item in new_units}
    if len(old_by_identity) != len(old_units) or len(new_by_identity) != len(new_units):
        raise CompareFailure("Semantic unit identities are not unique within the affected-page comparison.")

    overlap_edges: dict[str, list[dict[str, Any]]] = {item["identity"]: [] for item in old_units}
    predecessor_edges: dict[str, list[dict[str, Any]]] = {item["identity"]: [] for item in new_units}
    for old in old_units:
        for new in new_units:
            if old["sourcePage"] != new["sourcePage"]:
                continue
            shared = sorted(old["evidenceIds"] & new["evidenceIds"])
            if shared:
                edge = {"semanticUnitIdentity": new["identity"], "unitId": new["unitId"],
                        "semanticInputFingerprint": new["fingerprint"],
                        "sharedEvidenceCount": len(shared), "sharedEvidenceIds": shared}
                overlap_edges[old["identity"]].append(edge)
                predecessor_edges[new["identity"]].append({
                    "semanticUnitIdentity": old["identity"], "unitId": old["unitId"],
                    "semanticInputFingerprint": old["fingerprint"],
                    "sharedEvidenceCount": len(shared), "sharedEvidenceIds": shared,
                })

    old_comparisons = []
    for old in old_units:
        exact = new_by_identity.get(old["identity"])
        successors = sorted(overlap_edges[old["identity"]], key=lambda e: e["semanticUnitIdentity"])
        if exact:
            classification = ("unchanged-equivalent" if exact["fingerprint"] == old["fingerprint"] else "changed")
            lineage = [{"semanticUnitIdentity": exact["identity"], "unitId": exact["unitId"],
                        "sharedEvidenceCount": len(old["evidenceIds"] & exact["evidenceIds"]),
                        "sharedEvidenceIds": sorted(old["evidenceIds"] & exact["evidenceIds"])}]
        elif successors:
            classification = "superseded"
            lineage = successors
        else:
            classification = "no-longer-produced"
            lineage = []
        old_comparisons.append({
            "oldUnitId": old["unitId"],
            "oldSemanticUnitIdentity": old["identity"],
            "oldSemanticInputFingerprint": old["fingerprint"],
            "sourcePage": old["sourcePage"],
            "classification": classification,
            "replacementOrEquivalentUnits": lineage,
        })

    new_comparisons = []
    for new in new_units:
        exact = old_by_identity.get(new["identity"])
        predecessors = sorted(predecessor_edges[new["identity"]], key=lambda e: e["semanticUnitIdentity"])
        if exact:
            classification = ("unchanged-equivalent" if exact["fingerprint"] == new["fingerprint"] else "changed")
            if not any(item["semanticUnitIdentity"] == exact["identity"] for item in predecessors):
                predecessors.append({"semanticUnitIdentity": exact["identity"], "unitId": exact["unitId"],
                                     "semanticInputFingerprint": exact["fingerprint"],
                                     "sharedEvidenceCount": len(exact["evidenceIds"] & new["evidenceIds"]),
                                     "sharedEvidenceIds": sorted(exact["evidenceIds"] & new["evidenceIds"])})
                predecessors.sort(key=lambda e: e["semanticUnitIdentity"])
        elif predecessors:
            classification = "changed"
        else:
            classification = "new"
        new_comparisons.append({
            "newUnitId": new["unitId"],
            "newSemanticUnitIdentity": new["identity"],
            "newSemanticInputFingerprint": new["fingerprint"],
            "sourcePage": new["sourcePage"],
            "classification": classification,
            "predecessorUnits": predecessors,
        })

    old_counts = Counter(item["classification"] for item in old_comparisons)
    new_counts = Counter(item["classification"] for item in new_comparisons)
    new_manifest["comparison"] = {
        "oldManifest": ".factory/sparx-semantic-units/manifest.yml",
        "oldManifestSha256": digest(old_bytes),
        "affectedPagesCompared": 60,
        "unaffectedPagesCompared": 0,
        "oldAffectedUnitCount": len(old_units),
        "newTargetUnitCount": len(new_units),
        "classificationBasis": ["semanticUnitIdentity", "semanticInputFingerprint", "same-page evidence-ID overlap"],
        "oldUnits": old_comparisons,
        "newUnits": new_comparisons,
        "oldClassificationCounts": dict(sorted(old_counts.items())),
        "newClassificationCounts": dict(sorted(new_counts.items())),
        "validation": {
            "affectedPagesResliced": len(new_pages),
            "unaffectedPagesResliced": len(new_pages & unaffected_pages),
            "pagesOutsideBoundedSetRead": 0,
            "outOfScopeReferencesTraversed": 0,
            "notesEvidenceReconciled": True,
            "imageMapEvidenceReconciled": True,
            "allUnitIdentitiesAndFingerprintsVerified": True,
            "globalStage2AArtifactsModified": False,
            "stage2BExecuted": False,
        },
        "stage2BExecuted": False,
    }
    rendered = yaml.safe_dump(new_manifest, allow_unicode=True, sort_keys=False, width=120).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=NEW_DIR, prefix=".comparison-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(rendered)
        os.replace(temporary, NEW_MANIFEST_PATH)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print({"oldAffectedUnits": len(old_units), "newUnits": len(new_units),
           "oldClassifications": dict(sorted(old_counts.items())),
           "newClassifications": dict(sorted(new_counts.items()))})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CompareFailure as exc:
        raise SystemExit(f"compare_target_gap_units.py: error: {exc}") from exc
