#!/usr/bin/env python3
"""Retrieve Sparx semantic-result items using OpenAPI names as non-semantic hints."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


OPENAPI_FILE = ".factory/openapi-spec.yml"
RESULTS_ROOT = ".factory/sparx-semantic-results"
RESULTS_MANIFEST = f"{RESULTS_ROOT}/manifest.yml"
OUTPUT_FILE = ".factory/target-sparx-semantics.yml"
CATEGORIES = ("processes", "actions", "integrations", "errors", "decisions", "validations", "persistence", "mappings")
INACTIVE_CATEGORIES = ("operations", "actions", "integrations")
CONFIDENCE_CLASSES = {"explicit", "derived-structural", "ambiguous", "unsupported"}
INACTIVE_STATES = {"eliminado", "deleted", "removed", "inactive", "retired", "disabled", "obsolete"}
ACTIVE_STATES = {"nuevo", "new", "modificado", "modified", "reutilizado", "reused", "sin cambio", "unchanged", "active", "activo"}
STOP_WORDS = {
    "api", "v", "get", "post", "put", "patch", "delete", "options", "head",
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "by",
    "id", "info", "data", "response", "request", "schema", "model", "type",
    "service", "operation", "operations", "name", "path", "endpoint", "target",
}


class SelectionFailure(Exception):
    """Raised when safe deterministic retrieval cannot continue."""


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def repository_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "AGENTS.md").is_file() and (candidate / ".factory").is_dir():
            return candidate
    raise SelectionFailure("Cannot locate repository root.")


def load_yaml_support() -> Any:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SelectionFailure("PyYAML is required; dependencies are never installed dynamically.") from exc
    return yaml


def load_yaml(path: Path, yaml: Any) -> tuple[Any, bytes]:
    try:
        payload = path.read_bytes()
        document = yaml.load(payload, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except OSError as exc:
        raise SelectionFailure(f"Cannot read '{path.as_posix()}': {exc.strerror or type(exc).__name__}.") from exc
    except yaml.YAMLError as exc:
        raise SelectionFailure(f"Invalid YAML in '{path.as_posix()}'.") from exc
    return document, payload


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.replace("\xa0", " ").split()).casefold()


def tokens(value: Any) -> set[str]:
    text = str(value or "")
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return {token for token in re.split(r"[^\w]+", normalize(text)) if token and token not in STOP_WORDS}


def scalar_values(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"evidence", "evidenceIds", "evidenceUsed", "evidenceUnused", "referenceEvidenceUsed", "referenceEvidenceUnused"}:
                continue
            if isinstance(child, (dict, list)):
                yield from scalar_values(child, f"{path}.{key}" if path else key)
            elif child is not None:
                yield (f"{path}.{key}" if path else key, str(child))
    elif isinstance(value, list):
        for item in value:
            yield from scalar_values(item, path)


def safe_factory_path(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative or ":" in relative:
        raise SelectionFailure(f"Unsafe repository-relative path in manifest: '{relative}'.")
    path = root.joinpath(*pure.parts)
    factory = root / ".factory"
    try:
        resolved = path.resolve(strict=must_exist)
        factory_resolved = factory.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SelectionFailure(f"Cannot resolve approved input path '{relative}'.") from exc
    if not resolved.is_relative_to(factory_resolved):
        raise SelectionFailure(f"Input path escapes .factory/: '{relative}'.")
    if must_exist and (not path.is_file() or path.is_symlink()):
        raise SelectionFailure(f"Expected a regular file: '{relative}'.")
    return resolved


def target_hints(openapi: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    service = openapi.get("service") or {}
    service_name = str(service.get("title") or "").strip()
    operations: list[dict[str, Any]] = []
    hints: list[dict[str, Any]] = []

    def add(kind: str, value: Any, confidence: str = "high", source: str = "") -> None:
        text = " ".join(str(value or "").split())
        if text:
            hints.append({"kind": kind, "value": text, "retrievalConfidence": confidence, "source": source})

    add("service-name", service_name, "high", "openapi.service.title")
    for op in openapi.get("operations") or []:
        operation = {
            "operationId": op.get("operationId"),
            "path": op.get("path"),
            "method": op.get("method"),
            "tags": op.get("tags") or [],
            "summary": op.get("summary"),
        }
        operations.append(operation)
        add("operation-id", op.get("operationId"), "high", "openapi.operations.operationId")
        if op.get("path"):
            hints.append({"kind": "path", "value": str(op["path"]),
                          "retrievalConfidence": "high", "source": "openapi.operations.path",
                          "method": str(op.get("method") or "").upper(),
                          "operationId": op.get("operationId")})
        method_path = " ".join(x for x in (op.get("method"), op.get("path")) if x)
        add("method-path", method_path, "high", "openapi.operations.method+path")
        add("operation-summary", op.get("summary"), "medium", "openapi.operations.summary")
        for tag in op.get("tags") or []:
            add("operation-tag", tag, "medium", "openapi.operations.tags")

    components = openapi.get("components") or {}
    schema_names = sorted((components.get("schemas") or {}).keys())
    component_hints = []
    for category, values in components.items():
        if isinstance(values, dict):
            for name in sorted(values):
                component_hints.append({"kind": "component-name", "name": name, "category": category})
                add("component-name", name, "low", f"openapi.components.{category}")
    query = {
        "service": service_name or None,
        "operations": operations,
        "paths": sorted({str(op.get("path")) for op in operations if op.get("path")}),
        "schemaNames": schema_names,
        "componentNames": component_hints,
    }
    hints.sort(key=lambda h: (h["kind"], normalize(h["value"]), h["source"]))
    return query, hints


def hint_matches(hint: dict[str, Any], fields: list[tuple[str, str]]) -> list[dict[str, Any]]:
    value = normalize(hint["value"])
    hint_tokens = tokens(hint["value"])
    found: list[dict[str, Any]] = []
    for field, observed in fields:
        normalized = normalize(observed)
        exact = normalized == value
        contains = bool(value and len(value) >= 5 and value in normalized)
        observed_http_operations = semantic_http_operations(observed)
        observed_tokens = tokens(observed)
        overlap = hint_tokens & observed_tokens
        ratio = len(overlap) / len(hint_tokens) if hint_tokens else 0.0

        # Paths and operation IDs are strong retrieval hints only when present
        # in source-derived semantic result text, not merely in the OpenAPI file.
        if hint["kind"] == "path" and observed_http_operations:
            same_path = [op for op in observed_http_operations if normalize(op[1]) == normalize(hint["value"])]
            if not same_path:
                continue
            expected_method = str(hint.get("method") or "").upper()
            if expected_method and not any(method == expected_method for method, _ in same_path):
                strength, score = "path-match-method-conflict", 48
            else:
                strength, score = "exact-operation-path", 100
        elif hint["kind"] == "operation-id":
            if exact:
                strength, score = "exact", 100
            else:
                continue
        elif hint["kind"] in {"path", "method-path"}:
            if exact or contains:
                strength, score = "exact", 100
            else:
                continue
        elif hint["kind"] == "service-name":
            if exact:
                strength, score = "exact", 90
            elif contains:
                strength, score = "contains", 82
            elif len(hint_tokens) >= 2 and ratio >= 0.75 and len(overlap) >= 2:
                strength, score = "token-overlap", 58
            else:
                continue
        elif hint["kind"] == "component-name":
            if exact:
                strength, score = "exact", 55
            elif contains:
                strength, score = "contains", 42
            elif len(hint_tokens) >= 2 and ratio == 1.0:
                strength, score = "token-overlap", 35
            else:
                continue
        else:
            if exact:
                strength, score = "exact", 74
            elif contains:
                strength, score = "contains", 66
            elif len(hint_tokens) >= 2 and ratio >= 0.75 and len(overlap) >= 2:
                strength, score = "token-overlap", 48
            else:
                continue
        found.append({
            "hintKind": hint["kind"],
            "hint": hint["value"],
            "hintSource": hint["source"],
            "matchedField": field,
            "observed": observed,
            "matchType": strength,
            "retrievalConfidence": hint["retrievalConfidence"],
            "score": score,
        })
    return found


def semantic_http_operations(value: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s*[-:]\s*(/[A-Za-z0-9_./{}-]+)", re.IGNORECASE)
    return [(method.upper(), path.rstrip(".,;:")) for method, path in pattern.findall(value)]


def retrieval_fields(item: dict[str, Any]) -> list[tuple[str, str]]:
    return [(f"semantic.{name}", value) for name, value in scalar_values(item)]


def lifecycle_metadata(item: dict[str, Any], result: dict[str, Any], allowed_evidence: set[str]) -> dict[str, Any] | None:
    lifecycle = item.get("lifecycle") or item.get("lifecycleState") or item.get("statusMetadata")
    if lifecycle is None:
        return None
    if isinstance(lifecycle, str):
        raise SelectionFailure("Lifecycle metadata must preserve state, disposition, basis and evidenceIds.")
    evidence_ids = list(lifecycle.get("evidenceIds") or lifecycle.get("evidence") or [])
    if not evidence_ids or not set(evidence_ids).issubset(allowed_evidence):
        raise SelectionFailure("Lifecycle metadata has missing or invalid evidenceIds.")
    disposition = str(lifecycle.get("disposition") or "").strip().casefold()
    state = normalize(lifecycle.get("state") or lifecycle.get("value"))
    if state in INACTIVE_STATES:
        disposition = "inactive"
    elif state in ACTIVE_STATES:
        disposition = "active"
    elif disposition not in {"active", "inactive", "unknown"}:
        disposition = "unknown"
    basis = lifecycle.get("basis") or lifecycle.get("source")
    if not basis:
        raise SelectionFailure("Lifecycle metadata must identify its explicit source basis.")
    if "color" in str(basis).casefold() and "legend" not in str(basis).casefold():
        raise SelectionFailure("Color alone cannot establish lifecycle state.")
    return {**lifecycle, "disposition": disposition, "evidenceIds": evidence_ids}


def inactive_bucket(category: str, item: dict[str, Any]) -> str:
    if category == "integrations":
        return "integrations"
    if category == "actions":
        textual = " ".join(value for _, value in scalar_values(item))
        if item.get("semanticType") == "operation" or re.search(
            r"\b(?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s*[-:]\s*/", textual, re.IGNORECASE
        ):
            return "operations"
    return "actions"


def best_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for match in matches:
        key = (match["hintKind"], normalize(match["hint"]), match["matchedField"])
        current = unique.get(key)
        if current is None or (match["score"], match["observed"]) > (current["score"], current["observed"]):
            unique[key] = match
    return sorted(unique.values(), key=lambda x: (-x["score"], x["hintKind"], normalize(x["hint"]), x["matchedField"]))


def retrieval_level(matches: list[dict[str, Any]]) -> str:
    if not matches:
        return "none"
    score = max(m["score"] for m in matches)
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def result_relevance(result: dict[str, Any], hints: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    fields = []
    for key in ("title", "file", "pageId"):
        if (result.get("source") or {}).get(key) is not None:
            fields.append((f"source.{key}", str(result["source"][key])))
    matches = best_matches([m for h in hints for m in hint_matches(h, fields)])
    return matches, retrieval_level(matches)


def append_record(container: dict[str, list[Any]], category: str, record: dict[str, Any]) -> None:
    key = category if category in container else "actions"
    container[key].append(record)


def select_from_result(result: dict[str, Any], result_file: str, input_unit: str,
                       hints: list[dict[str, Any]]) -> tuple[dict[str, list[Any]], dict[str, list[Any]], list[Any], list[Any], list[Any], Counter, bool]:
    selected = {category: [] for category in CATEGORIES}
    inactive = {category: [] for category in INACTIVE_CATEGORIES}
    ambiguous: list[dict[str, Any]] = []
    relevant_missing: list[dict[str, Any]] = []
    relevant_warnings: list[dict[str, Any]] = []
    counters: Counter = Counter()
    source_fields = [(f"source.{key}", str(value)) for key, value in (result.get("source") or {}).items()
                     if key in {"title", "file", "pageId"} and value is not None]
    all_result_items: list[tuple[str, dict[str, Any]]] = []
    semantic_block = result.get("semantic") or {}
    unknown_categories = set(semantic_block) - set(CATEGORIES)
    if unknown_categories:
        raise SelectionFailure(f"Unknown semantic categories in '{result_file}': {', '.join(sorted(unknown_categories))}.")
    for category in CATEGORIES:
        for item in semantic_block.get(category, []) or []:
            all_result_items.append((category, item))
    candidate_match_by_evidence: dict[str, list[dict[str, Any]]] = {}
    result_retrieval_relevant = False
    traceability = result.get("traceability") or {}
    allowed_evidence = set(traceability.get("evidenceUsed") or [])
    allowed_evidence.update(traceability.get("referenceEvidenceUsed") or [])

    for category, item in all_result_items:
        counters["semanticItemsScanned"] += 1
        item_class = item.get("confidenceClass")
        if item_class not in CONFIDENCE_CLASSES:
            raise SelectionFailure(f"Unknown semantic confidenceClass in '{result_file}'.")
        fields = retrieval_fields(item)
        matches = best_matches([m for h in hints for m in hint_matches(h, fields)])
        level = retrieval_level(matches)
        if not matches:
            continue
        result_retrieval_relevant = True
        evidence_ids = list(item.get("evidence") or [])
        if not evidence_ids or not set(evidence_ids).issubset(allowed_evidence):
            raise SelectionFailure(f"Invalid semantic citations in '{result_file}'.")
        lifecycle = lifecycle_metadata(item, result, allowed_evidence)
        if lifecycle is not None:
            evidence_ids = list(dict.fromkeys([*evidence_ids, *lifecycle["evidenceIds"]]))
        for evidence_id in evidence_ids:
            candidate_match_by_evidence.setdefault(evidence_id, []).extend(matches)
        record = {
            "sourceResult": result_file,
            "sourceUnit": input_unit,
            "sourceUnitId": (result.get("source") or {}).get("unitId"),
            "sourcePageId": (result.get("source") or {}).get("pageId"),
            "sourceFile": (result.get("source") or {}).get("file"),
            "semanticCategory": category,
            "semanticItemId": item.get("id"),
            "matchedHints": matches,
            "selectionReason": "Observable source-result text matches one or more OpenAPI retrieval hints; OpenAPI contributes no semantic assertion.",
            "evidenceIds": evidence_ids,
            "retrievalConfidence": {"level": level, "score": max(m["score"] for m in matches)},
            "sourceConfidenceClass": item_class,
            "semanticItem": item,
            "lifecycle": lifecycle,
        }
        if lifecycle is not None and lifecycle["disposition"] == "inactive":
            inactive[inactive_bucket(category, item)].append({
                **record,
                "inactivityReason": "Explicit lifecycle metadata marks this semantic item inactive.",
            })
            continue
        if lifecycle is not None and lifecycle["disposition"] == "unknown":
            ambiguous.append({
                **record,
                "ambiguityReason": "Lifecycle state is explicit but active/inactive disposition is unresolved.",
            })
            continue
        has_nonlow_hint = any(match.get("retrievalConfidence") in {"high", "medium"} for match in matches)
        method_conflict = any(match["matchType"] == "path-match-method-conflict" for match in matches)
        if item_class in {"ambiguous", "unsupported"} or level == "low" or not has_nonlow_hint or method_conflict:
            reason = ("Source semantic item is classified unsupported." if item_class == "unsupported"
                      else "Source semantic item is classified ambiguous." if item_class == "ambiguous"
                      else "The source operation path matches, but its explicit method conflicts with the OpenAPI retrieval hint." if method_conflict
                      else "Only low-confidence retrieval hints matched this item." if not has_nonlow_hint
                      else "Retrieval relevance is plausible but not sufficiently specific for unconditional selection.")
            ambiguous.append({**record, "ambiguityReason": reason})
        else:
            selected[category].append(record)

    result_unresolved = result.get("unresolved") or {}
    for ambiguity in result_unresolved.get("ambiguities", []) or []:
        evidence_ids = list(ambiguity.get("evidence") or [])
        matches = best_matches([m for eid in evidence_ids for m in candidate_match_by_evidence.get(eid, [])])
        if not matches:
            fields = [(f"ambiguity.{k}", v) for k, v in scalar_values(ambiguity)]
            matches = best_matches([m for h in hints for m in hint_matches(h, fields)])
        result_matches, result_level = result_relevance(result, hints)
        if matches or result_level == "high":
            result_retrieval_relevant = True
            ambiguous.append({
                "sourceResult": result_file,
                "sourceUnitId": (result.get("source") or {}).get("unitId"),
                "sourceFile": (result.get("source") or {}).get("file"),
                "ambiguity": ambiguity,
                "evidenceIds": evidence_ids,
                "matchedHints": matches or result_matches,
                "retrievalConfidence": {"level": retrieval_level(matches or result_matches),
                                        "score": max((m["score"] for m in (matches or result_matches)), default=0)},
                "selectionReason": "Potential target relevance is retained as an ambiguous candidate.",
            })
            counters["relevantResultAmbiguities"] += 1

    for missing in result_unresolved.get("missingEvidence", []) or []:
        evidence_ids = list(missing.get("evidence") or [])
        matches = best_matches([m for eid in evidence_ids for m in candidate_match_by_evidence.get(eid, [])])
        result_matches, result_level = result_relevance(result, hints)
        if matches or result_level == "high":
            result_retrieval_relevant = True
            relevant_missing.append({
                "sourceResult": result_file,
                "sourceUnitId": (result.get("source") or {}).get("unitId"),
                "sourceFile": (result.get("source") or {}).get("file"),
                "missingEvidence": missing,
                "matchedHints": matches or result_matches,
                "retrievalConfidence": {"level": retrieval_level(matches or result_matches),
                                        "score": max((m["score"] for m in (matches or result_matches)), default=0)},
            })
    for warning in result_unresolved.get("warnings", []) or []:
        result_matches, result_level = result_relevance(result, hints)
        selected_evidence = {eid for groups in (selected, inactive) for records in groups.values()
                             for record in records for eid in record["evidenceIds"]}
        ambiguous_evidence = {eid for candidate in ambiguous for eid in candidate.get("evidenceIds", [])}
        if warning.get("evidenceId") in selected_evidence | ambiguous_evidence or result_retrieval_relevant or result_level == "high":
            relevant_warnings.append({"sourceResult": result_file, "warning": warning,
                                      "matchedHints": result_matches or [m for candidate in ambiguous for m in candidate.get("matchedHints", [])],
                                      "retrievalConfidence": {"level": result_level,
                                                              "score": max((m["score"] for m in result_matches), default=0)}})

    for pending in result_unresolved.get("coveragePending", []) or []:
        evidence_id = pending.get("evidenceId")
        matches = best_matches(candidate_match_by_evidence.get(evidence_id, []))
        result_matches, result_level = result_relevance(result, hints)
        if matches or result_level == "high":
            counters["coveragePending"] += 1
            relevant_missing.append({
                "sourceResult": result_file,
                "sourceUnitId": (result.get("source") or {}).get("unitId"),
                "sourceFile": (result.get("source") or {}).get("file"),
                "coveragePending": pending,
                "matchedHints": matches or result_matches,
                "retrievalConfidence": {"level": retrieval_level(matches or result_matches),
                                        "score": max((m["score"] for m in (matches or result_matches)), default=0)},
            })
    return selected, inactive, ambiguous, relevant_missing, relevant_warnings, counters, result_retrieval_relevant


def make_dumper(yaml: Any) -> Any:
    class StableDumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True
    return StableDumper


def write_output(path: Path, value: dict[str, Any], yaml: Any) -> None:
    payload = yaml.dump(value, Dumper=make_dumper(yaml), allow_unicode=True,
                        default_flow_style=False, sort_keys=False, width=120).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openapi", default=OPENAPI_FILE)
    parser.add_argument("--manifest", default=RESULTS_MANIFEST)
    parser.add_argument("--output", default=OUTPUT_FILE)
    args = parser.parse_args()
    try:
        root = repository_root()
        if args.openapi != OPENAPI_FILE or args.manifest != RESULTS_MANIFEST or args.output != OUTPUT_FILE:
            raise SelectionFailure("This selector accepts only canonical approved inputs and output paths.")
        api_path = safe_factory_path(root, args.openapi)
        manifest_path = safe_factory_path(root, args.manifest)
        output_path = root / OUTPUT_FILE
        if output_path.exists() and output_path.is_symlink():
            raise SelectionFailure("Output must not be a symlink.")
        yaml = load_yaml_support()
        openapi, api_bytes = load_yaml(api_path, yaml)
        manifest, manifest_bytes = load_yaml(manifest_path, yaml)
        if not isinstance(openapi, dict) or not isinstance(openapi.get("operations"), list):
            raise SelectionFailure("OpenAPI normalized resource has no operations list.")
        entries = manifest.get("units")
        declared_input_units = (manifest.get("statistics") or {}).get("inputUnits")
        declared_accounted = (manifest.get("statistics") or {}).get("accountedUnits")
        if (not isinstance(entries, list) or not entries or declared_input_units != len(entries)
                or declared_accounted != len(entries)):
            raise SelectionFailure("Semantic-result manifest has no unit inventory.")
        declared_interpreted = (manifest.get("statistics") or {}).get("interpretedUnits")
        declared_pending = (manifest.get("statistics") or {}).get("pendingUnits")
        if not isinstance(declared_interpreted, int) or not isinstance(declared_pending, int) or declared_interpreted + declared_pending != len(entries):
            raise SelectionFailure("Semantic-result interpreted/pending counts do not reconcile.")
        declared_semantic_items = (manifest.get("statistics") or {}).get("semanticItemsByCategory") or {}
        if set(declared_semantic_items) != set(CATEGORIES):
            raise SelectionFailure("Semantic-result category inventory is incomplete.")
        if not re.fullmatch(r"[0-9a-f]{64}", str((manifest.get("source") or {}).get("fingerprint") or "")):
            raise SelectionFailure("Semantic-results manifest fingerprint is missing or malformed.")
        query, hints = target_hints(openapi)

        scanned_results = 0
        scanned_items = 0
        rejected_items = 0
        selected = {category: [] for category in CATEGORIES}
        inactive = {category: [] for category in INACTIVE_CATEGORIES}
        ambiguous: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        coverage_pending: list[dict[str, Any]] = []
        result_hashes: list[dict[str, str]] = []
        selected_result_files: set[str] = set()
        relevant_source_pages: set[str] = set()
        actual_category_counts: Counter = Counter()
        actual_status_counts: Counter = Counter()
        results_directory = root / RESULTS_ROOT
        expected_results_directory = root / RESULTS_ROOT
        try:
            resolved_results_directory = results_directory.resolve(strict=True)
            resolved_factory = (root / ".factory").resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SelectionFailure("Cannot safely resolve semantic-results directory.") from exc
        if results_directory.is_symlink() or resolved_results_directory != results_directory.absolute():
            raise SelectionFailure("Semantic-results directory must be canonical and not redirected.")

        for entry in sorted(entries, key=lambda item: item.get("resultFile", "")):
            result_file = str(entry.get("resultFile") or "")
            expected_name = f"unit-{len(result_hashes) + 1:04d}.yml"
            expected_file = f"{RESULTS_ROOT}/{expected_name}"
            if result_file != expected_file or entry.get("inputFile") != f".factory/sparx-semantic-units/{expected_name}":
                raise SelectionFailure(f"Unexpected result/unit path in manifest: '{result_file}'.")
            if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256") or "")):
                raise SelectionFailure(f"Missing or malformed result hash: '{result_file}'.")
            path = safe_factory_path(root, result_file)
            result, payload = load_yaml(path, yaml)
            actual_hash = sha256(payload)
            if entry.get("sha256") and actual_hash != entry["sha256"]:
                raise SelectionFailure(f"Semantic result hash mismatch: '{result_file}'.")
            if (result.get("source") or {}).get("unitId") != entry.get("id"):
                raise SelectionFailure(f"Semantic result/unit identity mismatch: '{result_file}'.")
            actual_semantic_count = sum(len(items or []) for items in (result.get("semantic") or {}).values())
            if actual_semantic_count != entry.get("semanticItemCount"):
                raise SelectionFailure(f"Semantic item count mismatch: '{result_file}'.")
            if result.get("status") != entry.get("status"):
                raise SelectionFailure(f"Semantic result status mismatch: '{result_file}'.")
            actual_status_counts[result["status"]] += 1
            for category in CATEGORIES:
                actual_category_counts[category] += len((result.get("semantic") or {}).get(category, []) or [])
            result_hashes.append({"file": result_file, "sha256": actual_hash})
            scanned_results += 1
            result_selected, result_inactive, result_ambiguous, result_missing, result_warnings, counters, item_relevant = select_from_result(
                result, result_file, str(entry.get("inputFile") or ""), hints
            )
            page_matches, page_match_level = result_relevance(result, hints)
            local_count = actual_semantic_count
            scanned_items += local_count
            selected_count = sum(len(items) for items in result_selected.values())
            inactive_count = sum(len(items) for items in result_inactive.values())
            rejected_items += local_count - selected_count - sum(
                1 for candidate in result_ambiguous if candidate.get("semanticItem") is not None
            ) - inactive_count
            if selected_count or inactive_count or result_ambiguous or result_missing or result_warnings or counters.get("coveragePending") or item_relevant:
                selected_result_files.add(result_file)
                if (result.get("source") or {}).get("file"):
                    relevant_source_pages.add(result["source"]["file"])
            if page_match_level == "high" and (result.get("source") or {}).get("file"):
                relevant_source_pages.add(result["source"]["file"])
            for category in CATEGORIES:
                selected[category].extend(result_selected[category])
            for category in INACTIVE_CATEGORIES:
                inactive[category].extend(result_inactive[category])
            ambiguous.extend(result_ambiguous)
            missing.extend(result_missing)
            warnings.extend(result_warnings)
        if actual_category_counts != Counter({category: int(declared_semantic_items[category]) for category in CATEGORIES}):
            raise SelectionFailure("Semantic-result per-category counts do not reconcile.")
        if actual_status_counts != Counter({"interpreted": declared_interpreted, "coverage-pending": declared_pending}):
            raise SelectionFailure("Semantic-result statuses do not match manifest interpreted/pending counts.")
        for entry in sorted(entries, key=lambda item: item.get("resultFile", "")):
            result_file = entry["resultFile"]
            result, _ = load_yaml(safe_factory_path(root, result_file), yaml)
            same_page_relevant = (result.get("source") or {}).get("file") in relevant_source_pages
            if same_page_relevant:
                if result_file not in selected_result_files:
                    selected_result_files.add(result_file)
                for pending in result.get("unresolved", {}).get("coveragePending", []) or []:
                    coverage_pending.append({"sourceResult": result_file, "coveragePending": pending,
                                            "selectionReason": "Another semantic unit from the same source page matched target retrieval hints."})
                for warning in result.get("validation", {}).get("warnings", []) or []:
                    warnings.append({"sourceResult": result_file, "warning": warning,
                                     "matchedHints": [],
                                     "retrievalConfidence": {"level": "medium", "score": 55},
                                     "selectionReason": "Warning preserved from another semantic unit of a relevant source page."})
                for warning in result.get("unresolved", {}).get("warnings", []) or []:
                    warnings.append({"sourceResult": result_file, "warning": warning,
                                     "matchedHints": [],
                                     "retrievalConfidence": {"level": "medium", "score": 55},
                                     "selectionReason": "Unresolved warning preserved from another semantic unit of a relevant source page."})
        coverage_pending.sort(key=lambda r: (r.get("sourceResult", ""), str(r.get("coveragePending", {}))))
        warnings = list({
            (w.get("sourceResult", ""), str(w.get("warning", {}))): w for w in warnings
        }.values())
        warnings.sort(key=lambda r: (r.get("sourceResult", ""), str(r.get("warning", {}))))

        # Keep ordering reproducible and preserve source-provided item objects.
        record_key = lambda r: (r.get("sourceResult", ""), r.get("semanticItemId") or "", r.get("semanticCategory", ""))
        for category in CATEGORIES:
            selected[category].sort(key=record_key)
        for category in INACTIVE_CATEGORIES:
            inactive[category].sort(key=record_key)
        ambiguous.sort(key=lambda r: (r.get("sourceResult", ""), r.get("semanticItemId") or "", str(r.get("ambiguity", {}))))
        missing.sort(key=lambda r: (r.get("sourceResult", ""), str(r.get("missingEvidence", {}))))
        warnings.sort(key=lambda r: (r.get("sourceResult", ""), str(r.get("warning", {}))))
        coverage_pending.sort(key=lambda r: (r.get("sourceResult", ""), str(r.get("coveragePending", {}))))
        expected_unit_names = {f"unit-{index:04d}.yml" for index in range(1, len(entries) + 1)}
        if {Path(entry["resultFile"]).name for entry in entries} != expected_unit_names:
            raise SelectionFailure("Semantic-result manifest does not contain a complete sequential unit inventory.")
        evidence_ids = sorted({eid for groups in (selected, inactive) for records in groups.values()
                               for record in records for eid in record["evidenceIds"]})
        evidence_ids.extend(eid for eid in sorted({eid for candidate in ambiguous for eid in candidate.get("evidenceIds", [])}) if eid not in evidence_ids)
        all_records = [record for records in selected.values() for record in records]
        output = {
            "source": {
                "openapi": OPENAPI_FILE,
                "openapiFingerprint": sha256(api_bytes),
                "semanticResultsManifest": RESULTS_MANIFEST,
                "semanticResultsFingerprint": sha256(manifest_bytes),
                "semanticResultFingerprints": result_hashes,
            },
            "target": {
                "service": query["service"],
                "operations": query["operations"],
                "paths": query["paths"],
                "retrievalHints": hints,
                "openapiHintsOnly": True,
            },
            "statistics": {
                "semanticResultsScanned": scanned_results,
                "semanticItemsScanned": scanned_items,
                "selectedItems": len(all_records),
                "selectedItemsByCategory": {category: len(selected[category]) for category in CATEGORIES},
                "inactiveItems": sum(len(items) for items in inactive.values()),
                "inactiveItemsByCategory": {category: len(inactive[category]) for category in INACTIVE_CATEGORIES},
                "ambiguousCandidates": len(ambiguous),
                "rejectedItems": max(0, rejected_items),
            },
            "selected": selected,
            "inactive": inactive,
            "unresolved": {
                "ambiguities": ambiguous,
                "missingEvidence": missing,
                "coveragePending": coverage_pending,
                "warnings": warnings,
            },
            "traceability": {
                "evidenceIds": evidence_ids,
                "sourceResults": sorted(selected_result_files),
            },
            "validation": {
                "warnings": [],
                "errors": [],
                "retrievalOnly": True,
                "openapiUsedAsSemanticEvidence": False,
            },
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_output(output_path, output, yaml)
        print(output["statistics"], file=sys.stderr)
        return 0
    except (SelectionFailure, OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        print(f"select_target_semantics.py: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
