"""Spec writers for Phase 8.5 (called by consolidate_authoritative_specs.py after both readiness gates are true)."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import consolidate_authoritative_specs as core
import reconcile_specs as rs

ROOT, F = core.ROOT, core.F


def _decisions_applied(ctx: core.Context) -> list[dict[str, Any]]:
    rows = []
    for decision in ctx.decisions:
        effects = decision.get("machineEffects")
        if not effects:
            continue
        rows.append({
            "decisionId": decision["decisionId"], "humanReviewed": decision["humanReviewed"], "approvalStatus": decision.get("approvalStatus"),
            "targetOperations": decision["target"].get("operations"), "sourceConflict": decision["sourceConflict"],
            "approvedResolution": decision["approvedResolution"], "provenance": decision["provenance"],
            "affectedReadinessBlockers": decision["affectedReadinessBlockers"],
            "appliedEffects": sorted(set(ctx.consumed[decision["decisionId"]])), "appliedExactlyOnce": True,
        })
    return rows


def _deltas(ctx: core.Context, derived: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    deltas = []
    for method, op in derived.items():
        for response in op["effectiveResponses"]:
            if response["origin"] == "openapi":
                continue
            deltas.append({
                "operation": f"{method} {op['path']}", "operationId": op["operationId"], "change": "add-response", "status": response["status"],
                "originalOpenapi": response["originalOpenapi"], "authoritativeSparx": response["authoritativeSparx"],
                "humanReviewedDecision": f"{response['decisionId']} (409 approved)", "decisionId": response["decisionId"],
                "amendmentKind": "human-reviewed-contract-amendment", "schemaBasis": response["schemaBasis"],
                "originalOpenapiSourceModified": False,
                "recommendation": "Correct the input OpenAPI to declare 409 for this operation; until then the effective contract carries the delta.",
            })
    return deltas


def write_specs(ctx: core.Context, derived: dict[str, dict[str, Any]], register: dict[str, Any], readiness: dict[str, Any],
                source_hashes: dict[str, Any], archive: dict[str, Any], archetype_path: str) -> None:
    branch = ctx.branch
    identity = ctx.branch_identity
    inactive_decisions = [d for d in branch["reviewedLifecycleDecisions"] if d.get("disposition") == "inactive"]
    reviewed = core.load("decisions")["decisions"][0]
    inactive_ops = []
    for decision in inactive_decisions:
        sparx_only = next((m for m in branch["sparxOnlyMethods"] if m["name"] == f"{decision['method']}-{decision['path']}"), None)
        inactive_ops.append({
            "method": decision["method"], "path": decision["path"], "lifecycleState": decision["lifecycleState"], "disposition": "inactive",
            "decisionId": decision["decisionId"], "sparxMethod": {"page": sparx_only["page"], "guid": sparx_only["guid"]} if sparx_only else None,
            "reason": reviewed["reason"], "sourcePages": reviewed["sourcePages"], "evidenceIds": reviewed["evidenceIds"],
            "generation": "excluded; historical traceability only",
        })
    derived_assumptions = [{
        "id": "user-header-derived-mapping", "operations": [m for m, d in derived.items() if d["mappings"]["headerDerivedMappings"]],
        "statement": "INPUT userId (origin headerRequest) is tied to the x-user-id header: the only HeaderRequest row whose name normalizes to the INPUT destination; its description identifies the invoking user.",
        "classification": "technical-implementation-choice", "blocker": False,
        "evidence": {m: d["mappings"]["headerDerivedMappings"] for m, d in derived.items() if d["mappings"]["headerDerivedMappings"]},
    }]
    technical_choices = [i for i in register["items"] if i["classification"] == "technical-implementation-choice"]
    deltas = _deltas(ctx, derived)
    applied = _decisions_applied(ctx)
    table = ctx.table
    seq = core.load("sequence")
    source_pages: dict[str, str] = {}
    for d in derived.values():
        s = d["sources"]
        for key in ("method", "process", "validationActivity", "behaviorActivity"):
            if s[key].get("page"):
                source_pages[s[key]["page"]] = s[key].get("pageSha256") or ""
        source_pages[s["dataDefinition"]["page"]] = s["dataDefinition"]["sha256"]
        source_pages[s["validationLinkdoc"]["resolvedFile"]] = s["validationLinkdoc"]["sha256"]
        source_pages[s["behaviorLinkdoc"]["resolvedFile"]] = s["behaviorLinkdoc"]["sha256"]
    for o in seq["operations"]:
        for page, info in o["pagesRead"].items():
            source_pages.setdefault("input/sparx/PROYECT/" + page if not page.startswith("input/") else page, info["sha256"])
    all_evidence = sorted(core.evidence_ids(derived) | core.evidence_ids(table))
    nonauth = core.load("nonAuthoritative")

    def per_op(key: str) -> list[dict[str, Any]]:
        return [{"method": m, "path": d["path"], "operationId": d["operationId"], key: copy.deepcopy(d[key]), "authoritativeBranch": identity} for m, d in derived.items()]

    sparx_spec = {
        "version": 1, "kind": "sparx-spec", "phase": "8.5",
        "source": {"authority": source_hashes["authority"], "authoritativeEndpointDetail": source_hashes["detail"], "sequenceFlow": source_hashes["sequence"],
                   "proseInterpretation": source_hashes["prose"], "reviewedDecisions": source_hashes["decisions"],
                   "decisionReassessment": {"file": ".factory/sparx-decision-reassessment.yml", "sha256": core.sha256_file(".factory/sparx-decision-reassessment.yml")},
                   "previousSpecsArchive": archive},
        "target": {"service": ctx.authority["target"]["name"], "authoritativeBranch": identity,
                   "rootPages": [branch["service"]["page"]], "generationActiveBranch": identity["branchRootId"],
                   "traceabilityOnlyBranches": [{k: b[k] for k in ("branchRootId", "name", "pagePathPrefix", "authorityClass")} for b in ctx.authority["branches"] if b["authorityClass"] != "authoritative-candidate"]},
        "active": {
            "operations": [{"method": m, "path": d["path"], "operationId": d["operationId"], "sources": d["sources"]} for m, d in derived.items()],
            "processes": [{"method": m, "path": d["path"], "process": d["sources"]["process"], "flow": d["flow"]} for m, d in derived.items()],
            "actions": [{"method": m, "path": d["path"], "validationActivity": d["sources"]["validationActivity"], "behaviorActivity": d["sources"]["behaviorActivity"],
                         "actionKind": d["persistence"]["actionKind"], "actionKindBasis": d["persistence"]["actionKindBasis"]} for m, d in derived.items()],
            "integrations": [],
            "persistence": per_op("persistence"), "validations": per_op("validation"), "mappings": per_op("mappings"),
            "errors": [{"method": m, "path": d["path"], "operationId": d["operationId"], "outcomes": d["outcomes"], "effectiveResponses": d["effectiveResponses"]} for m, d in derived.items()],
        },
        "inactive": {"operations": inactive_ops, "actions": [], "integrations": []},
        "unresolved": {"conflicts": [], "ambiguities": [], "missingEvidence": []},
        "resolvedConflicts": register["items"],
        "humanDecisionsApplied": applied,
        "derivedAssumptions": derived_assumptions,
        "warnings": [
            {"warning": "Authoritative Sparx GET statement says AND/equality; the human-reviewed policy (OR/contains, at least one filter) is applied for generation. The Sparx text is preserved unchanged.", "decisionId": "human-reviewed-mailing-info-get-search-filter-policy"},
            {"warning": "Authoritative Sparx DML text uses TO/FROM/SUBJECT; physical names are normalized to the structured table (EMAILTO/EMAILFROM/EMAILSUBJECT) by human-reviewed decision.", "decisionId": "human-reviewed-mailing-info-physical-column-names"},
            {"warning": "Sparx database connection (URL/TNSNAMES/JNDI) is empty on all behavior activities; datasource wiring is an archetype-owned technical choice.", "decisionId": None},
        ],
        "traceability": {
            "evidenceUsed": all_evidence, "sourcePages": [{"page": p, "sha256": s} for p, s in sorted(source_pages.items())],
            "reviewedDecisions": [d["decisionId"] for d in applied] + [reviewed["decisionId"]],
            "nonAuthoritativeEvidence": {"file": core.PATHS["nonAuthoritative"], "sha256": core.sha256_file(core.PATHS["nonAuthoritative"]),
                                         "policy": nonauth["policy"], "usedForGeneration": False},
        },
        "readiness": {"contractReconciliationReady": True, "behaviorComplete": True, "implementationReady": True, "strictImplementationReady": True,
                      "functionalCodeGenerationReady": True, "scaffoldImplementationReady": True, "blockers": [], "nonBlockingIssues": [i["id"] for i in technical_choices],
                      "operations": readiness["operations"]},
        "validation": {"warnings": [], "errors": []},
        "architecturalEvidence": {"dataDefinitions": [{**{k: table[k] for k in ("page", "sha256", "identity", "columns", "keyAndIndexDeclarations", "associationRows")},
                                                       "role": "authoritative physical column names and types", "branchIdentity": identity,
                                                       "nullabilityDeclared": None, "defaultsDeclared": None,
                                                       "relationshipsOutsideTargetBehavior": "association rows (e.g. REQUEST FK) belong to other services' behavior and are not generation-active here"}],
                                 "logicalDataObjectsNotMerged": [d["page"] for d in ctx.detail["dataDefinitions"] if not d["definesColumns"]]},
        "unassignedArchitecturalEvidence": [],
    }
    sparx_bytes = core.encode(sparx_spec)
    (F / "sparx-spec.yml").write_bytes(sparx_bytes)

    # ------------------------------------------------------------------ service-spec
    openapi = ctx.api
    openapi_fingerprint = str(openapi["source"].get("sha256") or core.sha256_file(core.PATHS["openapi"]))
    artifact_sha = core.sha256_file(core.PATHS["openapi"])
    operations = []
    for index, api_op in enumerate(openapi["operations"]):
        method = api_op["method"]
        item = rs.build_operation(api_op, index, "matched", [], {}, openapi, openapi_fingerprint, artifact_sha)
        d = derived[method]
        contract_responses = {r["status"]: r for r in d["effectiveResponses"]}
        item["contract"]["effectiveResponses"] = d["effectiveResponses"]
        item["contract"]["contractDeltas"] = [x for x in deltas if x["operationId"] == d["operationId"]]
        item["behavior"] = {
            "matchStatus": "matched", "authoritativeBranch": identity, "sources": d["sources"], "processes": [{"process": d["sources"]["process"], "flow": d["flow"]}],
            "actions": [{"validationActivity": d["sources"]["validationActivity"], "behaviorActivity": d["sources"]["behaviorActivity"],
                         "actionKind": d["persistence"]["actionKind"]}],
            "integrations": [], "persistence": [d["persistence"]], "validations": [d["validation"]], "mappings": [d["mappings"]],
            "errors": [d["outcomes"]], "decisionsApplied": d["decisionsApplied"],
            "unresolved": {"ambiguities": [], "missingEvidence": []},
        }
        item["unresolved"] = {"ambiguities": [], "missingEvidence": []}
        item["traceability"] = {"openapi": item["traceability"]["openapi"],
                                "sparx": {"authoritativeBranch": identity, "sourcePages": d["sources"], "evidenceIds": sorted(core.evidence_ids(d))},
                                "reviewedDecisions": d["decisionsApplied"]}
        operations.append(item)
    openapi_validation = copy.deepcopy(openapi.get("validation") or {})
    contract_complete = bool(openapi_validation.get("valid")) and not (openapi_validation.get("errors") or [])
    service_spec = {
        "service": {"name": ctx.authority["target"]["name"], "contractVersion": (openapi.get("service") or {}).get("version"),
                    "description": (openapi.get("service") or {}).get("description"), "servers": copy.deepcopy(openapi.get("servers") or []),
                    "source": {"path": core.PATHS["openapi"], "fingerprint": openapi_fingerprint, "artifactSha256": artifact_sha}},
        "sources": {"openapi": {"path": core.PATHS["openapi"], "fingerprint": openapi_fingerprint, "artifactSha256": artifact_sha, "validation": openapi_validation},
                    "sparx": {"path": ".factory/sparx-spec.yml", "artifactSha256": hashlib.sha256(sparx_bytes).hexdigest(), "authoritativeBranch": identity,
                              "authority": source_hashes["authority"], "authoritativeEndpointDetail": source_hashes["detail"]},
                    "humanReviewedDecisions": source_hashes["decisions"],
                    "decisionReassessment": {"file": ".factory/sparx-decision-reassessment.yml", "sha256": core.sha256_file(".factory/sparx-decision-reassessment.yml")},
                    "archetype": {"file": archetype_path, "sha256": core.sha256_file(archetype_path)}},
        "operations": operations,
        "effectiveContractDeltas": deltas,
        "humanDecisions": {"applied": applied, "reviewedLifecycle": reviewed["decisionId"]},
        "behaviorContext": {
            "processes": sparx_spec["active"]["processes"], "actions": sparx_spec["active"]["actions"], "integrations": [],
            "persistence": sparx_spec["active"]["persistence"], "validations": sparx_spec["active"]["validations"], "mappings": sparx_spec["active"]["mappings"],
            "errors": sparx_spec["active"]["errors"], "architecturalEvidence": sparx_spec["architecturalEvidence"], "unassignedArchitecturalEvidence": [],
        },
        "inactive": copy.deepcopy(sparx_spec["inactive"]),
        "unresolved": {"conflicts": [], "ambiguities": [], "missingEvidence": []},
        "resolvedConflicts": register["items"],
        "technicalImplementationChoices": technical_choices,
        "derivedAssumptions": derived_assumptions,
        "warnings": {"openapi": copy.deepcopy(openapi_validation.get("warnings") or []), "sparx": copy.deepcopy(sparx_spec["warnings"])},
        "traceability": {"openapi": {"path": core.PATHS["openapi"], "fingerprint": openapi_fingerprint, "artifactSha256": artifact_sha},
                         "sparx": {"authoritativeBranch": identity, "traceabilityOnlyBranches": sparx_spec["target"]["traceabilityOnlyBranches"],
                                   "nonAuthoritativeEvidence": sparx_spec["traceability"]["nonAuthoritativeEvidence"]}},
        "statistics": {"activeOpenapiOperations": len(operations), "matched": len(operations), "partiallyMatched": 0, "noSparxBehavior": 0, "ambiguous": 0,
                       "inactiveSparxOperations": len(inactive_ops), "conflicts": 0, "targetImplementationBlockers": 0, "unassignedArchitecturalEvidence": 0,
                       "effectiveContractDeltas": len(deltas), "humanDecisionsApplied": len(applied), "technicalImplementationChoices": len(technical_choices)},
        "readiness": {
            "contractComplete": contract_complete, "behaviorComplete": True, "implementationReady": True, "strictImplementationReady": True,
            "functionalCodeGenerationReady": True, "scaffoldImplementationReady": True, "specConsolidationComplete": True, "implementationPlanningReady": True,
            "analysisStatus": {"scope": "authoritative Sparx branch 0.2 (EA2) + OpenAPI + approved human-reviewed decisions", "implementationBlocker": False},
            "blockers": [], "nonBlockingIssues": [i["id"] for i in technical_choices], "operations": readiness["operations"],
            "effectiveContractDeltas": [{"operation": x["operation"], "status": x["status"], "decisionId": x["decisionId"]} for x in deltas],
        },
        "validation": {"warnings": [], "errors": []},
    }
    (F / "service-spec.yml").write_bytes(core.encode(service_spec))
    print({"sparx-spec": hashlib.sha256(sparx_bytes).hexdigest(), "service-spec": core.sha256_file(".factory/service-spec.yml")})
