#!/usr/bin/env python3
"""Deterministically reconcile normalized OpenAPI with target-only Sparx semantics."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any


OPENAPI_PATH = Path(".factory/openapi-spec.yml")
SPARX_PATH = Path(".factory/sparx-spec.yml")
OUTPUT_PATH = Path(".factory/service-spec.yml")
PRIMARY_FIELDS = ("headings", "properties", "textBlocks", "tables", "operations", "activities", "processes", "links")
VALIDATION_KEYWORDS = {
    "required", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "format", "enum", "minItems", "maxItems",
    "uniqueItems", "minProperties", "maxProperties", "const",
}
METHOD_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S+)\s*$", re.IGNORECASE)


class ReconciliationFailure(Exception):
    pass


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def yaml_support() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ReconciliationFailure("PyYAML must already be installed; no dependencies are installed dynamically.") from exc
    return yaml


def safe_read_yaml(path: Path, yaml: Any, root: Path) -> tuple[Any, bytes]:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ReconciliationFailure(f"Missing or unsafe approved input: {path}")
    payload = path.read_bytes()
    try:
        value = yaml.load(payload, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise ReconciliationFailure(f"Invalid YAML: {path}") from exc
    return (value or {}), payload


def encode_yaml(value: Any, yaml: Any) -> bytes:
    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True
    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=120).encode("utf-8")


def normalized_method(method: Any) -> str:
    return str(method or "").strip().upper()


def normalized_path(path: Any) -> str:
    value = str(path or "").strip()
    value = re.sub(r"/{2,}", "/", value)
    if len(value) > 1:
        value = value.rstrip("/")
    return value


def json_pointer_token(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def walk_constraints(value: Any, pointer: str) -> list[dict[str, Any]]:
    """Extract only literal OpenAPI schema/parameter constraints with JSON pointers."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = pointer + "/" + json_pointer_token(key)
            if key in VALIDATION_KEYWORDS:
                found.append({"keyword": key, "value": copy.deepcopy(child), "jsonPointer": child_pointer})
            found.extend(walk_constraints(child, child_pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(walk_constraints(child, pointer + "/" + str(index)))
    return found


def operation_validations(operation: dict[str, Any], op_pointer: str) -> list[dict[str, Any]]:
    roots = (("parameters", operation.get("parameters") or {}),
             ("requestBody", operation.get("requestBody") or {}))
    constraints = []
    for section, subtree in roots:
        constraints.extend(walk_constraints(subtree, op_pointer + "/" + section))
    unique = {}
    for item in constraints:
        key = (item["jsonPointer"], item["keyword"], json.dumps(item["value"], ensure_ascii=False, sort_keys=True))
        unique[key] = item
    return [unique[key] for key in sorted(unique)]


def sparx_identity(record: dict[str, Any]) -> tuple[str | None, str | None]:
    method = record.get("method")
    path = record.get("path")
    if method and path:
        return normalized_method(method), normalized_path(path)
    raw = str(record.get("action") or record.get("operation") or "").strip()
    match = METHOD_RE.fullmatch(raw)
    if match:
        return normalized_method(match.group(1)), normalized_path(match.group(2))
    return None, None


def refs(item: dict[str, Any]) -> set[str]:
    return set(map(str, item.get("evidenceIds") or item.get("evidence") or []))


def merge_exact_operations(items: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    rank = {"unsupported": 0, "ambiguous": 1, "derived-structural": 2, "explicit": 3}
    for item in items:
        method, path = sparx_identity(item)
        if not method or not path:
            continue
        key = (method, path)
        if key not in merged:
            merged[key] = copy.deepcopy(item)
            merged[key]["evidenceIds"] = sorted(refs(item))
            continue
        prior = merged[key]
        # Exact method/path identity is evidence-backed. Preserve all citations and
        # provenance without strengthening semantic confidence.
        prior["evidenceIds"] = sorted(set(prior.get("evidenceIds", [])) | refs(item))
        prior_sources = {x.get("unitId"): x for x in prior.get("sourceUnits", [])}
        prior_sources.update({x.get("unitId"): x for x in item.get("sourceUnits", [])})
        prior["sourceUnits"] = [prior_sources[k] for k in sorted(prior_sources) if k]
        prior["sourcePages"] = sorted({x.get("sourcePage") for x in prior["sourceUnits"] if x.get("sourcePage")})
        prior["semanticInputFingerprints"] = sorted({x.get("semanticInputFingerprint") for x in prior["sourceUnits"]
                                                       if x.get("semanticInputFingerprint")})
        old_conf = prior.get("confidenceClass")
        new_conf = item.get("confidenceClass")
        if new_conf and (not old_conf or rank.get(new_conf, 0) < rank.get(old_conf, 0)):
            prior["confidenceClass"] = new_conf
        prior["supportingStatements"] = sorted(set(prior.get("supportingStatements", [])) |
                                                set(item.get("supportingStatements", [])))
    return merged


def source_inventory(source_unit: dict[str, Any]) -> set[str]:
    inventory = set()
    for field in PRIMARY_FIELDS:
        for item in (source_unit.get("evidence") or {}).get(field) or []:
            if isinstance(item, dict) and item.get("evidenceId"):
                inventory.add(str(item["evidenceId"]))
    return inventory


def _enforce_consistency_gate():
    """Mandatory Sparx/Swagger consistency gate: no consolidation, planning or generation unless it is cleared (service workspace)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "service-workspace" / "scripts"))
    import gate_guard
    return gate_guard.enforce()


def main() -> int:
    _gate_exit = _enforce_consistency_gate()
    if _gate_exit is not None:
        return _gate_exit
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--readiness-only", action="store_true",
                        help="Recalculate readiness on the existing service-spec without reconciling semantics.")
    parser.add_argument("--archetype", type=Path,
                        help="Available archetype.yml required by --readiness-only.")
    args = parser.parse_args()
    try:
        root = Path.cwd().resolve()
        factory = root / ".factory"
        yaml = yaml_support()
        if args.readiness_only:
            if not args.archetype:
                raise ReconciliationFailure("--archetype is required with --readiness-only.")
            return recalculate_readiness(root, args.output, args.archetype, yaml)
        openapi, openapi_bytes = safe_read_yaml(root / OPENAPI_PATH, yaml, root)
        sparx, sparx_bytes = safe_read_yaml(root / SPARX_PATH, yaml, root)
        output = (root / args.output).absolute()
        if output.parent.resolve() != factory.resolve() or output.is_symlink():
            raise ReconciliationFailure("Output must be a regular file directly under .factory/.")

        openapi_source = openapi.get("source") or {}
        sparx_source = sparx.get("source") or {}
        openapi_fingerprint = str(openapi_source.get("sha256") or digest(openapi_bytes))
        openapi_artifact_fingerprint = digest(openapi_bytes)
        sparx_fingerprint = digest(sparx_bytes)
        operations = openapi.get("operations") or []
        if not operations:
            raise ReconciliationFailure("Normalized OpenAPI has no active operations.")

        operation_keys: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        for index, operation in enumerate(operations):
            key = (normalized_method(operation.get("method")), normalized_path(operation.get("path")))
            if not all(key):
                raise ReconciliationFailure(f"OpenAPI operation {index} lacks method or path.")
            operation_keys[key].append((index, operation))
        duplicate_openapi = [key for key, values in operation_keys.items() if len(values) != 1]
        if duplicate_openapi:
            raise ReconciliationFailure(f"Normalized OpenAPI has duplicate active method/path pairs: {duplicate_openapi}")

        sparx_active = ((sparx.get("active") or {}).get("operations") or [])
        sparx_ops = merge_exact_operations(sparx_active)
        sparx_unmatched = []
        operation_specs = []
        conflicts = []
        openapi_cover = set()
        matched_count = partial_count = no_behavior_count = ambiguous_count = 0

        for key, op_entries in sorted(operation_keys.items()):
            index, operation = op_entries[0]
            op_pointer = f"/operations/{index}"
            candidates = sparx_ops.get(key)
            op_id = operation.get("operationId")

            # Conflicts require the same explicit operationId on two active assertions.
            id_mismatches = [item for item in sparx_active
                             if item.get("operationId") and op_id
                             and item.get("operationId") == op_id
                             and sparx_identity(item) != key]
            if id_mismatches:
                conflict = {"type": "active-operation-identity-mismatch", "operationId": op_id,
                            "openapi": {"method": key[0], "path": key[1]},
                            "sparx": [{"method": sparx_identity(value)[0], "path": sparx_identity(value)[1],
                                       "evidenceIds": sorted(refs(value)), "sourceUnits": value.get("sourceUnits", [])}
                                      for value in id_mismatches]}
                conflicts.append(conflict)
                status = "ambiguous"
                behavior_actions = []
                ambiguous_count += 1
            elif candidates:
                status = "matched"
                behavior_actions = [copy.deepcopy(candidates)]
                openapi_cover.add(key)
                matched_count += 1
            else:
                explicit_id = [item for item in sparx_active if item.get("operationId") == op_id and op_id]
                route_references = []
                for candidate in explicit_id:
                    route_references.append(candidate)
                if route_references:
                    status = "partially-matched"
                    behavior_actions = [copy.deepcopy(value) for value in route_references]
                    partial_count += 1
                else:
                    status = "no-sparx-behavior"
                    behavior_actions = []
                    no_behavior_count += 1

            operation_specs.append(build_operation(operation, index, status, behavior_actions,
                                                   sparx, openapi, openapi_fingerprint,
                                                   openapi_artifact_fingerprint))

        for key, item in sorted(sparx_ops.items()):
            if key not in operation_keys:
                sparx_unmatched.append({"method": key[0], "path": key[1],
                                        "evidenceIds": item.get("evidenceIds", []),
                                        "sourceUnits": item.get("sourceUnits", []),
                                        "reason": "Active Sparx operation has no exact active OpenAPI method/path; retained for review, not emitted as an API operation."})

        inactive_operations = copy.deepcopy(((sparx.get("inactive") or {}).get("operations") or []))
        for inactive_item in inactive_operations:
            method, path = sparx_identity(inactive_item)
            if not method or not path:
                method = normalized_method(inactive_item.get("method"))
                path = normalized_path(inactive_item.get("path"))
            if inactive_item.get("lifecycle", {}).get("disposition") != "inactive":
                raise ReconciliationFailure("Inactive operation is missing explicit inactive disposition.")
            if inactive_item.get("lifecycle", {}).get("state") != "ELIMINADO":
                # Other explicit inactive labels remain literal; never replace them.
                pass
            inactive_item["method"] = method
            inactive_item["path"] = path
            inactive_item["contractConflict"] = False

        if len(operation_specs) != len(operations) or len({(o["method"], o["path"]) for o in operation_specs}) != len(operations):
            raise ReconciliationFailure("Not every active OpenAPI operation appears exactly once.")

        active_semantic = sparx.get("active") or {}
        behavior_context = {key: copy.deepcopy(active_semantic.get(key) or [])
                            for key in ("processes", "actions", "integrations", "persistence", "validations", "mappings", "errors")}
        unresolved_sparx = sparx.get("unresolved") or {}
        all_ambiguities = copy.deepcopy(unresolved_sparx.get("ambiguities") or [])
        all_missing = copy.deepcopy(unresolved_sparx.get("missingEvidence") or [])
        for entry in sparx_unmatched:
            all_ambiguities.append({"type": "unmatched-active-sparx-operation", **entry})

        review_decisions = copy.deepcopy((sparx.get("traceability") or {}).get("reviewedDecisions") or [])
        openapi_validation = copy.deepcopy(openapi.get("validation") or {})
        spec = {
            "service": {"name": (openapi.get("service") or {}).get("title"),
                        "contractVersion": (openapi.get("service") or {}).get("version"),
                        "description": (openapi.get("service") or {}).get("description"),
                        "servers": copy.deepcopy(openapi.get("servers") or []),
                        "source": {"path": ".factory/openapi-spec.yml", "fingerprint": openapi_fingerprint,
                                   "artifactSha256": openapi_artifact_fingerprint}},
            "sources": {
                "openapi": {"path": ".factory/openapi-spec.yml", "fingerprint": openapi_fingerprint,
                            "artifactSha256": openapi_artifact_fingerprint,
                            "validation": openapi_validation},
                "sparx": {"path": ".factory/sparx-spec.yml", "fingerprint": sparx_fingerprint},
            },
            "operations": operation_specs,
            "behaviorContext": behavior_context,
            "inactive": {"operations": inactive_operations,
                         "actions": copy.deepcopy((sparx.get("inactive") or {}).get("actions") or []),
                         "integrations": copy.deepcopy((sparx.get("inactive") or {}).get("integrations") or [])},
            "unresolved": {"conflicts": conflicts, "ambiguities": all_ambiguities,
                           "missingEvidence": all_missing},
            "warnings": {"openapi": copy.deepcopy((openapi.get("validation") or {}).get("warnings") or []),
                         "sparx": copy.deepcopy(sparx.get("warnings") or [])},
            "traceability": {
                "openapi": {"artifact": ".factory/openapi-spec.yml", "fingerprint": openapi_fingerprint,
                            "artifactSha256": openapi_artifact_fingerprint,
                            "operations": [{"operationId": o.get("operationId"), "method": o["method"], "path": o["path"],
                                            "jsonPointer": f"/operations/{i}"} for i, o in enumerate(operations)]},
                "sparx": {"artifact": ".factory/sparx-spec.yml", "fingerprint": sparx_fingerprint,
                          "evidenceUsed": copy.deepcopy((sparx.get("traceability") or {}).get("evidenceUsed") or []),
                          "sourceUnits": copy.deepcopy((sparx.get("traceability") or {}).get("sourceUnits") or []),
                          "reviewedDecisions": review_decisions,
                          "lifecycleStates": copy.deepcopy((sparx.get("traceability") or {}).get("lifecycleStates") or [])},
            },
            "statistics": {"activeOpenapiOperations": len(operations), "matched": matched_count,
                           "partiallyMatched": partial_count, "noSparxBehavior": no_behavior_count,
                           "ambiguous": ambiguous_count, "inactiveSparxOperations": len(inactive_operations),
                           "conflicts": len(conflicts)},
            "readiness": {},
            "validation": {"warnings": [], "errors": []},
        }

        contract_complete = bool(openapi_validation.get("valid")) and not (openapi_validation.get("errors") or []) and all(
            operation.get("operationId") and operation.get("contract", {}).get("responses")
            and operation.get("contract", {}).get("security") is not None
            for operation in operation_specs)
        behavior_complete = not all_ambiguities and not all_missing and all(
            operation["behavior"]["matchStatus"] == "matched" for operation in operation_specs)
        required_sparx_gaps = bool(all_missing or all_ambiguities)
        implementation_ready = contract_complete and behavior_complete and not required_sparx_gaps
        blockers = []
        if all_missing:
            blockers.extend(f"Missing behavior evidence: {item.get('reason', 'unspecified gap')}" for item in all_missing)
        if all_ambiguities:
            blockers.extend(f"Unresolved behavior ambiguity: {item.get('reason', item.get('type', 'unspecified'))}"
                            for item in all_ambiguities)
        if any(operation["behavior"]["matchStatus"] != "matched" for operation in operation_specs):
            blockers.append("One or more active OpenAPI operations lack exact Sparx behavior matches.")
        spec["readiness"] = {"contractComplete": contract_complete, "behaviorComplete": behavior_complete,
                              "implementationReady": implementation_ready, "blockers": blockers,
                              "nonBlockingIssues": [f"Sparx warning: {(w.get('warning') or {}).get('code', w.get('code', 'warning'))}"
                                                    for w in (sparx.get("warnings") or [])]}

        # Validate citations on the emitted cross-source document using only source units directly referenced by it.
        unit_paths: dict[str, set[str]] = {}
        source_refs = spec["traceability"]["sparx"]["sourceUnits"]
        for source in source_refs:
            unit_file = PurePosixPath(str(source.get("inputFile") or ""))
            if unit_file.is_absolute() or ".." in unit_file.parts or unit_file.parts[:2] != (".factory", "sparx-semantic-units"):
                raise ReconciliationFailure(f"Unsafe directly referenced target unit: {unit_file}")
            unit = safe_read_yaml(root / Path(*unit_file.parts), yaml, root)[0]
            if unit.get("semanticUnitIdentity") != source.get("semanticUnitIdentity"):
                raise ReconciliationFailure(f"Target unit identity mismatch: {unit_file}")
            if unit.get("semanticInputFingerprint") != source.get("semanticInputFingerprint"):
                raise ReconciliationFailure(f"Target unit fingerprint mismatch: {unit_file}")
            unit_paths[str(source["unitId"])] = source_inventory(unit)
        reviewed_evidence = set()
        for reviewed in review_decisions:
            reviewed_evidence.update(map(str, reviewed.get("evidenceIds") or []))
        evidence_universe = set().union(*unit_paths.values()) if unit_paths else set()
        for operation in operation_specs:
            for category in ("actions", "processes", "integrations", "persistence", "validations", "errors"):
                for behavior in operation["behavior"].get(category, []):
                    verify_semantic_refs(behavior, evidence_universe, unit_paths, reviewed_evidence)
        for category in ("processes", "actions", "integrations", "persistence", "validations", "mappings", "errors"):
            for behavior in behavior_context.get(category, []):
                verify_semantic_refs(behavior, evidence_universe, unit_paths, reviewed_evidence)
        for operation in inactive_operations:
            verify_semantic_refs(operation, evidence_universe, unit_paths, reviewed_evidence)
            decision_refs = set(map(str, operation.get("reviewedDecisionEvidenceIds") or []))
            if operation.get("reviewedDecisionId") and not decision_refs <= reviewed_evidence:
                raise ReconciliationFailure("Inactive-operation decision citations do not resolve to reviewed-decision provenance.")
        for lifecycle in spec["traceability"]["sparx"]["lifecycleStates"]:
            verify_semantic_refs(lifecycle, evidence_universe, unit_paths, reviewed_evidence)
        trace_evidence = set(map(str, spec["traceability"]["sparx"]["evidenceUsed"] or []))
        if not trace_evidence <= (evidence_universe | reviewed_evidence):
            raise ReconciliationFailure("Sparx evidenceUsed includes IDs outside referenced target units/reviewed decision.")
        if not {source["unitId"] for source in source_refs} <= set(unit_paths):
            raise ReconciliationFailure("Not all referenced target units were validated.")
        for category in ("ambiguities", "missingEvidence"):
            for unresolved in all_ambiguities if category == "ambiguities" else all_missing:
                verify_semantic_refs(unresolved, evidence_universe, unit_paths, reviewed_evidence,
                                     allow_empty=(category == "missingEvidence"))
        if conflicts:
            spec["validation"]["warnings"].append("Active source conflicts block affected reconciliation.")

        payload = encode_yaml(spec, yaml)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=factory, prefix=".service-spec-", delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(payload)
            os.replace(temp_path, output)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        print({"activeOperations": len(operation_specs), "matched": matched_count,
               "partiallyMatched": partial_count, "noSparxBehavior": no_behavior_count,
               "ambiguous": ambiguous_count, "inactiveSparxOperations": len(inactive_operations),
               "conflicts": len(conflicts), "contractComplete": contract_complete,
               "behaviorComplete": behavior_complete, "implementationReady": implementation_ready,
               "bytes": len(payload), "sha256": digest(payload)})
        return 0
    except (ReconciliationFailure, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"reconcile_specs.py: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


def recalculate_readiness(root: Path, output_arg: Path, archetype_arg: Path, yaml: Any) -> int:
    """Update only service-spec readiness from its existing reconciled content."""
    output = (root / output_arg).absolute()
    factory = root / ".factory"
    if output.parent.resolve() != factory.resolve() or output.is_symlink():
        raise ReconciliationFailure("Readiness output must be a regular file directly under .factory/.")
    archetype_path = (root / archetype_arg).absolute()
    if (archetype_path.is_symlink() or not archetype_path.is_file()
            or not archetype_path.resolve().is_relative_to(root)):
        raise ReconciliationFailure(f"Missing or unsafe archetype manifest: {archetype_arg}")

    spec, original_bytes = safe_read_yaml(output, yaml, root)
    archetype, _ = safe_read_yaml(archetype_path, yaml, root)
    operations = spec.get("operations") or []
    inactive = ((spec.get("inactive") or {}).get("operations") or [])
    prior = spec.get("readiness") or {}
    contract_complete = bool(prior.get("contractComplete"))
    behavior_complete = bool(prior.get("behaviorComplete"))
    blockers = copy.deepcopy(prior.get("blockers") or [])

    active_keys = {(normalized_method(item.get("method")), normalized_path(item.get("path")))
                   for item in operations}
    inactive_keys = {(normalized_method(item.get("method")), normalized_path(item.get("path")))
                     for item in inactive}
    operations_known = bool(operations) and all(
        item.get("operationId") and normalized_method(item.get("method"))
        and normalized_path(item.get("path")) and item.get("contract") is not None
        for item in operations)
    inactive_excluded = not (active_keys & inactive_keys)
    archetype_available = bool((archetype.get("archetype") or {}).get("id")
                                and (archetype.get("archetype") or {}).get("version"))
    unresolved_explicit = bool(blockers) and all(
        (item.get("behavior") or {}).get("unresolved")
        for item in operations
    ) if not behavior_complete else True

    required_gaps = any(
        gap.get("implementationBlocker") is not False
        for item in operations
        for gap in ((item.get("behavior") or {}).get("unresolved") or {}).get("missingEvidence", [])
    )
    unresolved_root = spec.get("unresolved") or {}
    strict_ready = (contract_complete and behavior_complete and not blockers and not required_gaps
                    and not (unresolved_root.get("conflicts") or [])
                    and not (unresolved_root.get("ambiguities") or []))
    scaffold_ready = (contract_complete and operations_known and inactive_excluded
                      and archetype_available and unresolved_explicit)
    unresolved = []
    if not behavior_complete:
        unresolved.extend(copy.deepcopy(blockers))
        for item in operations:
            behavior = item.get("behavior") or {}
            gaps = (behavior.get("unresolved") or {}).get("missingEvidence") or []
            ambiguities = (behavior.get("unresolved") or {}).get("ambiguities") or []
            for gap in gaps + ambiguities:
                unresolved.append({"operationId": item.get("operationId"), **copy.deepcopy(gap)})

    scope = {
        "allowedScope": [
            "Maven/project and package structure from the available archetype",
            "Spring Boot bootstrap and archetype-owned configuration, logging, security, and deployment baselines",
            "OpenAPI-derived API interfaces and request/response DTOs",
            "OpenAPI-declared validation and explicitly declared contract error/status shapes",
            "Empty contract-level test skeletons without invented business assertions",
        ],
        "excludedScope": [
            "Concrete business or operation behavior and behavior-bearing controller implementations",
            "Ports/interfaces without evidence establishing their existence and semantics",
            "Request-to-domain mappings not supported by evidence",
            "Integration clients or calls, including retry behavior",
            "Persistence operations, repositories, entities, SQL, and entity/data mappings",
            "Business tests, sequence/ordering rules, and inferred outcomes",
        ],
        "unresolvedBehavior": unresolved,
    }
    spec["readiness"] = {
        **prior,
        "contractComplete": contract_complete,
        "behaviorComplete": behavior_complete,
        "strictImplementationReady": strict_ready,
        "implementationReady": strict_ready,
        "scaffoldImplementationReady": scaffold_ready,
        "scaffoldReadiness": {"value": scaffold_ready, **scope},
        "blockers": blockers,
    }
    readiness_start = original_bytes.rfind(b"\nreadiness:\n")
    validation_start = original_bytes.find(b"\nvalidation:\n", readiness_start)
    if readiness_start < 0 or validation_start < 0:
        raise ReconciliationFailure("Existing service-spec readiness/validation sections are missing.")
    readiness_start += 1
    validation_start += 1
    readiness_bytes = encode_yaml({"readiness": spec["readiness"]}, yaml)
    payload = original_bytes[:readiness_start] + readiness_bytes + original_bytes[validation_start:]
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=factory, prefix=".service-readiness-", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(payload)
        os.replace(temp_path, output)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    print({"contractComplete": contract_complete, "behaviorComplete": behavior_complete,
           "implementationReady": strict_ready, "strictImplementationReady": strict_ready,
           "scaffoldImplementationReady": scaffold_ready, "bytes": len(payload),
           "sha256": digest(payload)})
    return 0


def build_operation(operation: dict[str, Any], index: int, match_status: str,
                    behavior_actions: list[dict[str, Any]], sparx: dict[str, Any],
                    openapi: dict[str, Any], openapi_fingerprint: str,
                    artifact_fingerprint: str) -> dict[str, Any]:
    path = normalized_path(operation.get("path"))
    method = normalized_method(operation.get("method"))
    pointer = f"/operations/{index}"
    parameters = copy.deepcopy(operation.get("parameters") or {})
    response_map = copy.deepcopy(operation.get("responses") or {})
    headers = {"request": copy.deepcopy(parameters.get("header") or []),
               "responses": {status: copy.deepcopy(response.get("headers") or {})
                             for status, response in response_map.items()}}
    security = copy.deepcopy(operation.get("security") if operation.get("security") is not None
                              else (openapi.get("security") or {}).get("root"))
    contract_source = {"path": ".factory/openapi-spec.yml", "fingerprint": openapi_fingerprint,
                       "artifactSha256": artifact_fingerprint, "operationIndex": index}
    contract = {
        "summary": copy.deepcopy(operation.get("summary")),
        "description": copy.deepcopy(operation.get("description")),
        "tags": copy.deepcopy(operation.get("tags") or []),
        "deprecated": copy.deepcopy(operation.get("deprecated")),
        "pathItem": copy.deepcopy(operation.get("pathItem") or {}),
        "parameters": parameters,
        "headers": headers,
        "requestBody": copy.deepcopy(operation.get("requestBody")),
        "responses": response_map,
        "security": security,
        "servers": {"root": copy.deepcopy(openapi.get("servers") or []),
                    "operation": copy.deepcopy(operation.get("servers"))},
        "validations": operation_validations(operation, pointer),
        "provenance": {
            "operation": {**contract_source, "jsonPointer": pointer},
            "method": {**contract_source, "jsonPointer": pointer + "/method"},
            "path": {**contract_source, "jsonPointer": pointer + "/path"},
            "operationId": {**contract_source, "jsonPointer": pointer + "/operationId"},
            "summary": {**contract_source, "jsonPointer": pointer + "/summary"},
            "description": {**contract_source, "jsonPointer": pointer + "/description"},
            "tags": {**contract_source, "jsonPointer": pointer + "/tags"},
            "deprecated": {**contract_source, "jsonPointer": pointer + "/deprecated"},
            "pathItem": {**contract_source, "jsonPointer": pointer + "/pathItem"},
            "parameters": {**contract_source, "jsonPointer": pointer + "/parameters"},
            "headers": {"request": {**contract_source, "jsonPointer": pointer + "/parameters/header"},
                        "responses": {status: {**contract_source,
                                                "jsonPointer": pointer + "/responses/" + json_pointer_token(status) + "/headers"}
                                      for status in response_map}},
            "requestBody": {**contract_source, "jsonPointer": pointer + "/requestBody"},
            "responses": {**contract_source, "jsonPointer": pointer + "/responses"},
            "security": {**contract_source, "jsonPointer": pointer + "/security"},
            "servers": {"root": {"path": ".factory/openapi-spec.yml", "fingerprint": openapi_fingerprint,
                                  "artifactSha256": artifact_fingerprint, "jsonPointer": "/servers"},
                        "operation": {**contract_source, "jsonPointer": pointer + "/servers"}},
            "validations": {**contract_source,
                            "jsonPointers": [pointer + "/parameters", pointer + "/requestBody"]},
        },
    }
    per_op_ambiguities = []
    per_op_missing = []
    # Attach unresolved Sparx issues only when they cite the matched operation's evidence.
    matched_evidence = set()
    for action in behavior_actions:
        matched_evidence.update(refs(action))
    for group, sink in (("ambiguities", per_op_ambiguities), ("missingEvidence", per_op_missing)):
        for issue in ((sparx.get("unresolved") or {}).get(group) or []):
            if matched_evidence.intersection(map(str, issue.get("evidenceIds") or [])):
                sink.append(copy.deepcopy(issue))
    behavior = {
        "matchStatus": match_status,
        "processes": [],
        "actions": behavior_actions,
        "integrations": [],
        "persistence": [],
        "validations": [],
        "errors": [],
    }
    return {"operationId": copy.deepcopy(operation.get("operationId")), "method": method, "path": path,
            "contract": contract, "behavior": behavior,
            "unresolved": {"ambiguities": per_op_ambiguities, "missingEvidence": per_op_missing},
            "traceability": {"openapi": contract_source,
                             "sparx": [{"sourceUnit": item.get("sourceUnits", []),
                                        "sourcePages": item.get("sourcePages", []),
                                        "evidenceIds": sorted(refs(item)),
                                        "semanticInputFingerprints": item.get("semanticInputFingerprints", [])}
                                       for item in behavior_actions]}}


def verify_semantic_refs(item: dict[str, Any], inventory: set[str],
                         unit_inventories: dict[str, set[str]], reviewed_evidence: set[str],
                         allow_empty: bool = False) -> None:
    citations = set(map(str, item.get("evidenceIds") or item.get("evidence") or []))
    if not citations and not allow_empty:
        raise ReconciliationFailure("A consolidated semantic item has no evidenceIds.")
    source_units = item.get("sourceUnits") or []
    source_unit_ids = {str(source.get("unitId")) for source in source_units}
    accessible = set().union(*(unit_inventories.get(uid, set()) for uid in source_unit_ids)) if source_unit_ids else set()
    # Decision legend IDs are external to Stage 2A units but are preserved verbatim in reviewed-decision traceability.
    allowed = accessible | (reviewed_evidence if item.get("reviewedDecisionId") else set())
    if not citations <= allowed:
        raise ReconciliationFailure(f"Consolidated citation has no referenced source unit/decision: {sorted(citations - allowed)}")
    if item.get("confidenceClass") not in {"explicit", "derived-structural", "ambiguous", "unsupported"}:
        raise ReconciliationFailure("Consolidated semantic item has an invalid/missing confidenceClass.")


if __name__ == "__main__":
    raise SystemExit(main())
