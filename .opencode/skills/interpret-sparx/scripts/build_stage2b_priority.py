#!/usr/bin/env python3
"""Build a deterministic, blocker-first Stage 2B batch plan without interpreting units."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
FACTORY = ROOT / ".factory"
TARGET_PLAN = FACTORY / "target-sparx-gap-units.yml"
SERVICE_SPEC = FACTORY / "service-spec.yml"
IMPACT = FACTORY / "sparx-target-gap-impact.yml"
OUTPUT = FACTORY / "target-sparx-gap-stage2b-priority.yml"
P1_CATEGORIES = {
    "operation-specific processing",
    "persistence",
    "request/response mappings",
    "conditions",
    "integration behavior",
}
P2_CATEGORIES = {"flow relationships"}


class PlanFailure(Exception):
    pass


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stable_yaml(value: Any, yaml: Any) -> bytes:
    class StableDumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True
    return yaml.dump(value, Dumper=StableDumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=120).encode("utf-8")


def load(path: Path, yaml: Any) -> tuple[Any, bytes]:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(FACTORY.resolve()):
        raise PlanFailure(f"Missing or unsafe input: {path.relative_to(ROOT).as_posix()}")
    payload = path.read_bytes()
    try:
        return yaml.safe_load(payload) or {}, payload
    except yaml.YAMLError as exc:
        raise PlanFailure(f"Invalid YAML: {path.relative_to(ROOT).as_posix()}") from exc


def strings(value: Any, excluded: set[str] | None = None):
    excluded = excluded or {"evidenceId", "coords", "shape", "attributes", "style", "color", "fillColor"}
    if isinstance(value, dict):
        for key, nested in value.items():
            if key not in excluded:
                yield from strings(nested, excluded)
    elif isinstance(value, list):
        for nested in value:
            yield from strings(nested, excluded)
    elif isinstance(value, (str, int)):
        yield str(value)


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


def method_paths(value: str) -> set[tuple[str, str]]:
    return {(match.group(1).upper(), match.group(2).rstrip(".,;:"))
            for match in re.finditer(r"\b(GET|POST|PATCH)\s*[- ]\s*(/api/v1/[^\s<>\"']+)",
                                     value, flags=re.IGNORECASE)}


def text_of(unit: dict[str, Any]) -> str:
    info = unit.get("unit") or {}
    return " ".join([str(info.get("title") or ""), *list(strings(unit.get("evidence") or {}))]).casefold()


def method_mentions(unit: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    evidence = unit.get("evidence") or {}
    info = unit.get("unit") or {}
    texts = [str(info.get("title") or ""), *list(strings(evidence))]
    all_text = " ".join(texts).casefold()
    activities = [str(item.get("name") or "") for item in evidence.get("activities") or []]
    title = str(info.get("title") or "")
    methods: dict[str, dict[str, Any]] = {}
    for operation in operations:
        method = str(operation.get("method") or "").upper()
        path = str(operation.get("path") or "")
        exact = any((method, path) in method_paths(text) for text in texts)
        if exact:
            methods[str(operation.get("operationId"))] = {
                "operationId": operation.get("operationId"),
                "method": method,
                "path": path,
                "basis": "explicit Sparx method/path text matches active contract signature",
                "mappingEstablished": False,
            }
            continue

        # Retrieval hints are query metadata, not behavior evidence. Pair them
        # with a separately observed Sparx method/title and keep mapping open.
        matched_hints = unit.get("matchedHints") or []
        hint_match = any(str(hint).strip() == f"path:{path}" for hint in matched_hints)
        source_method = None
        for observed in [title, *activities]:
            match = re.match(r"\s*(GET|POST|PATCH)\s*[- ]\s*(/[^\s]+)", observed, flags=re.IGNORECASE)
            if match:
                source_method = (match.group(1).upper(), match.group(2))
                break
        same_id_shape = bool(source_method and source_method[1].endswith("/{id}") == path.endswith("/{id}"))
        if hint_match and source_method and source_method[0] == method and same_id_shape:
            methods[str(operation.get("operationId"))] = {
                "operationId": operation.get("operationId"),
                "method": method,
                "path": path,
                "basis": "target-retrieval path hint paired with a same-verb Sparx method; mapping is unproven",
                "mappingEstablished": False,
            }
            continue

        # An explicit URI-only image-map reference to the shared GET/POST path
        # is useful retrieval evidence but does not establish its HTTP method.
        candidate_path_signal = any(path.casefold() in str(signal).casefold()
                                    for candidate in unit.get("phaseCandidateSignals", [])
                                    for signal in candidate)
        if candidate_path_signal and path == "/api/v1/mailing/info":
            methods[str(operation.get("operationId"))] = {
                "operationId": operation.get("operationId"),
                "method": method,
                "path": path,
                "basis": "explicit target path appears in candidate evidence; method remains unspecified",
                "mappingEstablished": False,
            }
    return methods


def main() -> int:
    try:
        import yaml
    except ImportError as exc:
        raise PlanFailure("PyYAML must already be installed.") from exc
    plan, plan_bytes = load(TARGET_PLAN, yaml)
    service_spec, service_bytes = load(SERVICE_SPEC, yaml)
    impact, impact_bytes = load(IMPACT, yaml)
    target = plan.get("target") or {}
    operations = target.get("operations") or []
    active_signatures = {(str(item.get("method") or "").upper(), str(item.get("path") or ""))
                         for item in operations}
    required = {("GET", "/api/v1/mailing/info"), ("POST", "/api/v1/mailing/info"),
                ("PATCH", "/api/v1/mailing/info/{id}")}
    if active_signatures != required:
        raise PlanFailure("Target plan active operations differ from the approved operation set.")
    readiness = service_spec.get("readiness") or {}
    blockers = [item for item in readiness.get("blockers") or [] if item.get("implementationBlocker")]
    if readiness.get("strictImplementationReady") is not False or len(blockers) != 2:
        raise PlanFailure("Service-spec strict readiness blockers do not match the current two-blocker target state.")
    if plan.get("phase8_2", {}).get("stage2BPlan", {}).get("minimumUnitsRequiringStage2B") != 28:
        raise PlanFailure("Target plan Stage 2B minimum changed; refresh the prioritization inputs explicitly.")
    blocker_ids = {str(evidence_id) for blocker in blockers for evidence_id in blocker.get("evidenceIds") or []}

    impacts = {item["semanticUnitIdentity"]: item
               for item in (plan.get("phase8_2", {}).get("selectionComparison", {}).get("notesAndImageMapImpact") or [])}
    reusable_ids = set(plan.get("stage2BPlan", {}).get("reusable") or [])
    reuse_unproven_ids = set(plan.get("stage2BPlan", {}).get("reuse-unproven") or [])
    needs_ids = set(plan.get("stage2BPlan", {}).get("needs-interpretation") or [])
    units: list[dict[str, Any]] = []
    unit_by_identity: dict[str, dict[str, Any]] = {}
    for record in plan.get("units") or []:
        if record.get("selectionType") == "inactive-item":
            continue
        path = (ROOT / str(record.get("file") or "")).resolve()
        if (not path.is_relative_to(FACTORY.resolve()) or path.is_symlink() or not path.is_file()):
            raise PlanFailure(f"Unsafe target semantic unit file: {record.get('file')}")
        unit = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        identity = str(record.get("semanticUnitIdentity") or "")
        if not identity or unit.get("semanticUnitIdentity") != identity:
            raise PlanFailure(f"Semantic unit identity mismatch: {record.get('file')}")
        if unit.get("semanticInputFingerprint") != record.get("semanticInputFingerprint"):
            raise PlanFailure(f"Semantic input fingerprint mismatch: {record.get('file')}")
        impact_row = impacts.get(identity, {})
        candidate_relevance = (impact_row.get("candidateEvidenceRelevance") or {}).get("candidateRelevance") or []
        categories = sorted({str(item.get("category")) for item in candidate_relevance})
        info = unit.get("unit") or {}
        evidence = unit.get("evidence") or {}
        activity_names = [str(item.get("name") or "") for item in evidence.get("activities") or []]
        all_text = " ".join([str(info.get("title") or ""), *list(strings(evidence))]).casefold()
        blocker_evidence_matches = sorted(evidence_ids(evidence) & blocker_ids)
        active_ops = method_mentions({**unit, "matchedHints": record.get("matchedHints") or [],
                                      "phaseCandidateSignals": [str(signal)
                                          for item in candidate_relevance for ev in item.get("evidence") or []
                                          for signal in ev.get("literalSignals") or []]}, operations)
        has_inactive_get_id = bool(re.search(r"get\s*[- ]\s*/api/v1/mailing/info/\{id\}", all_text))
        direct_inactive_only = has_inactive_get_id and not active_ops
        p1_signals = sorted(set(categories) & P1_CATEGORIES)
        direct_operation_declaration = any(
            str(item.get("basis") or "").startswith("explicit Sparx method/path text")
            for item in active_ops.values()
        )
        if direct_inactive_only:
            priority = 3
            reason = "The unit's explicit GET-by-id signature is outside the active operation set and overlaps the reviewed inactive GET; defer to preserve the ELIMINADO boundary."
        elif p1_signals or direct_operation_declaration or blocker_evidence_matches:
            priority = 1
            reasons = []
            if p1_signals:
                reasons.append("candidate signal(s): " + ", ".join(p1_signals))
            if direct_operation_declaration:
                reasons.append("active operation method/path evidence")
            if blocker_evidence_matches:
                reasons.append("exact source evidence IDs cited by current strict blocker(s)")
            reason = "Priority-1 basis: " + "; ".join(reasons) + "."
        elif "flow relationships" in categories and (active_ops or evidence.get("imageMaps")):
            priority = 2
            reason = "Explicit flow/image-map links may support an active-operation execution path; no meaning is inferred from geometry."
        else:
            priority = 3
            reason = "Architectural or context evidence has no direct blocker signal for an active operation in this unit."

        existing_status = ("reusable" if record.get("unitId") in reusable_ids else
                           "reuse-unproven" if record.get("unitId") in reuse_unproven_ids else
                           "needs-interpretation" if record.get("unitId") in needs_ids else "not-in-current-plan")
        note_ids = sorted(str(item.get("evidenceId")) for item in evidence.get("notes") or [] if item.get("evidenceId"))
        map_ids = sorted(str(image_map.get("evidenceId")) for image_map in evidence.get("imageMaps") or []
                         if image_map.get("evidenceId"))
        area_ids = sorted(str(area.get("evidenceId")) for image_map in evidence.get("imageMaps") or []
                          for area in image_map.get("areas") or [] if area.get("evidenceId"))
        methods = sorted(active_ops.values(), key=lambda item: (item["method"], item["path"], item["operationId"]))
        if methods:
            relevant_operations = methods
            operation_basis = "operation-specific evidence/retrieval candidate; mapping is not asserted"
        elif p1_signals:
            relevant_operations = [{"operationId": op.get("operationId"), "method": op.get("method"),
                                    "path": op.get("path"), "basis": "strict blocker affects operation; unit-to-operation mapping unresolved",
                                    "mappingEstablished": False} for op in operations]
            operation_basis = "strict blocker scope only; no operation-specific source mapping established"
        else:
            relevant_operations = []
            operation_basis = "no active operation owner established"
        candidate_types = sorted(set(categories) |
                                 ({"Notes/documentation"} if note_ids else set()) |
                                 ({"image-map explicit links"} if area_ids else set()) |
                                 ({"active operation declarations"} if direct_operation_declaration else set()) |
                                 ({"strict-blocker cited evidence"} if blocker_evidence_matches else set()))
        result = {
            "semanticUnitIdentity": identity,
            "unitId": record.get("unitId"),
            "file": record.get("file"),
            "sourcePage": record.get("sourcePage"),
            "selectionType": record.get("selectionType"),
            "priority": priority,
            "candidateEvidenceTypes": candidate_types,
            "candidateEvidenceIds": {"notes": note_ids, "imageMaps": map_ids, "imageMapAreas": area_ids},
            "strictBlockerEvidenceIds": blocker_evidence_matches,
            "owningOrRelevantOperations": relevant_operations,
            "operationEvidenceCandidates": methods,
            "operationRelationBasis": operation_basis,
            "mappingEstablished": False,
            "reasonForPriority": reason,
            "candidateSignals": candidate_relevance,
            "existingCurrentStage2BResultReusable": existing_status == "reusable",
            "existingStage2BResultDisposition": existing_status,
            "inactiveGetByIdEvidencePresent": has_inactive_get_id,
        }
        units.append(result)
        unit_by_identity[identity] = {"record": record, "unit": unit, "summary": result,
                                      "categories": categories, "priority": priority,
                                      "candidateRelevance": candidate_relevance,
                                      "activityNames": activity_names, "allText": all_text}

    batch_ids: list[str] = []
    operation_coverage: list[dict[str, Any]] = []
    for operation in operations:
        op_id = str(operation.get("operationId"))
        signature = f"{operation.get('method')} {operation.get('path')}".casefold()
        candidates = []
        for identity, info in unit_by_identity.items():
            if info["priority"] != 1 or info["summary"]["existingCurrentStage2BResultReusable"]:
                continue
            record = info["record"]
            title = str((info["unit"].get("unit") or {}).get("title") or "").casefold()
            categories = info["categories"]
            if (str(operation.get("method") or "").upper(), str(operation.get("path") or "")) in method_paths(title) \
                    and "operation-specific processing" in categories:
                candidates.append((0, identity, info))
                continue
            if op_id in (info["summary"].get("operationEvidenceCandidates") or {}):
                exact_method_basis = info["summary"]["operationEvidenceCandidates"][op_id].get("basis", "")
                rank = 1 if "retrieval hint" in exact_method_basis else 2
                candidates.append((rank, identity, info))
        if not candidates:
            raise PlanFailure(f"No nonreusable Priority-1 unit offers retrieval coverage for {signature}.")
        _, chosen_identity, chosen = sorted(candidates, key=lambda item: (item[0], item[1]))[0]
        if chosen_identity not in batch_ids:
            batch_ids.append(chosen_identity)
        operation_coverage.append({
            "operationId": op_id,
            "method": operation.get("method"),
            "path": operation.get("path"),
            "coveredByUnits": [chosen["summary"]["semanticUnitIdentity"]],
            "coverage": "candidate evidence selected; Stage 2B must establish behavior/mapping without assuming equivalence",
        })

    inactive_source_unit_ids = {str(item.get("unitId") or "") for item in plan.get("units") or []
                                if item.get("selectionType") == "inactive-item"}
    root_candidates = [(identity, info) for identity, info in unit_by_identity.items()
                       if info["record"].get("unitId") in inactive_source_unit_ids
                       and info["priority"] == 1
                       and info["summary"]["owningOrRelevantOperations"]
                       and not info["summary"]["existingCurrentStage2BResultReusable"]]
    if root_candidates:
        root_identity, _ = sorted(root_candidates,
                                  key=lambda pair: (-len(pair[1]["summary"]["owningOrRelevantOperations"]), pair[0]))[0]
        if root_identity not in batch_ids:
            batch_ids.append(root_identity)

    # Include the explicitly reviewed service-operation source unit so Stage 2B
    # sees active method associations while the inactive GET remains separated.
    inactive_unit_ids = {str(item.get("unitId") or "") for item in plan.get("units") or []
                         if item.get("selectionType") == "inactive-item"}
    for inactive_unit_id in sorted(inactive_unit_ids):
        roots = [identity for identity, info in unit_by_identity.items()
                 if info["record"].get("unitId") == inactive_unit_id
                 and info["record"].get("selectionType") != "inactive-item"
                 and info["priority"] == 1
                 and info["summary"]["owningOrRelevantOperations"]
                 and not info["summary"]["existingCurrentStage2BResultReusable"]]
        if roots:
            root_identity = sorted(roots)[0]
            if root_identity not in batch_ids:
                batch_ids.append(root_identity)

    # Minimum cross-blocker signal cover: one unit with conditions/integration,
    # one with the densest distinct Priority-1 signals, and one mapped data object.
    def add_best(predicate, sort_key, missing_message):
        candidates = [(identity, info) for identity, info in unit_by_identity.items()
                      if identity not in batch_ids and info["priority"] == 1
                      and not info["summary"]["existingCurrentStage2BResultReusable"] and predicate(info)]
        if not candidates:
            raise PlanFailure(missing_message)
        identity, _ = sorted(candidates, key=lambda item: sort_key(item[0], item[1]))[0]
        batch_ids.append(identity)

    add_best(lambda info: {"conditions", "integration behavior"}.issubset(set(info["categories"])),
             lambda identity, info: (0 if info["record"].get("sourcePage") ==
                                      "input/sparx/PROYECT/EARoot/EA2/EA6/EA716.htm" else 1, identity),
             "No Priority-1 candidate combines condition and integration evidence.")
    add_best(lambda info: {"operation-specific processing", "persistence", "request/response mappings"}
             .issubset(set(info["categories"])),
             lambda identity, info: (identity,),
             "No multi-signal operation/persistence/mapping candidate exists.")
    add_best(lambda info: "persistence" in info["categories"] and "MAILINGINFORMATION" in info["allText"].upper(),
             lambda identity, info: (-len(info["summary"]["strictBlockerEvidenceIds"]), identity),
             "No selected MAILINGINFORMATION persistence candidate exists.")
    add_best(lambda info: "request/response mappings" in info["categories"] and
             any(name.upper().startswith("POST-") for name in info["activityNames"]),
             lambda identity, info: (identity,),
             "No POST-linked request/response mapping candidate exists.")
    add_best(lambda info: bool(info["unit"].get("evidence", {}).get("imageMaps")) and
             "operation-specific processing" in info["categories"],
             lambda identity, info: (-sum(len(ev.get("literalSignals") or []) for candidate in info["candidateRelevance"]
                                          if candidate.get("category") == "operation-specific processing"
                                          for ev in candidate.get("evidence") or []), identity),
             "No image-map candidate with an explicit active-path signal exists.")
    add_best(lambda info: bool(info["unit"].get("evidence", {}).get("imageMaps")) and
             "flow relationships" in info["categories"] and
             bool(info["summary"].get("operationEvidenceCandidates")),
             lambda identity, info: (0 if info["priority"] == 2 else 1, identity),
             "No explicit active-operation flow-map candidate exists.")

    batch_records = [unit_by_identity[identity]["summary"] for identity in batch_ids]
    if len(batch_records) < 8 or len(batch_records) > 12:
        raise PlanFailure(f"Evidence-supported minimal batch size {len(batch_records)} falls outside the 8-12 planning target.")
    if any(item["existingCurrentStage2BResultReusable"] for item in batch_records):
        raise PlanFailure("A current exact-fingerprint reusable Stage 2B result entered the first batch.")
    batch_candidate_types = {evidence_type for item in batch_records
                             for evidence_type in item["candidateEvidenceTypes"]}
    required_batch_types = {"operation-specific processing", "persistence", "request/response mappings",
                            "conditions", "integration behavior"}
    if not required_batch_types.issubset(batch_candidate_types):
        raise PlanFailure("The candidate batch does not cover all five Priority-1 strict-blocker evidence types.")
    covered = {entry["operationId"] for entry in operation_coverage}
    if covered != {str(op.get("operationId")) for op in operations}:
        raise PlanFailure("First batch does not provide separate candidate coverage for all active operations.")

    priority_groups = {
        str(level): sorted([item for item in units if item["priority"] == level],
                           key=lambda item: (-len(set(item["candidateEvidenceTypes"])
                                                  & (P1_CATEGORIES | P2_CATEGORIES)),
                                             item["semanticUnitIdentity"]))
        for level in (1, 2, 3)
    }
    flow_candidates = [item for item in units if "flow relationships" in item["candidateEvidenceTypes"]]
    first_batch = []
    for order, identity in enumerate(batch_ids, 1):
        summary = dict(unit_by_identity[identity]["summary"])
        categories = set(summary["candidateEvidenceTypes"])
        if identity in {item["semanticUnitIdentity"] for item in priority_groups["2"]}:
            reason = "Priority-2 explicit flow links are included only after the Priority-1 operation/persistence/mapping/condition/integration coverage is established."
        elif "flow relationships" in categories and "image-map explicit links" in categories:
            reason = "Priority-1 map candidate supplies explicit active-operation path/mapping evidence; its flow links are supporting signals, and geometry is not used."
        elif summary.get("inactiveGetByIdEvidencePresent"):
            reason = "Provides active method/association context; the reviewed GET-by-id evidence remains a separate inactive ELIMINADO item."
        else:
            reason = "Selected to cover a distinct active operation or a strict-blocker evidence category with no exact reusable result."
        first_batch.append({"batchOrder": order, **summary, "reasonForFirstBatch": reason})

    first_ids = set(batch_ids)
    deferred = [dict(item, deferReason=("Priority-1 signals remain behind the smaller blocker-covering batch."
                                       if item["priority"] == 1 else
                                       "Priority-2/3 evidence is deferred until the first batch establishes blocker coverage."))
                for item in units if item["semanticUnitIdentity"] not in first_ids]
    inactive_records = plan.get("units") or []
    inactive_separate = [item for item in inactive_records if item.get("selectionType") == "inactive-item"]
    plan_document = {
        "version": 1,
        "source": {
            "targetPlan": TARGET_PLAN.relative_to(ROOT).as_posix(),
            "targetPlanSha256": sha(plan_bytes),
            "serviceSpec": SERVICE_SPEC.relative_to(ROOT).as_posix(),
            "serviceSpecSha256": sha(service_bytes),
            "impact": IMPACT.relative_to(ROOT).as_posix(),
            "impactSha256": sha(impact_bytes),
        },
        "target": {"service": target.get("service"), "activeOperations": operations},
        "strictReadiness": {
            "strictImplementationReady": readiness.get("strictImplementationReady"),
            "implementationBlockers": [{key: blocker.get(key) for key in
                                         ("id", "reason", "affectedOperations", "requiredInformation", "readinessClass")}
                                        for blocker in blockers],
        },
        "scope": {
            "activeCandidateUnits": len(units),
            "unaffectedPagesWithoutCurrentStage2AUnitsDeferred": plan.get("phase8_2", {}).get("scope", {}).get(
                "unaffectedPagesWithoutCurrentUnits", []),
            "unaffectedPagesTouched": 0,
            "stage2BExecuted": False,
            "interpretationPerformed": False,
        },
        "priorityDefinitions": {
            "priority1": sorted(P1_CATEGORIES),
            "priority2": ["flow relationships explicitly linked to an active-operation candidate"],
            "priority3": ["architectural/context-only candidates or evidence with no active-operation blocker link"],
            "rankingUsesRawEvidenceVolume": False,
            "mappingClaimsEstablished": False,
        },
        "priority1Units": priority_groups["1"],
        "priority2Units": priority_groups["2"],
        "priority3Units": priority_groups["3"],
        "priorityCounts": {"totalCandidateUnits": len(units), "priority1": len(priority_groups["1"]),
                           "priority2": len(priority_groups["2"]), "priority3": len(priority_groups["3"])},
        "tieringNotes": {
            "flowRelationshipCandidateUnits": len(flow_candidates),
            "flowCandidatesAssignedToPriority1": sum(item["priority"] == 1 for item in flow_candidates),
            "standalonePriority2FlowUnits": len(priority_groups["2"]),
            "reason": "Flow evidence co-occurs with a Priority-1 operation/mapping/condition/integration signal in the current candidates; it remains listed on those Priority-1 units. No unit is elevated solely by diagram size or evidence volume.",
        },
        "firstBatch": {
            "selectionMode": "minimum blocker-signal cover with one separate candidate unit per active operation",
            "unitCount": len(first_batch),
            "whyThisIsTheSmallestUsefulFirstPass": "It allocates a distinct nonreusable candidate unit to GET, POST, and PATCH, then adds only the units needed to cover operation processing, persistence, request/response mappings, conditions, integrations, and explicit map-flow support. It tests evidence sufficiency without interpreting it or asserting that strict blockers are resolved.",
            "units": first_batch,
            "activeOperationCoverage": operation_coverage,
            "coveredPriority1EvidenceTypes": ["operation-specific processing", "persistence",
                                                "request/response mappings", "conditions", "integration behavior"],
            "coveredFlowRelationshipEvidenceTypes": ["flow relationships (supporting signals co-located with Priority-1 units)"],
            "existingReusableUnitsReinterpreted": 0,
        },
        "deferredStage2BUnits": deferred,
        "reusableStage2BResults": [{"unitId": item["unitId"], "semanticUnitIdentity": item["semanticUnitIdentity"],
                                     "file": item["file"], "semanticInputFingerprint": item.get("semanticInputFingerprint"),
                                     "status": "exact identity/fingerprint reusable; not in first batch"}
                                    for item in units if item["existingCurrentStage2BResultReusable"]],
        "inactiveReviewedOperations": {
            "separateFromActiveBatch": inactive_separate,
            "getByIdState": "ELIMINADO",
            "activeInterpretationAllowed": False,
        },
        "validation": {
            "batchOperationCoverageComplete": True,
            "batchContainsOnlyNonreusableUnits": True,
            "selectionBalancedAcrossActiveOperations": True,
            "geometryOrColorUsedAsSemanticSignal": False,
            "stage2BExecuted": False,
        },
    }
    payload = stable_yaml(plan_document, yaml)
    if OUTPUT.is_symlink() or not OUTPUT.resolve().is_relative_to(FACTORY.resolve()):
        raise PlanFailure("Priority plan output path is unsafe.")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=FACTORY, prefix=".stage2b-priority-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, OUTPUT)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print({"priorityCounts": plan_document["priorityCounts"], "firstBatchUnits": len(first_batch),
           "reusable": len(plan_document["reusableStage2BResults"]), "sha256": sha(payload)})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PlanFailure as exc:
        raise SystemExit(f"build_stage2b_priority.py: error: {exc}") from exc
