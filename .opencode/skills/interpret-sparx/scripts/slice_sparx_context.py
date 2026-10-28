#!/usr/bin/env python3
"""Deterministically slice approved context; never interpret source evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any


SOURCE = ".factory/sparx-context.yml"
PRIMARY = ("headings", "properties", "textBlocks", "tables", "operations", "activities", "processes",
           "links", "imageMaps", "notes")
FIELDS = (*PRIMARY, "diagrams", "imageReferences", "anchors")
IDENTITY = ("id", "evidenceKey", "file", "title", "breadcrumb", "selectionReasons")
ADMIN_PROPERTY_NAMES = {
    "created", "modified", "author", "version", "phase", "complexity",
    "difficulty", "priority", "multiplicity", "advanced", "uuid",
}
SEMANTIC_INPUT_FINGERPRINT_ALGORITHM = "sha256-canonical-json-v1"
SEMANTIC_UNIT_IDENTITY_ALGORITHM = "page-evidence-partition-sha256-v1"


class SliceFailure(Exception):
    pass


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def within(path: Path, root: Path) -> bool:
    return path.is_relative_to(root)


def yaml_support() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise SliceFailure("PyYAML is required; dependencies are never installed dynamically.") from exc
    return yaml


def encode(value: Any, yaml: Any) -> bytes:
    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True
    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=120).encode("utf-8")


def load(payload: bytes, yaml: Any) -> Any:
    try:
        return yaml.load(payload, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise SliceFailure("Invalid YAML; no output was published.") from exc


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def semantic_evidence(unit: dict[str, Any]) -> dict[str, Any]:
    evidence = unit.get("evidence") or {}
    semantic: dict[str, Any] = {}
    for field in FIELDS:
        items = evidence.get(field) or []
        if field == "properties":
            items = [item for item in items if str(item.get("name", "")).strip().casefold() not in ADMIN_PROPERTY_NAMES]
        elif field == "tables":
            filtered_tables = []
            for table in items:
                table_class = str(table.get("class") or "").casefold()
                if set(table_class.split()) & {"contentmaintable", "objectdetails"}:
                    continue
                clone = dict(table)
                headers = clone.get("headers") or []
                if headers and len(headers) >= 2:
                    rows = []
                    for row in clone.get("rows") or []:
                        label = str(row[0]).strip().rstrip(":").casefold() if row else ""
                        if label in ADMIN_PROPERTY_NAMES:
                            continue
                        rows.append(row)
                    clone["rows"] = rows
                filtered_tables.append(clone)
            items = filtered_tables
        semantic[field] = items
    return semantic


def semantic_relevant_metadata(unit: dict[str, Any]) -> dict[str, Any]:
    meta = dict(unit.get("pageMetadata") or {})
    for key in ("selectionReasons", "visualMetadata", "legends", "lifecycleStates"):
        meta.pop(key, None)
    page_meta = unit.get("pageMetadata") or {}
    states = page_meta.get("lifecycleStates") or []
    legends = page_meta.get("legends") or []
    referenced_visual_ids: set[str] = set()
    for state in states:
        referenced_visual_ids.update(state.get("evidenceIds") or [])
        for key in ("elementEvidenceId", "visualEvidenceId"):
            if state.get(key):
                referenced_visual_ids.add(state[key])
    for legend in legends:
        for mapping in legend.get("mappings") or []:
            referenced_visual_ids.update(mapping.get("visualEvidenceIds") or [])
            if mapping.get("styleEvidenceId"):
                referenced_visual_ids.add(mapping["styleEvidenceId"])
    visual_metadata = [
        item for item in (page_meta.get("visualMetadata") or [])
        if item.get("evidenceId") in referenced_visual_ids
    ]
    return {
        "pageMetadata": meta,
        "visualMetadata": visual_metadata,
        "legends": legends,
        "lifecycleStates": states,
    }


def stamp_authority_branch(unit: dict[str, Any], branch: dict[str, Any] | None) -> dict[str, Any]:
    """Attach source-authority branch provenance (from sparx-target-authority.yml) to a unit.

    The stamp participates in semanticUnitIdentity and semanticInputFingerprint so evidence from
    parallel Sparx branches can never be treated as the same unit or reused across branches.
    Units without a stamp keep their historical hashes.
    """
    result = dict(unit)
    if branch:
        result["authorityBranch"] = {key: branch.get(key) for key in ("branchRootId", "branchRootGuid", "authorityClass")}
    return result


def semantic_input_payload(unit: dict[str, Any]) -> dict[str, Any]:
    unit_info = unit.get("unit") or {}
    payload = _semantic_input_payload_core(unit, unit_info)
    if unit.get("authorityBranch"):
        payload["authorityBranch"] = unit["authorityBranch"]
    return payload


def _semantic_input_payload_core(unit: dict[str, Any], unit_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "pageIdentity": {
            "pageId": unit_info.get("pageId"),
            "evidenceKey": unit_info.get("evidenceKey"),
            "file": unit_info.get("file"),
            "title": unit_info.get("title"),
            "breadcrumb": unit_info.get("breadcrumb") or [],
        },
        "pageMetadata": semantic_relevant_metadata(unit),
        "evidence": semantic_evidence(unit),
        "context": {
            "structuralParents": (unit.get("context") or {}).get("structuralParents") or [],
            "structuralChildren": (unit.get("context") or {}).get("structuralChildren") or [],
            "relevantLinkedPages": [
                {key: value for key, value in page.items() if key != "selected"}
                for page in (unit.get("context") or {}).get("relevantLinkedPages") or []
            ],
        },
        "validation": unit.get("validation") or {"warnings": [], "errors": []},
    }


def semantic_input_fingerprint(unit: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(semantic_input_payload(unit))).hexdigest()


def semantic_unit_identity(unit: dict[str, Any]) -> str:
    unit_info = unit.get("unit") or {}
    page_identity = str(unit_info.get("evidenceKey") or unit_info.get("pageId") or
                        hashlib.sha256(str(unit_info.get("file") or "").encode("utf-8")).hexdigest())
    evidence = semantic_evidence(unit)
    partition: dict[str, list[str]] = {}
    for field, items in evidence.items():
        partition[field] = []
        for item in items:
            identity = (str(item.get("evidenceId")) if isinstance(item, dict) and item.get("evidenceId")
                        else hashlib.sha256(canonical_bytes(item)).hexdigest())
            if field == "imageMaps" and isinstance(item, dict):
                identity += ":areas=" + ",".join(
                    str(area.get("evidenceId") or hashlib.sha256(canonical_bytes(area)).hexdigest())
                    for area in item.get("areas") or []
                )
            partition[field].append(identity)
    page_meta = unit.get("pageMetadata") or {}
    partition["lifecycleStates"] = sorted(
        str(item.get("evidenceId")) for item in page_meta.get("lifecycleStates") or []
        if item.get("evidenceId")
    )
    partition["legends"] = sorted(
        [str(legend.get("evidenceId"))]
        + [str(entry.get("evidenceId")) for entry in legend.get("entries") or [] if entry.get("evidenceId")]
        + [str(mapping.get("evidenceId")) for mapping in legend.get("mappings") or [] if mapping.get("evidenceId")]
        for legend in page_meta.get("legends") or [] if legend.get("evidenceId")
    )
    if unit.get("authorityBranch"):
        partition["authorityBranch"] = unit["authorityBranch"]
    partition_hash = hashlib.sha256(canonical_bytes(partition)).hexdigest()
    page_hash = hashlib.sha256(page_identity.encode("utf-8")).hexdigest()
    # Keep the deterministic part ordinal as a final disambiguator. Sparse EA
    # pages can repeat the same evidence IDs across oversized context-only parts.
    suffix = f":part-{int(unit_info.get('part') or 0):04d}"
    return f"semantic-page-{page_hash}:partition-{partition_hash}{suffix}"


def add_semantic_metadata(unit: dict[str, Any]) -> dict[str, Any]:
    result = dict(unit)
    result["semanticUnitIdentity"] = semantic_unit_identity(unit)
    result["semanticInputFingerprint"] = semantic_input_fingerprint(unit)
    return result


def repo_root() -> Path:
    for root in Path(__file__).resolve().parents:
        if (root / "AGENTS.md").is_file() and (root / ".factory").is_dir():
            return root
    raise SliceFailure("Cannot find repository root.")


def paths(root: Path, input_arg: Path, output_arg: Path) -> tuple[Path, Path]:
    expected = root / SOURCE
    logical_input = Path(os.path.abspath(root / input_arg))
    logical_output = Path(os.path.abspath(root / output_arg))
    factory = root / ".factory"
    if logical_input != expected or expected.is_symlink() or expected.resolve() != expected:
        raise SliceFailure(f"Input must be the canonical regular file {SOURCE}.")
    if not expected.is_file():
        raise SliceFailure("Approved context does not exist.")
    if not within(logical_output, factory) or logical_output == factory:
        raise SliceFailure("Output must be a dedicated directory under .factory/.")
    for path in (logical_output, *logical_output.parents):
        if path == root:
            break
        if path.is_symlink() or path.resolve() != path:
            raise SliceFailure("Symlinks/junctions are not permitted in output paths.")
    if logical_output.exists() and not logical_output.is_dir():
        raise SliceFailure("Output must be a directory.")
    return expected, logical_output


def primary_ids(page: dict[str, Any]) -> list[str]:
    result = []
    for field in PRIMARY:
        for item in page.get(field, []):
            if field == "notes" and isinstance(item, str):
                # Legacy global indexes stored note text here without evidence IDs.
                continue
            if not isinstance(item, dict) or not isinstance(item.get("evidenceId"), str) or not item["evidenceId"]:
                raise SliceFailure(f"Primary evidence lacks evidenceId in {field}.")
            result.append(item["evidenceId"])
            if field == "imageMaps":
                for area in item.get("areas") or []:
                    if not isinstance(area, dict) or not isinstance(area.get("evidenceId"), str) or not area["evidenceId"]:
                        raise SliceFailure("Image-map area lacks evidenceId.")
                    result.append(area["evidenceId"])
    return result


def page_issues(issues: list[dict[str, Any]], page: dict[str, Any]) -> list[dict[str, Any]]:
    identifier = str(page.get("id") or "").strip("{}").casefold()
    return [issue for issue in issues if issue.get("source") == page["file"] or
            (identifier and issue.get("code") == "duplicate_page_identifier" and
             str(issue.get("target") or "").strip("{}").casefold() == identifier)]


def skeleton(page: dict[str, Any], pages: dict[str, dict[str, Any]], relationships: list[dict[str, Any]],
             validation: dict[str, Any]) -> dict[str, Any]:
    def summary(file: str) -> dict[str, Any]:
        p = pages.get(file, {})
        return {"file": file, "id": p.get("id"), "title": p.get("title"), "selected": file in pages}
    parents = [r for r in relationships if r.get("child") == page["file"]]
    children = [r for r in relationships if r.get("parent") == page["file"]]
    links = sorted({link["target"] for link in page.get("links", [])
                    if link.get("kind") == "internal-page" and link.get("resolved") and link.get("target")})
    return {
        "unit": {"id": None, "pageId": page.get("id"), "file": page["file"],
                 "title": page.get("title"), "breadcrumb": page.get("breadcrumb", []),
                 "selectionReasons": page.get("selectionReasons", []),
                 "evidenceKey": page.get("evidenceKey"), "part": None, "parts": None,
                 "fieldRanges": {}},
        "pageMetadata": {key: value for key, value in page.items() if key not in FIELDS and key not in IDENTITY},
        "evidence": {field: [] for field in FIELDS},
        "context": {"structuralParents": parents, "structuralChildren": children,
                    "relevantLinkedPages": [summary(file) for file in links]},
        "validation": {"warnings": page_issues(validation.get("warnings", []), page),
                       "errors": page_issues(validation.get("errors", []), page)},
    }


def slice_context(context: dict[str, Any], fingerprint: str, max_bytes: int, yaml: Any,
                  output_relative: str, source_file: str = SOURCE) -> tuple[dict[str, bytes], dict[str, Any]]:
    if not isinstance(context, dict) or not isinstance(context.get("pages"), list):
        raise SliceFailure("Invalid context structure.")
    if (context.get("selection", {}).get("ambiguity", {}).get("detected") or
            context.get("selection", {}).get("noMatch", {}).get("detected")):
        raise SliceFailure("Context selection is unresolved.")
    pages = sorted(context["pages"], key=lambda p: p["file"])
    by_file = {p["file"]: p for p in pages}
    if not pages or len(by_file) != len(pages):
        raise SliceFailure("Context must contain nonempty, unique pages.")
    for p in pages:
        file = PurePosixPath(p["file"])
        if file.is_absolute() or ".." in file.parts or "\\" in p["file"] or ":" in p["file"]:
            raise SliceFailure("Page file must be repository-relative.")
        for field in FIELDS:
            if not isinstance(p.get(field, []), list):
                raise SliceFailure(f"Invalid evidence collection {field}.")
    source_ids = [eid for page in pages for eid in primary_ids(page)]
    if len(source_ids) != len(set(source_ids)):
        raise SliceFailure("Primary evidence IDs are duplicated; explicit reconciliation is required.")
    artifacts: dict[str, bytes] = {}
    entries = []
    seen_unit_identities: set[str] = set()
    output_ids = []
    validation = context.get("validation", {})
    for page in pages:
        base = skeleton(page, by_file, context.get("relationships", []), validation)
        records = [(field, i, item) for field in FIELDS for i, item in enumerate(page.get(field, []))]
        chunks: list[list[tuple[str, int, Any]]] = []
        chunk: list[tuple[str, int, Any]] = []
        size = len(encode(base, yaml)) + 2048
        for record in records:
            item_payload = encode({record[0]: [record[2]]}, yaml)
            item_size = len(item_payload) + 8 * item_payload.count(b"\n") + 128
            if chunk and size + item_size > max_bytes:
                chunks.append(chunk)
                chunk = []
                size = len(encode(base, yaml)) + 2048
            chunk.append(record)
            size += item_size
        if chunk or not chunks:
            chunks.append(chunk)
        for part, records in enumerate(chunks, 1):
            unit = skeleton(page, by_file, context.get("relationships", []), validation)
            unit_id = f"page-{digest(page['file'].encode('utf-8'))}:part:{part:04d}"
            unit["unit"].update({"id": unit_id, "part": part, "parts": len(chunks)})
            for field, index, item in records:
                unit["evidence"][field].append(item)
                ranges = unit["unit"]["fieldRanges"]
                if field not in ranges:
                    ranges[field] = {"start": index, "endExclusive": index + 1}
                else:
                    ranges[field]["endExclusive"] = index + 1
            unit = add_semantic_metadata(unit)
            if unit["semanticUnitIdentity"] in seen_unit_identities:
                raise SliceFailure("Stable semantic-unit identity collision; partition is not uniquely addressable.")
            seen_unit_identities.add(unit["semanticUnitIdentity"])
            ids = primary_ids(unit["evidence"])
            output_ids.extend(ids)
            payload = encode(unit, yaml)
            if len(payload) > max_bytes:
                unit["validation"]["warnings"].append({
                    "code": "unit_size_limit_exceeded", "source": page["file"],
                    "message": "An indivisible evidence item or page context exceeds the byte budget; nothing was truncated.",
                    "maxBytes": max_bytes,
                })
                payload = encode(unit, yaml)
            name = f"unit-{len(entries) + 1:04d}.yml"
            artifacts[name] = payload
            entries.append({"id": unit_id,
                            "file": f"{output_relative}/{name}",
                            "sourceFile": page["file"], "pageId": page.get("id"),
                            "part": part, "parts": len(chunks), "evidenceCount": len(ids),
                            "semanticUnitIdentity": unit["semanticUnitIdentity"],
                            "semanticInputFingerprint": unit["semanticInputFingerprint"],
                            "sha256": digest(payload), "bytes": len(payload),
                            "warnings": len(unit["validation"]["warnings"]),
                            "errors": len(unit["validation"]["errors"])})
            entries[-1]["semanticUnitIdentity"] = unit["semanticUnitIdentity"]
            entries[-1]["semanticInputFingerprint"] = unit["semanticInputFingerprint"]
    if Counter(source_ids) != Counter(output_ids):
        raise SliceFailure("Evidence reconciliation failed.")
    manifest = {
        "source": {"contextFile": source_file, "contextFingerprint": fingerprint,
                   "contextProvenance": context.get("source"),
                   "target": context.get("selection", {}).get("selectedRoot")},
        "configuration": {
            "maxUnitBytes": max_bytes,
            "fieldOrder": list(FIELDS),
            "semanticInputFingerprintAlgorithm": SEMANTIC_INPUT_FINGERPRINT_ALGORITHM,
            "semanticUnitIdentityAlgorithm": SEMANTIC_UNIT_IDENTITY_ALGORITHM,
        },
        "statistics": {"pages": len(pages), "units": len(entries), "evidenceItems": len(source_ids)},
        "units": entries,
        "validation": {"warnings": validation.get("warnings", []), "errors": validation.get("errors", [])},
    }
    artifacts["manifest.yml"] = encode(manifest, yaml)
    return artifacts, manifest


def build_target_gap_context(root: Path, index_arg: Path, impact_arg: Path, yaml: Any) -> tuple[dict[str, Any], bytes, str]:
    factory = root / ".factory"
    index_path = (root / index_arg).resolve() if not index_arg.is_absolute() else index_arg.resolve()
    impact_path = (root / impact_arg).resolve() if not impact_arg.is_absolute() else impact_arg.resolve()
    for path in (index_path, impact_path):
        if path.is_symlink() or not path.is_file() or not within(path, factory.resolve()):
            raise SliceFailure("Targeted index and impact inputs must be regular files under .factory/.")
    index_bytes = index_path.read_bytes()
    impact_bytes = impact_path.read_bytes()
    index = load(index_bytes, yaml)
    impact = load(impact_bytes, yaml)
    if digest(index_bytes) != (impact.get("source") or {}).get("targetIndexSha256"):
        raise SliceFailure("Target gap index hash does not match the approved impact artifact.")
    global_manifest_path = factory / "sparx-semantic-units" / "manifest.yml"
    global_manifest_bytes = global_manifest_path.read_bytes()
    if digest(global_manifest_bytes) != (impact.get("source") or {}).get("semanticUnitsManifestSha256"):
        raise SliceFailure("Existing Stage 2A manifest differs from the approved impact provenance.")
    declared_affected = [str(item.get("page") or "") for item in impact.get("affectedPages") or []]
    unaffected = [str(item) for item in impact.get("unaffectedPages") or []]
    target_pages = [str(page.get("file") or "") for page in index.get("pages") or []]
    if (len(declared_affected) != 60 or len(set(declared_affected)) != 60
            or len(unaffected) != 21 or len(set(unaffected)) != 21
            or len(target_pages) != 81 or len(set(target_pages)) != 81
            or set(declared_affected).intersection(unaffected)
            or set(declared_affected) | set(unaffected) != set(target_pages)):
        raise SliceFailure("Impact and target index do not establish the exact 60/21/81-page scope.")
    by_file = {str(page.get("file")): page for page in index.get("pages") or []}
    pages = []
    for page_file in sorted(declared_affected):
        page = by_file[page_file]
        prepared = dict(page)
        prepared["selectionReasons"] = []
        for field in FIELDS:
            prepared.setdefault(field, [])
        pages.append(prepared)
    context = {
        "source": {
            "index": index_path.relative_to(root).as_posix(),
            "indexSha256": digest(index_bytes),
            "impact": impact_path.relative_to(root).as_posix(),
            "impactSha256": digest(impact_bytes),
            "globalStage2AManifest": global_manifest_path.relative_to(root).as_posix(),
            "globalStage2AManifestSha256": digest(global_manifest_bytes),
            "targetSetPages": len(target_pages),
            "unaffectedPagesExcluded": len(unaffected),
        },
        "selection": {"selectedRoot": None, "ambiguity": {"detected": False}, "noMatch": {"detected": False}},
        "pages": pages,
        "relationships": index.get("relationships") or [],
        "validation": index.get("validation") or {"warnings": [], "errors": []},
    }
    return context, index_bytes, index_path.relative_to(root).as_posix()


def write_artifacts(output: Path, artifacts: dict[str, bytes], yaml: Any,
                    expected_source: str = SOURCE) -> None:
    old_files: set[str] = set()
    if output.exists() and any(output.iterdir()):
        manifest_path = output / "manifest.yml"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise SliceFailure("Refusing to overwrite an unowned/nonempty output directory.")
        old = load(manifest_path.read_bytes(), yaml)
        if old.get("source", {}).get("contextFile") != expected_source:
            raise SliceFailure("Existing output manifest has different ownership.")
        for item in old.get("units", []):
            name = PurePosixPath(item["file"]).name
            if not re.fullmatch(r"unit-\d{4,}\.yml", name):
                raise SliceFailure("Invalid owned unit filename.")
            path = output / name
            if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != item.get("sha256"):
                raise SliceFailure("Existing owned unit was changed or is missing; refusing replacement.")
            old_files.add(name)
        allowed = old_files | {"manifest.yml"}
        for p in output.iterdir():
            if p.is_symlink() or not p.is_file() or p.name not in allowed:
                raise SliceFailure("Output contains unowned files or symlinks.")
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in artifacts.items():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=output, prefix=".slice-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
            os.replace(temporary, output / name)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    for name in sorted(old_files - set(artifacts)):
        (output / name).unlink()


def refresh_existing_semantic_metadata(output: Path, yaml: Any) -> dict[str, Any]:
    """Backfill identities/fingerprints only; does not re-slice or alter evidence."""
    manifest_path = output / "manifest.yml"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise SliceFailure("Existing semantic-unit manifest is required for metadata-only refresh.")
    manifest = load(manifest_path.read_bytes(), yaml)
    if manifest.get("source", {}).get("contextFile") != SOURCE:
        raise SliceFailure("Semantic-unit manifest has unexpected ownership.")
    entries = manifest.get("units")
    if not isinstance(entries, list) or not entries:
        raise SliceFailure("Semantic-unit manifest has no units.")
    prepared: list[tuple[Path, dict[str, Any], dict[str, Any], bytes]] = []
    identities: set[str] = set()
    unit_names: set[str] = set()
    for entry in entries:
        relative = str(entry.get("file") or "")
        pure = PurePosixPath(relative)
        name = pure.name
        if (pure.parent.as_posix() != output.relative_to(output.parents[1]).as_posix()
                or not re.fullmatch(r"unit-\d{4,}\.yml", name) or name in unit_names):
            raise SliceFailure(f"Unexpected semantic-unit path in manifest: '{relative}'.")
        unit_names.add(name)
        unit_path = output / name
        if unit_path.is_symlink() or not unit_path.is_file():
            raise SliceFailure(f"Missing/untrusted semantic unit '{relative}'.")
        original_payload = unit_path.read_bytes()
        if digest(original_payload) != entry.get("sha256"):
            raise SliceFailure(f"Existing unit hash does not match manifest: '{relative}'.")
        unit = load(original_payload, yaml)
        original_evidence = {
            "unit": unit.get("unit"),
            "pageMetadata": unit.get("pageMetadata"),
            "evidence": unit.get("evidence"),
            "context": unit.get("context"),
            "validation": unit.get("validation"),
        }
        refreshed = add_semantic_metadata(unit)
        if refreshed["semanticUnitIdentity"] in identities:
            raise SliceFailure("Stable semantic-unit identity collision during metadata backfill.")
        identities.add(refreshed["semanticUnitIdentity"])
        assert original_evidence == {
            "unit": refreshed.get("unit"),
            "pageMetadata": refreshed.get("pageMetadata"),
            "evidence": refreshed.get("evidence"),
            "context": refreshed.get("context"),
            "validation": refreshed.get("validation"),
        }
        rendered = encode(refreshed, yaml)
        prepared.append((unit_path, refreshed, entry, rendered))

    # Publish unit metadata atomically per file, then refresh the owning manifest.
    for unit_path, refreshed, entry, rendered in prepared:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=output, prefix=".metadata-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(rendered)
            os.replace(temporary, unit_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        entry["semanticUnitIdentity"] = refreshed["semanticUnitIdentity"]
        entry["semanticInputFingerprint"] = refreshed["semanticInputFingerprint"]
        entry["sha256"] = digest(rendered)
        entry["bytes"] = len(rendered)
    configuration = manifest.setdefault("configuration", {})
    configuration["semanticInputFingerprintAlgorithm"] = SEMANTIC_INPUT_FINGERPRINT_ALGORITHM
    configuration["semanticUnitIdentityAlgorithm"] = SEMANTIC_UNIT_IDENTITY_ALGORITHM
    write_payload = encode(manifest, yaml)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output, prefix=".manifest-metadata-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(write_payload)
        os.replace(temporary, manifest_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return manifest


def backfill_metadata_only(output: Path, yaml: Any) -> dict[str, Any]:
    """Alias documenting this operation as metadata-only, not a semantic reslice."""
    return refresh_existing_semantic_metadata(output, yaml)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--max-unit-bytes", type=int, default=65536)
    parser.add_argument("--metadata-only", action="store_true",
                        help="Backfill fingerprints/identities into existing units without re-slicing.")
    parser.add_argument("--target-gap-index", type=Path,
                        help="Enriched target index for the exact impacted-page Stage 2A reslice.")
    parser.add_argument("--target-gap-impact", type=Path,
                        help="Authoritative Phase 8.2 affected/unaffected page scope.")
    parser.add_argument("--target-output", type=Path,
                        help="Dedicated output directory used with target-gap mode.")
    args = parser.parse_args()
    try:
        root = repo_root()
        yaml = yaml_support()
        if args.metadata_only:
            if (args.input is not None or args.output is not None or args.target_gap_index
                    or args.target_gap_impact or args.target_output):
                raise SliceFailure("--metadata-only takes no positional paths.")
            output = root / ".factory/sparx-semantic-units"
            if not within(output, root / ".factory") or output.is_symlink():
                raise SliceFailure("Unsafe metadata-only output directory.")
            manifest = backfill_metadata_only(output, yaml)
            print(manifest["statistics"])
            return 0
        if args.max_unit_bytes < 4096:
            raise SliceFailure("Byte budget must be at least 4096.")
        if bool(args.target_gap_index) != bool(args.target_gap_impact):
            raise SliceFailure("--target-gap-index and --target-gap-impact must be supplied together.")
        if args.target_gap_index and args.target_gap_impact:
            if args.input is not None or args.output is not None or args.target_output is None:
                raise SliceFailure("Target gap mode requires --target-output and no positional input/output.")
            output = ((root / args.target_output).absolute() if not args.target_output.is_absolute()
                      else args.target_output.absolute())
            expected_output = (root / ".factory/sparx-target-gap-semantic-units").resolve()
            factory = (root / ".factory").resolve()
            if (output.is_symlink() or not within(output, factory) or output.resolve() != expected_output
                    or output.name != "sparx-target-gap-semantic-units"):
                raise SliceFailure("Target gap mode must write only .factory/sparx-target-gap-semantic-units/.")
            context, source_bytes, source_file = build_target_gap_context(
                root, args.target_gap_index, args.target_gap_impact, yaml
            )
            artifacts, manifest = slice_context(
                context, digest(source_bytes), args.max_unit_bytes, yaml,
                output.relative_to(root).as_posix(), source_file,
            )
            manifest["targetedScope"] = {
                "mode": "phase-8.2-affected-pages-only",
                "affectedPages": 60,
                "unaffectedPagesResliced": 0,
                "pagesOutsideBoundedSetRead": 0,
                "outOfScopeLinksTraversed": 0,
                "stage2BExecuted": False,
            }
            artifacts["manifest.yml"] = encode(manifest, yaml)
            write_artifacts(output, artifacts, yaml, expected_source=source_file)
        else:
            if args.target_output is not None:
                raise SliceFailure("--target-output is available only with target gap mode.")
            if args.input is None or args.output is None:
                raise SliceFailure("Input and output paths are required unless --metadata-only or target-gap mode is used.")
            source, output = paths(root, args.input, args.output)
            payload = source.read_bytes()
            context = load(payload, yaml)
            artifacts, manifest = slice_context(context, digest(payload), args.max_unit_bytes,
                                                 yaml, output.relative_to(root).as_posix())
            write_artifacts(output, artifacts, yaml)
        print(manifest["statistics"])
        return 0
    except (SliceFailure, OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"slice_sparx_context.py: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
